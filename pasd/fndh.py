#!/usr/bin/env python

"""Classes to handle communications with SKA-Low PaSD 'SMARTbox' elements, 24 of which make
   up an SKA-Low station.

   This code runs on the MCCS side in the control building, and talks to a physical FNDH module in the field.
"""

import json
import logging
import time

logging.basicConfig()

from pasd import conversion   # Conversion functions between register values and actual temps/voltages/currents
from pasd import smartbox     # SMARTbox controller, so we can subclass the PortStatus class
from pasd import transport    # Modbus API

# Register definitions and status code mapping - only one mapping here now (FNDH_POLL_REGS_1,
# FNDH_CONF_REGS_1 and FNDH_CODES_1), and these define the registers and codes for Modbus register map
# revision 1 (where SYS_MBRV==1).
#
# When firmware updates require a new register map and status codes, define new dictionaries FNDH_POLL_REGS_2,
# FNDH_CONF_REGS_2, and FNDH_CODES_2, and add them to the FNDH_REGISTERS and FNDH_CODES dictionaries.
#
# When a FNDH is contacted, the SYS_MBRV register value (always defined to be in register 1) will be used to load
# the appropriate register map and status codes.
#
# Register maps are dictionaries with register name as key, and a tuple of (register_number, number_of_registers,
# description, scaling_function) as value.

FNDH_POLL_REGS_1 = {  # These initial registers will be assumed to be fixed, between register map revisions
                        'SYS_MBRV':    (1, 1, 'Modbus register map revision', None),
                        'SYS_PCBREV':  (2, 1, 'PCB Revision number', None),
                        'SYS_CPUID':   (3, 2, 'Microcontroller device ID', None),
                        'SYS_CHIPID':  (5, 8, 'Chip unique device ID', None),
                        'SYS_FIRMVER': (13, 1, 'Firmware version', None),
                        'SYS_UPTIME':  (14, 2, 'Uptime in seconds', None),
                        'SYS_ADDRESS': (16, 1, 'MODBUS station ID', None),

                        # From here on register address and contents can change between firmware revisions
                        'SYS_48V1_V': (17, 1, '48VDC PSU 1 output voltage', conversion.scale_48v),
                        'SYS_48V2_V': (18, 1, '48VDC PSU 2 output voltage', conversion.scale_48v),
                        'SYS_5V_V':    (19, 1, '5VDC PSU output voltage', conversion.scale_5v),
                        'SYS_48V_I':   (20, 1, 'Total 48VDC output current', conversion.scale_48vcurrent),
                        'SYS_48V_TEMP': (21, 1, '48VDC PSU 1+2 temperature', conversion.scale_temp),
                        'SYS_5V_TEMP': (22, 1, '5VDC PSU temperature', conversion.scale_temp),
                        'SYS_PCBTEMP': (23, 1, 'PCB temperature', conversion.scale_temp),
                        'SYS_OUTTEMP': (24, 1, 'Outside temperature', conversion.scale_temp),
                        'SYS_STATUS':  (25, 1, 'System status code', None),
                        'SYS_LIGHTS':  (26, 1, 'LED state codes', None),

                        # Per-port status variables
                        'P01_STATE': (27, 1, 'Port 01 state bitmap (r/w)', None),
                        'P02_STATE': (28, 1, 'Port 02 state bitmap (r/w)', None),
                        'P03_STATE': (29, 1, 'Port 03 state bitmap (r/w)', None),
                        'P04_STATE': (30, 1, 'Port 04 state bitmap (r/w)', None),
                        'P05_STATE': (31, 1, 'Port 05 state bitmap (r/w)', None),
                        'P06_STATE': (32, 1, 'Port 06 state bitmap (r/w)', None),
                        'P07_STATE': (33, 1, 'Port 07 state bitmap (r/w)', None),
                        'P08_STATE': (34, 1, 'Port 08 state bitmap (r/w)', None),
                        'P09_STATE': (35, 1, 'Port 09 state bitmap (r/w)', None),
                        'P10_STATE': (36, 1, 'Port 10 state bitmap (r/w)', None),
                        'P11_STATE': (37, 1, 'Port 11 state bitmap (r/w)', None),
                        'P12_STATE': (38, 1, 'Port 12 state bitmap (r/w)', None),
                        'P13_STATE': (39, 1, 'Port 13 state bitmap (r/w)', None),
                        'P14_STATE': (40, 1, 'Port 14 state bitmap (r/w)', None),
                        'P15_STATE': (41, 1, 'Port 15 state bitmap (r/w)', None),
                        'P16_STATE': (42, 1, 'Port 16 state bitmap (r/w)', None),
                        'P17_STATE': (43, 1, 'Port 17 state bitmap (r/w)', None),
                        'P18_STATE': (44, 1, 'Port 18 state bitmap (r/w)', None),
                        'P19_STATE': (45, 1, 'Port 19 state bitmap (r/w)', None),
                        'P20_STATE': (46, 1, 'Port 20 state bitmap (r/w)', None),
                        'P21_STATE': (47, 1, 'Port 21 state bitmap (r/w)', None),
                        'P22_STATE': (48, 1, 'Port 22 state bitmap (r/w)', None),
                        'P23_STATE': (49, 1, 'Port 23 state bitmap (r/w)', None),
                        'P24_STATE': (50, 1, 'Port 24 state bitmap (r/w)', None),
                        'P25_STATE': (51, 1, 'Port 25 state bitmap (r/w)', None),
                        'P26_STATE': (52, 1, 'Port 26 state bitmap (r/w)', None),
                        'P27_STATE': (53, 1, 'Port 27 state bitmap (r/w)', None),
                        'P28_STATE': (54, 1, 'Port 28 state bitmap (r/w)', None),
}

