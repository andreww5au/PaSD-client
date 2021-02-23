#!/usr/bin/env python

"""Classes to handle communications with SKA-Low PaSD 'SMARTbox' elements, 24 of which make
   up an SKA-Low station.
"""

import json
import logging
import time

logging.basicConfig()
logger = logging.getLogger()
logger.level = logging.DEBUG

import conversion
import transport


# Dicts with register name as key, and a tuple of (register_number, number_of_registers, name, scaling_function) as value
FNDH_POLL_REGS_1 = {  # These initial registers will be assumed to be fixed, between register map revisions
                        'SYS_MBRV':    (1, 1, 'Modbus register map revision', None),
                        'SYS_PCBREV':  (2, 1, 'PCB Revision number', None),
                        'SYS_CPUID':   (3, 2, 'Microcontroller device ID', None),
                        'SYS_CHIPID':  (5, 8, 'Chip unique device ID', None),
                        'SYS_FIRMVER': (13, 1, 'Firmware version', None),
                        'SYS_UPTIME':  (14, 1, 'Uptime in seconds', None),
                        'SYS_ADDRESS': (15, 1, 'MODBUS station ID', None),

                        # From here on can change between firmware revisions
                        'SYS_48V_V':     (16, 1, 'Incoming 48VDC voltage', conversion.scale_48v),
                        'SYS_PSU_V':     (17, 1, 'PSU output voltage', conversion.scale_5v),
                        'SYS_PSUTEMP': (18, 1, 'PSU Temperature', conversion.scale_temp),
                        'SYS_PCBTEMP': (19, 1, 'PCB Temperature', conversion.scale_temp),
                        'SYS_OUTTEMP': (20, 1, 'Outside Temperature', conversion.scale_temp),
                        'SYS_STATUS':  (21, 1, 'System status code', None),
                        'SYS_LIGHTS':  (22, 1, 'LED state codes', None),

                        # Per-port status variables
                        'P01_TURNON': (35, 1, 'Port 01 Turn-on register', conversion.scale_temp),
                        'P01_HEALTH': (36, 1, 'Port 01 Health bitmap', conversion.scale_temp),
                        'P02_TURNON': (37, 1, 'Port 02 Turn-on register', conversion.scale_temp),
                        'P02_HEALTH': (38, 1, 'Port 02 Health bitmap', conversion.scale_temp),
                        'P03_TURNON': (39, 1, 'Port 03 Turn-on register', conversion.scale_temp),
                        'P03_HEALTH': (40, 1, 'Port 03 Health bitmap', conversion.scale_temp),
                        'P04_TURNON': (41, 1, 'Port 04 Turn-on register', conversion.scale_temp),
                        'P04_HEALTH': (42, 1, 'Port 04 Health bitmap', conversion.scale_temp),
                        'P05_TURNON': (43, 1, 'Port 05 Turn-on register', conversion.scale_temp),
                        'P05_HEALTH': (44, 1, 'Port 05 Health bitmap', conversion.scale_temp),
                        'P06_TURNON': (45, 1, 'Port 06 Turn-on register', conversion.scale_temp),
                        'P06_HEALTH': (46, 1, 'Port 06 Health bitmap', conversion.scale_temp),
                        'P07_TURNON': (47, 1, 'Port 07 Turn-on register', conversion.scale_temp),
                        'P07_HEALTH': (48, 1, 'Port 07 Health bitmap', conversion.scale_temp),
                        'P08_TURNON': (49, 1, 'Port 08 Turn-on register', conversion.scale_temp),
                        'P08_HEALTH': (50, 1, 'Port 08 Health bitmap', conversion.scale_temp),
                        'P09_TURNON': (51, 1, 'Port 09 Turn-on register', conversion.scale_temp),
                        'P09_HEALTH': (52, 1, 'Port 09 Health bitmap', conversion.scale_temp),
                        'P10_TURNON': (53, 1, 'Port 10 Turn-on register', conversion.scale_temp),
                        'P10_HEALTH': (54, 1, 'Port 10 Health bitmap', conversion.scale_temp),
                        'P11_TURNON': (55, 1, 'Port 11 Turn-on register', conversion.scale_temp),
                        'P11_HEALTH': (56, 1, 'Port 11 Health bitmap', conversion.scale_temp),
                        'P12_TURNON': (57, 1, 'Port 12 Turn-on register', conversion.scale_temp),
                        'P12_HEALTH': (58, 1, 'Port 12 Health bitmap', conversion.scale_temp),
}

