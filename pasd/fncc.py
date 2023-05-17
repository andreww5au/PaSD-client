#!/usr/bin/env python

"""Classes to handle communications with SKA-Low PaSD 'SMARTbox' elements, 24 of which make
   up an SKA-Low station.

   This code runs on the MCCS side in the control building, and talks to the FNCC (communications microcontroller) inside
   a physical FNDH module in the field.
"""

import json
import logging
import time

logging.basicConfig()

from pasd import transport    # Modbus API
from pasd import command_api  # System register API, for reset, firmware upload and rapid sampling

# Register definitions and status code mapping - only one mapping here now (FNCC_POLL_REGS_1,
# FNCC_CONF_REGS_1 and FNCC_CODES_1), and these define the registers and codes for Modbus register map
# revision 1 (where SYS_MBRV==1).
#
# When firmware updates require a new register map and status codes, define new dictionaries FNDH_POLL_REGS_2,
# FNCC_CONF_REGS_2, and FNCC_CODES_2, and add them to the FNDH_REGISTERS and FNDH_CODES dictionaries.
#
# When a FNCC is contacted, the SYS_MBRV register value (always defined to be in register 1) will be used to load
# the appropriate register map and status codes.
#
# Register maps are dictionaries with register name as key, and a tuple of (register_number, number_of_registers,
# description, scaling_function) as value.

FNCC_POLL_REGS_1 = {  # These initial registers will be assumed to be fixed, between register map revisions
                        'SYS_MBRV':    (1, 1, 'Modbus register map revision', None),
                        'SYS_PCBREV':  (2, 1, 'PCB Revision number', None),
                        'SYS_CPUID':   (3, 2, 'Microcontroller device ID', None),
                        'SYS_CHIPID':  (5, 8, 'Chip unique device ID', None),
                        'SYS_FIRMVER': (13, 1, 'Firmware version', None),
                        'SYS_UPTIME':  (14, 2, 'Uptime in seconds', None),
                        'SYS_ADDRESS': (16, 1, 'MODBUS station ID', None),

}


# Translation between the integer in the SYS_STATUS register (.statuscode), and .status string
# Note that the -1 (UNKNOWN) is for internal use only, if we haven't polled the hardware yet - we can't ever
# receive a -1 from the actual hardware.
STATUS_UNKNOWN = -1       # No contact with hardware yet, we don't know the status code
STATUS_OK = 0             # Initialised, system health OK
STATUS_WARNING = 1        # Initialised, and at least on sensor in WARNING, but none in ALARM or RECOVERY
STATUS_ALARM = 2          # Initialised, and at least one sensor in ALARM
STATUS_RECOVERY = 3       # Initialised, and at least one sensor in RECOVERY, but none in ALARM
STATUS_UNINITIALISED = 4  # NOT initialised, regardless of sensor states
STATUS_POWERUP = 5        # Local tech wants the MCCS to turn off all ports, then go through full powerup sequence (long press)
STATUS_CODES = {-1:'STATUS_UNKNOWN',
                0:'STATUS_OK',
                1:'STATUS_WARNING',
                2:'STATUS_ALARM',
                3:'STATUS_RECOVERY',
                4:'STATUS_UNINITIALISED',
                5:'STATUS_POWERUP'}


# Dicts with register version number as key, and a dict of registers (defined above) as value
FNCC_REGISTERS = {1: {'POLL':FNCC_POLL_REGS_1, 'CONF':{}},
                  3: {'POLL':FNCC_POLL_REGS_1, 'CONF':{}}}    # Added to support a buggy firmware version

STATUS_STRING = """\
FNDH at address: %(modbus_address)s:
    ModBUS register revision: %(mbrv)s
    PCB revision: %(pcbrv)s
    CPU ID: %(cpuid)s
    CHIP ID: %(chipid)s
    Firmware revision: %(firmware_version)s
    Uptime: %(uptime)s seconds
    R.Address: %(station_value)s
"""