# TODO - add PDoC port serial number block (28 * 4 registers) in here, to be read once on boot, not polled.

# System threshold configuration registers (not polled)
FNDH_CONF_REGS_1 = {  # thresholds with over-value alarm and warning, as well as under-value alarm and warning
                    'SYS_48V1_V_TH':(1001, 4, '48V PSU 1, 48VDC voltage AH, WH, WL, AL', conversion.scale_48v),
                    'SYS_48V2_V_TH':(1005, 4, '48V PSU 2, 48VDC voltage AH, WH, WL, AL', conversion.scale_48v),
                    'SYS_5V_V_TH':(1009, 4, '5V PSU output voltage AH, WH, WL, AL', conversion.scale_5v),
                    'SYS_48V_I_TH':(1013, 4, '48V PSU output current AH, WH, WL, AL', conversion.scale_48vcurrent),
                    'SYS_48V_TEMP_TH':(1017, 4, '48V PSU temperature AH, WH, WL, AL', conversion.scale_temp),
                    'SYS_5V_TEMP_TH':(1021, 4, '5V PSU temperature AH, WH, WL, AL', conversion.scale_temp),
                    'SYS_PCBTEMP_TH':(1025, 4, 'PCB temperature AH, WH, WL, AL', conversion.scale_temp),
                    'SYS_OUTTEMP_TH':(1029, 4, 'Outside temperature AH, WH, WL, AL', conversion.scale_temp),
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


# Translation between the integer the SYS_LIGHTS MSB (.indicator_code) and the .indicator_status string
# Note that the -1 (UNKNOWN) is for internal use only, if we haven't polled the hardware yet - we can't ever
# receive a -1 from the actual hardware.
LED_UNKNOWN = -1        # No contact with hardware yet, we don't know what the LED state is
LED_OFF = 0             # Probably never used, so we can tell if the power is on or off

LED_GREEN = 10          # OK and 'offline' (haven't heard from MCCS lately)
LED_GREENSLOW = 11      # OK and 'online'
LED_GREENFAST = 12
LED_GREENVFAST = 13
LED_GREENDOTDASH = 14

LED_YELLOW = 20         # WARNING and 'offline'
LED_YELLOWSLOW = 21     # WARNING
LED_YELLOWFAST = 22     # Uninitialised - thresholds not written
LED_YELLOWVFAST = 23
LED_YELLOWDOTDASH = 24

LED_RED = 30            # ALARM and 'offline'
LED_REDSLOW = 31        # ALARM
LED_REDFAST = 32
LED_REDVFAST = 33
LED_REDDOTDASH = 34

LED_YELLOWRED = 40      # RECOVERY and 'offline' (alternating yellow and red with no off-time)
LED_YELLOWREDSLOW = 41  # RECOVERY (alternating short yellow and short red flashes)

LED_GREENRED = 50       # Waiting for restart from MCCS after long button press

LED_CODES = {-1:'UKNOWN',
             0:'OFF',
             10:'GREEN',
             11:'GREENSLOW',
             12:'GREENFAST',
             13:'GREENVFAST',
             14:'GREENDOTDASH',

             20:'YELLOW',
             21:'YELLOWSLOW',
             22:'YELLOWFAST',
             23:'YELLOWVFAST',
             24:'YELLOWDOTDASH',

             30:'RED',
             31:'REDSLOW',
             32:'REDFAST',
             33:'REDVFAST',
             34:'REDDOTDASH',

             40:'YELLOWRED',
             41:'YELLOWREDSLOW',

             50:'GREENRED'}


# Dicts with register version number as key, and a dict of registers (defined above) as value
FNDH_REGISTERS = {1: {'POLL':FNDH_POLL_REGS_1, 'CONF':FNDH_CONF_REGS_1}}

THRESHOLD_FILENAME = 'pasd/fndh_thresholds.json'
PORTCONFIG_FILENAME = 'pasd/fndh_ports.json'

STATUS_STRING = """\
FNDH at address: %(modbus_address)s:
    ModBUS register revision: %(mbrv)s
    PCB revision: %(pcbrv)s
    CPU ID: %(cpuid)s
    CHIP ID: %(chipid)s
    Firmware revision: %(firmware_version)s
    Uptime: %(uptime)s seconds
    R.Address: %(station_value)s
    48V Out 1: %(psu48v1_voltage)s V
    48V Out 2: %(psu48v2_voltage)s V
    5V out: %(psu5v_voltage)s V
    48V Current: %(psu48v_current)s A 
    48V Temp: %(psu48v_temp)s deg C
    5V Temp: %(psu5v_temp)s deg C
    PCB Temp: %(pcb_temp)s deg C
    Outside Temp: %(outside_temp)s deg C
    Status: %(statuscode)s (%(status)s)
    Service LED: %(service_led)s
    Indicator: %(indicator_code)s (%(indicator_state)s)
"""


class PdocStatus(smartbox.PortStatus):
    """
        FNDH PDoC port status instance, representing one of the 28 FEM PDoC ports that supply 48VDC and
        serial comms to SMARTboxes in the field, making up a station.

        Some of the attributes inherited from the smartbox.PortStatus class are unused here, for PDoC port status
        instances.

        Attributes are:
        port_number: Which PDoC port this is (1-28)
        modbus_address: Modbus address of the FNDH microcontroller (should always be 31)
        smartbox_address: Modbus address of the SMARTbox connected to this PDoC port (1-30) (populated externally by the station startup code)
        status_bitmap: Raw contents of the P<NN>_STATE register for this port (0-65535)
        current_timestamp: Unused
        current_raw: Unused
        current: Unused
        status_timestamp: Unix epoch at the time the P<NN>_STATE register was last read (integer)
        system_level_enabled: Has the FNDH decided that it's in a safe state (not overheated, etc) (Boolean)
        system_online: Has the FNDH decided that it's heard from the MCCS recently enough to go online (Boolean)
        desire_enabled_online: Does the MCCS want this PDoC port enabled when the device is online (Boolean)
        desire_enabled_offline:Does the MCCS want this PDoC port enabled when the device is offline (Boolean)
        locally_forced_on: Has this PDoC port been locally forced ON by a technician overide (Boolean)
        locally_forced_off: Has this PDoC port been locally forced OFF by a technician overide (Boolean)
        breaker_tripped: Unused
        power_state: Is this port switched ON (Boolean)
        power_sense: True if 48V power is detected on the output of this port
        antenna_number: Unused

        Note that modbus_address, system_level_enabled and system_online have the the same values for all ports.
    """
    def __init__(self, port_number, modbus_address, status_bitmap, read_timestamp, logger=None):
        """
        Instantiate an instance of a PdocStatus() object.

        This initialisation function doesn't communicate with the port hardware, it just sets up the
        data structures.

        :param port_number: Which PDoC port this is (1-28)
        :param modbus_address: Modbus address of the FNDH microcontroller (should always be 31)
        :param status_bitmap: Raw contents of the P<NN>_STATE register for this port (0-65535)
        :param read_timestamp: Unix epoch at the time the P<NN>_STATE register was last read (integer)
        """
        smartbox.PortStatus.__init__(self, port_number, modbus_address, status_bitmap, 0, 0.0, read_timestamp, logger=logger)

        self.smartbox_address = 0   # populated by the station initialisation code on powerup
        self.power_sense = None  # True if 48V power is detected on the output of this port

    def set_status_data(self, status_bitmap, read_timestamp):
        """
        Given a status bitmap (from one of the P<NN>_STATE registers), update the instance with the new data.

        :param status_bitmap:  integer, 0-65535 - state bitmap from P<NN>_STATE register
        :param read_timestamp:  float - unix timetamp when the data was pulled from the SMARTbox
        :return: None
        """
        smartbox.PortStatus.set_status_data(self, status_bitmap, read_timestamp)

        # In an FNDH, there is no breaker - instead there's a 'Power Sense' bit. It's RO, so use desired_enabled_* to
        # force the port to turn off then on again to reset it.
        self.raw_bitmap = status_bitmap
        self.power_sense = self.breaker_tripped
        self.breaker_tripped = None

    def __str__(self):
        if self.status_timestamp is None:
            status_string = "Unknown"
        else:
            if self.locally_forced_on:
                lfstring = 'Forced:ON'
            elif self.locally_forced_off:
                lfstring = 'Forced:OFF'
            else:
                lfstring = 'NotForced'
            enstring = '(DesireEnabled:%s)' % ','.join([{False:'', True:'Online', None:'?'}[self.desire_enabled_online],
                                                       {False:'', True:'Offline', None:'?'}[self.desire_enabled_offline]])
            sysstring = '(System:%s,%s)' % ({False:'Offline', True:'Online', None:'??line?'}[self.system_online],
                                            {False:'Disabled', True:'Enabled', None:'??abled?'}[self.system_level_enabled])
            status_items = ['%s: Status(age %1.1f s):' % (self.raw_bitmap, time.time() - self.status_timestamp),
                            {False:'Power:OFF', True:'Power:ON', None:'Power:?'}[self.power_state],
                            sysstring,
                            enstring,
                            lfstring,
                            {False:'PowerSense:OFF', True:'PowerSense:ON', None:'PowerSense:?'}[self.power_sense]
                            ]
            status_string = ' '.join(status_items)

        return "P%02d: %s" % (self.port_number, status_string)


class FNDH(transport.ModbusDevice):
    """
    FNDH class, an instance of which represents the microcontroller inside the FNDH in an SKA-Low station, sitting
    (virtually) on the same shared low-speed serial bus used to communicate with the SMARTboxes.

    Attributes are:
    modbus_address: Modbus address of the FNDH (usually 31)
    mbrv: Modbus register-map revision number for this physical FNDH
    pcbrv: PCB revision number for this physical FNDH
    register_map: A dictionary mapping register name to (register_number, number_of_registers, description, scaling_function) tuple
    cpuid: CPU identifier (integer)
    chipid: Unique ID number (16 bytes), different for every physical FNDH
    firmware_version: Firmware revision mumber for this physical FNDH
    uptime: Time in seconds since this FNDH was powered up
    station_value: Modbus address read back from the SYS_ADDRESS register - should always equal modbus_address
    psu48v1_voltage: Voltage measured on the output of the first 48VDC power supply (Volts)
    psu48v2_voltage: Voltage measured on the output of the second 48VDC power supply (Volts)
    psu5v_voltage: Voltage measured on the output of the 5VDC power supply (Volts)
    psu48v_current: Total current on the 48VDC bus (Amps)
    psu48v_temp: Common temperature for both 48VDC power supplies (deg C)
    psu5v_temp: Temperature of the 5VDC power supply (Volts)
    pcb_temp: Temperature on the internal PCB (deg C)
    outside_temp: Outside temperature (deg C)
    statuscode: Status value, one of the STATUS_* globals, and used as a key for STATUS_CODES (eg 0 meaning 'OK')
    status: Status string, obtained from STATUS_CODES global (eg 'OK')
    service_led: True if the blue service indicator LED is switched ON.
    indicator_code: LED status value, one of the LED_* globals, and used as a key for LED_CODES
    indicator_state: LED status string, obtained from LED_CODES
    readtime: Unix timestamp for the last successful polled data from this FNDH
    thresholds: JSON structure containing the analog threshold values for each analogue sensor on this FNDH
    portconfig: JSON structure containing the port configuration (desired online and offline power state) for each port

    ports: A dictionary with port number (1-28) as the key, and instances of PdocStatus() as values.
    """

    def __init__(self, conn=None, modbus_address=None, logger=None):
        """
        Instantiate an instance of FNDH() using a connection object, and the modbus address for the FNDH
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
        self.chipid = []  # Unique ID number (16 bytes), different for every physical FNDH
        self.firmware_version = 0  # Firmware revision mumber for this physical FNDH
        self.uptime = 0  # Time in seconds since this FNDH was powered up
        self.station_value = 0  # Modbus address read back from the SYS_ADDRESS register - should always equal modbus_address
        self.psu48v1_voltage = 0.0  # Voltage measured on the output of the first 48VDC power supply (Volts)
        self.psu48v2_voltage = 0.0  # Voltage measured on the output of the second 48VDC power supply (Volts)
        self.psu5v_voltage = 0.0  # Voltage measured on the output of the 5VDC power supply (Volts)
        self.psu48v_current = 0.0  # Total current on the 48VDC bus (Amps)
        self.psu48v_temp = 0.0  # Common temperature for both 48VDC power supplies (deg C)
        self.psu5v_temp = 0.0  # Temperature of the 5VDC power supply (Volts)
        self.pcb_temp = 0.0  # Temperature on the internal PCB (deg C)
        self.outside_temp = 0.0  # Outside temperature (deg C)
        self.statuscode = STATUS_UNINITIALISED  # Status value, one of the STATUS_* globals, and used as a key for STATUS_CODES (eg 0 meaning 'OK')
        self.status = 'UNINITIALISED'  # Status string, obtained from STATUS_CODES global (eg 'OK')
        self.service_led = False  # True if the blue service indicator LED is switched ON.
        self.indicator_code = -1  # LED status value, one of the LED_* globals, and used as a key for LED_CODES
        self.indicator_state = 'UNKNOWN'  # LED status string, obtained from LED_CODES
        self.readtime = 0    # Unix timestamp for the last successful polled data from this FNDH

        self.thresholds = None   # Set in the .configure_all_off() method - a dict with threshold values for each sensor register
        self.portconfig = None   # Set in the .configure_all_off() method - a dict with [desire_enabled_online, desire_enabled_offline] for each port

        self.ports = {}  # A dictionary with port number (1-28) as the key, and instances of PdocStatus() as values.
        for pnum in range(1, 29):
            self.ports[pnum] = PdocStatus(port_number=pnum,
                                          modbus_address=modbus_address,
                                          status_bitmap=0,
                                          read_timestamp=None)

    def __str__(self):
        tmpdict = self.__dict__.copy()
        tmpdict['status_age'] = time.time() - self.readtime
        return ((STATUS_STRING % tmpdict) +
                "\nPorts:\n" + ("\n".join([str(self.ports[pnum]) for pnum in range(1, 29)])))

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
            tmp_regmap = FNDH_POLL_REGS_1
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
        self.register_map = FNDH_REGISTERS[self.mbrv]

        for regname in self.register_map['POLL'].keys():  # Iterate over all the register names in the current register map
            regnum, numreg, regdesc, scalefunc = self.register_map['POLL'][regname]
            raw_value = valuelist[regnum - 1:regnum + numreg - 1]
            # print('%s: %s' % (regname, raw_value))
            raw_int = None
            scaled_float = None
            if numreg <= 2:
                raw_int = transport.bytestoN(raw_value)
            if scalefunc:
                scaled_float = scalefunc(raw_int, pcb_version=self.pcbrv)
            # print("    int=%s, float=%s"  % (raw_int, scaled_float))
            # Go through all the registers and update the instance data.
            if regname == 'SYS_CPUID':
                self.cpuid = hex(raw_int)
            elif regname == 'SYS_CHIPID':
                bytelist = []
                for byte_tuple in bytelist:
                    bytelist += list(byte_tuple)
                self.chipid = list(bytes(bytelist).decode('utf8'))
            elif regname == 'SYS_FIRMVER':
                self.firmware_version = raw_int
            elif regname == 'SYS_UPTIME':
                self.uptime = raw_int
            elif regname == 'SYS_ADDRESS':
                self.station_value = raw_int
            elif regname == 'SYS_48V1_V':
                self.psu48v1_voltage = scaled_float
            elif regname == 'SYS_48V2_V':
                self.psu48v2_voltage = scaled_float
            elif regname == 'SYS_5V_V':
                self.psu5v_voltage = scaled_float
            elif regname == 'SYS_48V_I':
                self.psu48v_current = scaled_float
            elif regname == 'SYS_48V_TEMP':
                self.psu48v_temp = scaled_float
            elif regname == 'SYS_5V_TEMP':
                self.psu5v_temp = scaled_float
            elif regname == 'SYS_PCBTEMP':
                self.pcb_temp = scaled_float
            elif regname == 'SYS_OUTTEMP':
                self.outside_temp = scaled_float
            elif regname == 'SYS_STATUS':
                self.statuscode = raw_int
                self.status = STATUS_CODES[self.statuscode]
            elif regname == 'SYS_LIGHTS':
                self.service_led = bool(raw_value[0][0])
                self.indicator_code = raw_value[0][1]
                self.indicator_state = LED_CODES[self.indicator_code]
            elif (len(regname) >= 8) and ((regname[0] + regname[-6:]) == 'P_STATE'):
                pnum = int(regname[1:-6])
                self.ports[pnum].set_status_data(status_bitmap=raw_int, read_timestamp=read_timestamp)

        self.readtime = read_timestamp
        return True

    def write_thresholds(self):
        """
        Write the ADC threshold data (loaded on init from a JSON file into self.thresholds) to the FNDH.

        :return: True if successful, False on failure, None if self.thresholds is empty
        """
        if self.thresholds is None:
            return None

        if not self.register_map:
            self.logger.error('No register map, call poll_data() first')
            return None

        # Count how many system threshold registers there are, and create an empty list of register values
        conf_reglist = self.register_map['CONF'].keys()
        vlist = [0] * sum(x[1] for x in self.register_map['CONF'].values())

        startreg = min([data[0] for data in self.register_map['CONF'].values()])
        for regname in conf_reglist:
            regnum, numreg, regdesc, scalefunc = self.register_map['CONF'][regname]
            # Convert the list of threshold values in physical units into the 16 bit integers to be passed in registers
            values = [scalefunc(v, pcb_version=self.pcbrv, reverse=True) for v in self.thresholds[regname]]
            assert len(values) == numreg
            vlist[(regnum - startreg):(regnum - startreg) + numreg] = values

        try:
            res = self.conn.writeMultReg(modbus_address=self.modbus_address, regnum=startreg, valuelist=vlist)
        except:
            self.logger.exception('Exception in transport.writeMultReg() in write_thresholds:')
            return False

        if res:
            return True
        else:
            return False

    def write_portconfig(self, write_state=True, write_to=False, write_breaker=False):
        """
        Write the current instance data for all of the ports to the FNDH.

        If 'write_state' is True, then the 'desired_state_online' and 'desired_state_offline' will have bitfields
        corresponding to the current instance data, otherwise they will contain '00' (meaning 'do not overwrite').

        If 'write_to' is True, then the 'technicians override' bits will have bitfields corresponding to the
        current instance data (locally_forced_on and locally_forced_off), otherwise they will contain '00'

        If 'write_breaker' is True, then the bit corresponding to the 'reset breaker' action will be 1, otherwise
        it will contain 0 (do not reset the breaker).

        :return: True if successful, False on failure
        """
        if not self.register_map:
            self.logger.error('No register map, call poll_data() first')
            return None

        vlist = [0] * 28
        startreg = self.register_map['POLL']['P01_STATE'][0]
        for portnum in range(1, 29):
            vlist[(portnum - 1)] = self.ports[portnum].status_to_integer(write_state=write_state,
                                                                         write_to=write_to,
                                                                         write_breaker=write_breaker)

        try:
            res = self.conn.writeMultReg(modbus_address=self.modbus_address, regnum=startreg, valuelist=vlist)
        except:
            self.logger.exception('Exception in transport.writeMultReg() in write_portconfig:')
            return False

        if res:
            return True
        else:
            return False

    def configure_all_off(self, thresholds=None, portconfig=None):
        """
         Get the threshold data (as given, or from the config file), and write it to the FNDH.

         If that succeeds, read the port configuration (desired state online, desired state offline) from the config
         file (if it's not supplied) and save it in self.portconfig, but do NOT write it to the FNDH. Instead,
         configure all outputs as 'off' in both online and offline states.

         Then write a '1' to the status register to tell the micontroller to
         transition out of the 'UNINITIALISED' state.

         :param thresholds: A dictionary containing the ADC thresholds to write to the FNDH. If none, use defaults
                            from the JSON file specified in THRESHOLD_FILENAME
         :param portconfig: A dictionary containing the port configuration data. If none, use
                            defaults from the JSON file specified in PORTCONFIG_FILENAME
         :return: True for sucess
         """
        if thresholds:
            self.thresholds = thresholds
        else:
            if not self.thresholds:
                try:
                    # JSON structure containing the analog threshold values for each port on this SMARTbox
                    self.thresholds = json.load(open(THRESHOLD_FILENAME, 'r'))
                except Exception:
                    self.thresholds = None

        if portconfig:
            self.portconfig = portconfig
        else:
            if not self.portconfig:
                try:
                    # JSON structure containing the port configuration (desired online and offline power state) for each port
                    self.portconfig = {int(x):y for x,y in json.load(open(PORTCONFIG_FILENAME, 'r')).items()}
                except Exception:
                    self.portconfig = None

        if not self.register_map:
            self.logger.error('No register map, call poll_data() first')
            return None

        ok = self.write_thresholds()
        if not ok:
            self.logger.error('Could not load and write threshold data.')
            return False

        # Make sure all the ports are off, both online and offline, and clear technician override bits
        for portnum in range(1, 29):
            self.ports[portnum].desire_enabled_online = False
            self.ports[portnum].desire_enabled_offline = False
            self.ports[portnum].locally_forced_off = False
            self.ports[portnum].locally_forced_on = False
        ok = self.write_portconfig()
        if not ok:
            self.logger.error('Could not write port configuration to the FNDH.')
            return False

        # Write state register so the FNDH will transition to 'online'
        try:
            self.conn.writeReg(modbus_address=self.modbus_address, regnum=self.register_map['POLL']['SYS_STATUS'][0], value=1)
        except:
            self.logger.exception('Exception in transport.writeReg() in configure_all_off:')
            return False

        return True

    def configure_final(self):
        """
        Use the self.portconfig data to set all the desired_state_online and desired_state_offline
        flags, and write the full set of port data to the FNDH, to turn on all desired ports.

        This is called after the power-on procedure, which turns on all of the ports, one by one, to determine
        which SMARTbox is connected to which PDoC port.
        """
        if not self.register_map:
            self.logger.error('No register map, call poll_data() first')
            return None

        # Startup finished, now set all the port states as per the saved port configuration:
        for portnum in range(1, 29):
            self.ports[portnum].desire_enabled_online = bool(self.portconfig[portnum][0])
            self.ports[portnum].desire_enabled_offline = bool(self.portconfig[portnum][1])
        ok = self.write_portconfig()
        return ok


"""
Use as 'communicate.py fndh', or:

from pasd import transport
from pasd import fndh
conn = transport.Connection(hostname='134.7.50.185')  # address of ethernet-serial bridge
# or
conn = transport.Connection(devicename='/dev/ttyS0')  # or 'COM5' for example, under Windows

f = fndh.FNDH(conn=conn, modbus_address=31)
f.poll_data()
f.configure_all_off()
f.configure_final()
"""