FNDH_CONF_REGS_1 = {

}

FNDH_CODES_1 = {'status':{'fromid':{0:'UNINITIALISED', 1:'OK', 2:'ALARM', 3:'WARNING', 4:'RECOVERY'},
                          'fromname':{'UNINITIALISED':0, 'OK':1, 'ALARM':2, 'WARNING':3, 'RECOVERY':4}},
                'leds':{'fromid':{0:'OFF', 1:'GREEN', 2:'RED', 3:'YELLOW'},
                        'fromname':{'OFF':0, 'GREEN':1, 'RED':2, 'YELLOW':3}}}


# Dicts with register version number as key, and a dict of registers (defined above) as value
FNDH_REGISTERS = {1: {'POLL':FNDH_POLL_REGS_1, 'CONF':FNDH_CONF_REGS_1}}
FNDH_CODES = {1: FNDH_CODES_1}

THRESHOLD_FILENAME = 'fndh_thresholds.json'
PORTCONFIG_FILENAME = 'fndh_ports.json'


class FNDH(transport.ModbusSlave):
    def __init__(self, conn=None, modbus_address=None):
        transport.ModbusSlave.__init__(self, conn=conn, modbus_address=modbus_address)

        self.mbrv = None
        self.pcbrv = None
        self.register_map = {}
        self.codes = {}
        self.cpuid = ''
        self.chipid = []
        self.firmware_version = 0
        self.uptime = 0
        self.station_value = 0
        self.psu_voltage = 0.0
        self.psu_temp = 0.0
        self.pcb_temp = 0.0
        self.outside_temp = 0.0
        self.statuscode = 0
        self.status = ''
        self.service_led = None
        self.indicator_code = None
        self.indicator_state = ''
        self.readtime = 0    # Unix timestamp for the last successful polled data from this FNDH
        try:
            self.thresholds = json.load(open(THRESHOLD_FILENAME, 'r'))
        except Exception:
            self.thresholds = None
        try:
            allports = json.load(open(PORTCONFIG_FILENAME, 'r'))
            self.portconfig = allports[self.modbus_address]
        except Exception:
            self.portconfig = None

    def poll_data(self):
        """
        Get all the polled registers from the device, and use the contents to fill in the instance data for this station

        :return:
        """
        maxregnum = max([data[0] for data in self.register_map['POLL'].values()])
        maxregname = [name for (name, data) in self.register_map['POLL'].items() if data[0] == maxregnum]
        poll_blocksize = maxregnum + (self.register_map['POLL'][maxregname][1] - 1)  # number of registers to read

        # Get a list of tuples, where each tuple is a two-byte register value, eg (0,255)
        try:
            valuelist = self.conn.readReg(modbus_address=self.modbus_address, regnum=1, numreg=poll_blocksize)
        except Exception:
            logger.exception('Exception in readReg in poll_data for FNDH')
            return None

        read_timestamp = time.time()
        if valuelist is None:
            logger.error('Error in readReg in poll_data for FNDH, no data')
            return None

        if len(valuelist) != poll_blocksize:
            logger.warning(
                'Only %d registers returned from FNSH by readReg in poll_data, expected %d' % (len(valuelist), poll_blocksize))

        self.mbrv = transport.bytestoN(valuelist[0])
        self.pcbrv = transport.bytestoN(valuelist[1])
        self.register_map = FNDH_REGISTERS[self.mbrv]
        self.codes = FNDH_CODES[self.mbrv]

        # TODO - Parse all the registers here

        self.readtime = read_timestamp

    def configure(self, thresholds=None, portconfig=None):
        """
         Get the threshold data (as given, or from the config file), and write it to the SMARTbox.

         If that succeeds, read the port configuration (desired state online, desired state offline) from the config
         file (if it's not supplied), and write it to the SMARTbox.

         Then, if that succeeds, write a '1' to the status register to tell the micontroller to
         transition out of the 'UNINITIALISED' state.

         :param thresholds: A dictionary containing the ADC thresholds to write to the SMARTbox. If none, use defaults
                            from the JSON file specified in THRESHOLD_FILENAME
         :param portconfig: A dictionary containing the port configuration data to write to the SMARTbox. If none, use
                            defaults from the JSON file specified in PORTCONFIG_FILENAME
         :return: True for sucess
         """
        if thresholds:
            self.thresholds = thresholds

        if portconfig:
            self.portconfig = portconfig