class FNCC(transport.ModbusDevice):
    """
    FNCC class, an instance of which represents the microcontroller inside the FNDH in an SKA-Low station, sitting
    (virtually) on the same shared low-speed serial bus used to communicate with the SMARTboxes.

    Attributes are:
    modbus_address: Modbus address of the FNDH (usually 31)
    mbrv: Modbus register-map revision number for this physical FNDH
    pcbrv: PCB revision number for this physical FNDH
    register_map: A dictionary mapping register name to (register_number, number_of_registers, description, scaling_function) tuple
    cpuid: CPU identifier (integer)
    chipid: Unique ID number (16 bytes as ASCII hex), different for every physical FNDH
    firmware_version: Firmware revision mumber for this physical FNDH
    uptime: Time in seconds since this FNDH was powered up
    station_value: Modbus address read back from the SYS_ADDRESS register - should always equal modbus_address
    """

    def __init__(self, conn=None, modbus_address=None, logger=None):
        """
        Instantiate an instance of FNCC() using a connection object, and the modbus address for the FNDH
        (usually 31).

        This initialisation function doesn't communicate with the FNDH hardware, it just sets up the
        data structures.

        :param conn: An instance of transport.Connection() defining a connection to an FNDH
        :param modbus_address: Modbus address of the FNDH (usually 31)
        """
        transport.ModbusDevice.__init__(self, conn=conn, modbus_address=modbus_address, logger=logger)

        self.mbrv = None   # Modbus register-map revision number for this physical FNDH
        self.pcbrv = None  # PCB revision number for this physical FNDH
        self.register_map = {}  # A dictionary mapping register name to (register_number, number_of_registers, description, scaling_function) tuple
        self.cpuid = ''  # CPU identifier (integer)
        self.chipid = ''  # Unique ID number (16 bytes as ASCII hex), different for every physical FNDH
        self.firmware_version = 0  # Firmware revision mumber for this physical FNDH
        self.uptime = 0  # Time in seconds since this FNDH was powered up
        self.station_value = 0  # Modbus address read back from the SYS_ADDRESS register - should always equal modbus_address
        self.readtime = 0    # Unix timestamp for the last successful polled data from this FNDH

    def __str__(self):
        tmpdict = self.__dict__.copy()
        tmpdict['status_age'] = time.time() - self.readtime
        return ((STATUS_STRING % tmpdict))

    def __repr__(self):
        return str(self)

    def poll_data(self):
        """
        Get all the polled registers from the device, and use the contents to fill in the instance data for this instance.

        :return:True for success, None if there were any errors.
        """
        if self.register_map:  # We've talked to this box before, so we know the actual register map
            tmp_regmap = self.register_map['POLL']
        else:   # We haven't talked to this box, so use a default map to get the registers to read this time
            tmp_regmap = FNCC_POLL_REGS_1
        maxregnum = max([data[0] for data in tmp_regmap.values()])
        maxregname = [name for (name, data) in tmp_regmap.items() if data[0] == maxregnum][0]
        poll_blocksize = maxregnum + (tmp_regmap[maxregname][1] - 1)  # number of registers to read

        # Get a list of tuples, where each tuple is a two-byte register value, eg (0,255)
        try:
            valuelist = self.conn.readReg(modbus_address=self.modbus_address, regnum=1, numreg=poll_blocksize)
        except IOError:
            self.logger.info('No data returned by readReg in poll_data for FNDH')
            return None
        except Exception:
            self.logger.exception('Exception in readReg in poll_data for FNDH')
            return None

        read_timestamp = time.time()
        if valuelist is None:
            self.logger.error('Error in readReg in poll_data for FNDH, no data')
            return None

        if len(valuelist) != poll_blocksize:
            self.logger.warning('Only %d registers returned from FNSH by readReg in poll_data, expected %d' % (len(valuelist), poll_blocksize))

        self.mbrv = transport.bytestoN(valuelist[0])
        self.pcbrv = transport.bytestoN(valuelist[1])
        self.register_map = FNCC_REGISTERS[self.mbrv]

        for regname in self.register_map['POLL'].keys():  # Iterate over all the register names in the current register map
            regnum, numreg, regdesc, scalefunc = self.register_map['POLL'][regname]
            raw_value = valuelist[regnum - 1:regnum + numreg - 1]
            # print('%s: %s' % (regname, raw_value))
            raw_int = None
            if numreg <= 2:
                raw_int = transport.bytestoN(raw_value)
            # Go through all the registers and update the instance data.
            if regname == 'SYS_CPUID':
                self.cpuid = hex(raw_int)
            elif regname == 'SYS_CHIPID':
                bytelist = []
                for byte_tuple in bytelist:
                    bytelist += list(byte_tuple)
                self.chipid = ''.join([hex(v)[-2:].upper() for v in bytelist])
            elif regname == 'SYS_FIRMVER':
                self.firmware_version = raw_int
            elif regname == 'SYS_UPTIME':
                self.uptime = raw_int
            elif regname == 'SYS_ADDRESS':
                self.station_value = raw_int

        self.readtime = read_timestamp
        return True

    def reset(self):
        """
        Sends a command to reset the microcontroller.

        :return: None
        """
        command_api.reset_microcontroller(conn=self.conn,
                                          address=self.modbus_address,
                                          logger=self.logger)


"""
Use as 'communicate.py fncc', or:

from pasd import transport
from pasd import fncc
conn = transport.Connection(hostname='134.7.50.185')  # address of ethernet-serial bridge
# or
conn = transport.Connection(devicename='/dev/ttyS0')  # or 'COM5' for example, under Windows

fc = fndh.FNCC(conn=conn, modbus_address=100)
fc.poll_data()
fc.configure_all_off()
fc.configure_final()
"""
