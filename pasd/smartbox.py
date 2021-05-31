#!/usr/bin/env python

"""Classes to handle communications with an SKA-Low PaSD 'SMARTbox', 24 of which make
   up an SKA-Low station.

   This code runs on the MCCS side in the control building, and talks to a physical SMARTbox module in the field.
"""

import json
import logging
import time

logging.basicConfig()

from pasd import conversion
from pasd import transport


# Dicts with register name as key, and a tuple of (register_number, number_of_registers, description, scaling_function) as value
SMARTBOX_POLL_REGS_1 = {  # These initial registers will be assumed to be fixed, between register map revisions
                        'SYS_MBRV':    (1, 1, 'Modbus register map revision', None),
                        'SYS_PCBREV':  (2, 1, 'PCB Revision number', None),
                        'SYS_CPUID':   (3, 2, 'Microcontroller device ID', None),
                        'SYS_CHIPID':  (5, 8, 'Chip unique device ID', None),
                        'SYS_FIRMVER': (13, 1, 'Firmware version', None),
                        'SYS_UPTIME':  (14, 2, 'Uptime in seconds', None),
                        'SYS_ADDRESS': (16, 1, 'MODBUS station ID', None),

                        # From here on can change between firmware revisions
                        'SYS_48V_V':     (17, 1, 'Incoming 48VDC voltage', conversion.scale_48v),
                        'SYS_PSU_V':     (18, 1, 'PSU output voltage', conversion.scale_5v),
                        'SYS_PSUTEMP': (19, 1, 'PSU Temperature', conversion.scale_temp),
                        'SYS_PCBTEMP': (20, 1, 'PCB Temperature', conversion.scale_temp),
                        'SYS_OUTTEMP': (21, 1, 'Outside Temperature', conversion.scale_temp),
                        'SYS_STATUS':  (22, 1, 'System status code', None),
                        'SYS_LIGHTS':  (23, 1, 'LED state codes', None),

                        # Note - only a few of these FEM enclosure temps will return valid data
                        'SYS_FEM01TEMP': (24, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_FEM02TEMP': (25, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_FEM03TEMP': (26, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_FEM04TEMP': (27, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_FEM05TEMP': (28, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_FEM06TEMP': (29, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_FEM07TEMP': (30, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_FEM08TEMP': (31, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_FEM09TEMP': (32, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_FEM10TEMP': (33, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_FEM11TEMP': (34, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_FEM12TEMP': (35, 1, 'FEM Temperature', conversion.scale_temp),

                        # Per-port status variables
                        'P01_STATE': (36, 1, 'Port 01 state bitmap', None),
                        'P01_CURRENT': (37, 1, 'Port 01 current', conversion.scale_current),
                        'P02_STATE': (38, 1, 'Port 02 state bitmap', None),
                        'P02_CURRENT': (39, 1, 'Port 02 current', conversion.scale_current),
                        'P03_STATE': (40, 1, 'Port 03 state bitmap', None),
                        'P03_CURRENT': (41, 1, 'Port 03 current', conversion.scale_current),
                        'P04_STATE': (42, 1, 'Port 04 state bitmap', None),
                        'P04_CURRENT': (43, 1, 'Port 04 current', conversion.scale_current),
                        'P05_STATE': (44, 1, 'Port 05 state bitmap', None),
                        'P05_CURRENT': (45, 1, 'Port 05 current', conversion.scale_current),
                        'P06_STATE': (46, 1, 'Port 06 state bitmap', None),
                        'P06_CURRENT': (47, 1, 'Port 06 current', conversion.scale_current),
                        'P07_STATE': (48, 1, 'Port 07 state bitmap', None),
                        'P07_CURRENT': (49, 1, 'Port 07 current', conversion.scale_current),
                        'P08_STATE': (50, 1, 'Port 08 state bitmap', None),
                        'P08_CURRENT': (51, 1, 'Port 08 current', conversion.scale_current),
                        'P09_STATE': (52, 1, 'Port 09 state bitmap', None),
                        'P09_CURRENT': (53, 1, 'Port 09 current', conversion.scale_current),
                        'P10_STATE': (54, 1, 'Port 10 state bitmap', None),
                        'P10_CURRENT': (55, 1, 'Port 10 current', conversion.scale_current),
                        'P11_STATE': (56, 1, 'Port 11 state bitmap', None),
                        'P11_CURRENT': (57, 1, 'Port 11 current', conversion.scale_current),
                        'P12_STATE': (58, 1, 'Port 12 state bitmap', None),
                        'P12_CURRENT': (59, 1, 'Port 12 current', conversion.scale_current),
}

# System threshold configuration registers (not polled)
SMARTBOX_CONF_REGS_1 = {
                        'SYS_48V_V_TH': (1001, 4, 'Incoming 48VDC voltage AH, WH, WL, AL', conversion.scale_48v),
                        'SYS_PSU_V_TH': (1005, 4, 'PSU output voltage AH, WH, WL, AL', conversion.scale_5v),
                        'SYS_PSUTEMP_TH': (1009, 4, 'PSU temperature AH, WH, WL, AL', conversion.scale_temp),
                        'SYS_PCBTEMP_TH': (1013, 4, 'PCB temperature AH, WH, WL, AL', conversion.scale_temp),
                        'SYS_OUTTEMP_TH': (1017, 4, 'Outside temperature AH, WH, WL, AL', conversion.scale_temp),
                        'SYS_FEM01TEMP_TH': (1021, 4, 'FEM 1 temperature AH, WH, WL, AL', conversion.scale_temp),
                        'SYS_FEM02TEMP_TH': (1025, 4, 'FEM 2 temperature AH, WH, WL, AL', conversion.scale_temp),
                        'SYS_FEM03TEMP_TH': (1029, 4, 'FEM 3 temperature AH, WH, WL, AL', conversion.scale_temp),
                        'SYS_FEM04TEMP_TH': (1033, 4, 'FEM 4 temperature AH, WH, WL, AL', conversion.scale_temp),
                        'SYS_FEM05TEMP_TH': (1037, 4, 'FEM 5 temperature AH, WH, WL, AL', conversion.scale_temp),
                        'SYS_FEM06TEMP_TH': (1041, 4, 'FEM 6 temperature AH, WH, WL, AL', conversion.scale_temp),
                        'SYS_FEM07TEMP_TH': (1045, 4, 'FEM 7 temperature AH, WH, WL, AL', conversion.scale_temp),
                        'SYS_FEM08TEMP_TH': (1049, 4, 'FEM 8 temperature AH, WH, WL, AL', conversion.scale_temp),
                        'SYS_FEM09TEMP_TH': (1053, 4, 'FEM 9 temperature AH, WH, WL, AL', conversion.scale_temp),
                        'SYS_FEM10TEMP_TH': (1057, 4, 'FEM 10 temperature AH, WH, WL, AL', conversion.scale_temp),
                        'SYS_FEM11TEMP_TH': (1061, 4, 'FEM 11 temperature AH, WH, WL, AL', conversion.scale_temp),
                        'SYS_FEM12TEMP_TH': (1065, 4, 'FEM 12 temperature AH, WH, WL, AL', conversion.scale_temp),

                        # No hysteris or low-current limits for FEM currents, just a single value in ADC
                        'P01_CURRENT_TH':(1069, 1, 'Port 01 current trip threshold', None),
                        'P02_CURRENT_TH':(1070, 1, 'Port 02 current trip threshold', None),
                        'P03_CURRENT_TH':(1071, 1, 'Port 03 current trip threshold', None),
                        'P04_CURRENT_TH':(1072, 1, 'Port 04 current trip threshold', None),
                        'P05_CURRENT_TH':(1073, 1, 'Port 05 current trip threshold', None),
                        'P06_CURRENT_TH':(1074, 1, 'Port 06 current trip threshold', None),
                        'P07_CURRENT_TH':(1075, 1, 'Port 07 current trip threshold', None),
                        'P08_CURRENT_TH':(1076, 1, 'Port 08 current trip threshold', None),
                        'P09_CURRENT_TH':(1077, 1, 'Port 09 current trip threshold', None),
                        'P10_CURRENT_TH':(1078, 1, 'Port 10 current trip threshold', None),
                        'P11_CURRENT_TH':(1079, 1, 'Port 11 current trip threshold', None),
                        'P12_CURRENT_TH':(1080, 1, 'Port 12 current trip threshold', None),
}

SMARTBOX_CODES_1 = {'status':{'fromid':{0:'OK', 1:'WARNING', 2:'ALARM', 3:'RECOVERY', 4:'UNINITIALISED'},
                              'fromname':{'OK':0, 'WARNING':1, 'ALARM':2, 'RECOVERY':3, 'UNINITIALISED':4}},
                    'led':{'fromid':{0:'OFF', 1:'GREEN', 2:'RED', 3:'YELLOW'},
                           'fromname':{'OFF':0, 'GREEN':1, 'RED':2, 'YELLOW':3}}}


# Dicts with register version number as key, and a dict of registers (defined above) as value
SMARTBOX_REGISTERS = {1: {'POLL':SMARTBOX_POLL_REGS_1, 'CONF':SMARTBOX_CONF_REGS_1}}
SMARTBOX_CODES = {1: SMARTBOX_CODES_1}

THRESHOLD_FILENAME = 'pasd/smartbox_thresholds.json'
PORTCONFIG_FILENAME = 'pasd/smartbox_ports.json'

STATUS_STRING = """\
SMARTBox at address: %(modbus_address)s:
    ModBUS register revision: %(mbrv)s
    PCB revision: %(pcbrv)s
    CPU ID: %(cpuid)s
    CHIP ID: %(chipid)s
    Firmware revision: %(firmware_version)s
    Uptime: %(uptime)s seconds
    R.Address: %(station_value)s
    48V In: %(incoming_voltage)s V
    5V out: %(psu_voltage)s V
    PSU Temp: %(psu_temp)s deg C
    PCB Temp: %(pcb_temp)s deg C
    Outside Temp: %(outside_temp)s deg C
    Status: %(statuscode)s (%(status)s)
    Service LED: %(service_led)s
    Indicator: %(indicator_code)s (%(indicator_state)s)
"""


class PortStatus(object):
    """
        SMARTbox port status instance, representing one of the 12 FEM modules and antenna ports in a
        single SMARTbox.

        Attributes are:
        port_number: Which FEM port this is (1-12)
        modbus_address: Modbus address of the SMARTbox that this port is inside (1-30)
        status_bitmap: Raw contents of the P<NN>_STATE register for this port (0-65535)
        current_timestamp: Unix epoch at the time the port current was last read (integer)
        current_raw: Raw ADC value for the port current (0-65535)
        current: Port current in mA (float)
        status_timestamp: Unix epoch at the time the P<NN>_STATE register was last read (integer)
        system_level_enabled: Has the SMARTbox decided that it's in a safe state (not overheated, etc) (Boolean)
        system_online: Has the SMARTbox decided that it's heard from the MCCS recently enough to go online (Boolean)
        desire_enabled_online: Does the MCCS want this port enabled when the device is online (Boolean)
        desire_enabled_offline:Does the MCCS want this port enabled when the device is offline (Boolean)
        locally_forced_on: Has this port been locally forced ON by a technician overide (Boolean)
        locally_forced_off: Has this port been locally forced OFF by a technician overide (Boolean)
        breaker_tripped: Has the over-current breaker tripped on this port (Boolean)
        power_state: Is this port switched ON (Boolean)
        antenna_number: Physical station antenna number. Only set externally, at the station level. (1-256)

        Note that modbus_address, system_level_enabled and system_online have the the same values for all ports.
    """
    def __init__(self, port_number, modbus_address, status_bitmap, current_raw, current, read_timestamp, logger=None):
        """
        Instantiate a SMARTbox port status instance, given a 16 bit integer bitwise state (from a PNN_STATE register),
        a raw (ADC) current value, a scaled (float) current reading, and a timestamp at which that data was read.

        This initialisation function doesn't communicate with the FNDH hardware, it just sets up the
        data structures.

        Parameters:
        :param port_number: integer, 1-12 - physical FEM port number inside the SMARTbox
        :param modbus_address: integer - the modbus station address of the SMARTbox that this port is in.
        :param status_bitmap: integer, 0-65535
        :param current_raw: integer, 0-65535 - raw ADC value for the port current
        :param current: float - port current in mA
        :param read_timestamp - float - unix timetamp when the data was pulled from the SMARTbox
        :return: None
        """
        self.port_number = port_number        # Which FEM port this is (1-12)
        self.modbus_address = modbus_address  # Modbus address of the SMARTbox that this port is inside
        self.status_bitmap = status_bitmap    # Raw contents of the P<NN>_STATE register for this port
        self.current_timestamp = read_timestamp  # Unix epoch at the time the port current was last read
        self.current_raw = current_raw           # Raw ADC value for the port current
        self.current = current                   # Port current in mA
        self.status_timestamp = read_timestamp   # Unix epoch at the time the P<NN>_STATE register was last read
        self.system_level_enabled = False   # Has the SMARTbox decided that it's in a safe state (not overheated, etc)
        self.system_online = False   # Has the SMARTbox decided that it's heard from the MCCS recently enough to go online
        self.desire_enabled_online = False   # Does the MCCS want this port enabled when the device is online
        self.desire_enabled_offline = False   # Does the MCCS want this port enabled when the device is offline
        self.locally_forced_on = False     # Has this port been locally forced ON by a technician overide
        self.locally_forced_off = False    # Has this port been locally forced OFF by a technician overide
        self.breaker_tripped = False    # Has the over-current breaker tripped on this port
        self.power_state = False    # Is this port switched ON
        self.antenna_number = None   # Physical station antenna number (1-256). Only set externally, at the station level.

        if logger is None:
            self.logger = logging.getLogger('P%02d' % self.port_number)
        else:
            self.logger = logger

        self.set_current(current_raw, current, read_timestamp=read_timestamp)
        self.set_status_data(status_bitmap, read_timestamp=read_timestamp)

    def __str__(self):
        if self.current_timestamp is None:
            current_string = "Current:Unknown"
        else:
            current_string = "Current:%4.1f(%1.1f s)" % (self.current, time.time() - self.current_timestamp)

        if self.status_timestamp is None:
            status_string = "Unknown"
        else:
            if self.locally_forced_on:
                lfstring = 'Forced:ON'
            elif self.locally_forced_off:
                lfstring = 'Forced:OFF'
            else:
                lfstring = 'NotForced'
            status_items = ['Status(%1.1f s):' % (time.time() - self.current_timestamp),
                            {False:'Disabled', True:'Enabled', None:'??abled?'}[self.system_level_enabled],
                            {False:'Offline', True:'Online', None:'??line?'}[self.system_online],
                            'DesEnableOnline=%s' % self.desire_enabled_online,
                            'DesEnableOffline=%s' % self.desire_enabled_offline,
                            lfstring,
                            {False:'Power:OFF', True:'Power:ON', None:'Power:?'}[self.power_state],
                            {False:'', True:'BreakerTrip!', None:'Breaker:?'}[self.breaker_tripped]
                            ]
            status_string = ' '.join(status_items)

        return "P%02d on SB:%d: %s %s" % (self.port_number, self.modbus_address, current_string, status_string)

    def __repr__(self):
        return str(self)

    def set_current(self, current_raw, current, read_timestamp):
        """
        Given a current reading (raw and scaled) and a read timestamp, update the instance with the new current data.

        :param current_raw: integer - raw ADC value
        :param current: flaot - current in mA
        :param read_timestamp: float - unix timetamp when the data was pulled from the SMARTbox
        :return: None
        """
        self.current_timestamp = read_timestamp
        self.current_raw = current_raw
        self.current = current

    def set_status_data(self, status_bitmap, read_timestamp):
        """
        Given a status bitmap (from one of the P<NN>_STATE registers), update the instance with the new data.

        :param status_bitmap:  integer, 0-65535 - state bitmap from P<NN>_STATE register
        :param read_timestamp:  float - unix timetamp when the data was pulled from the SMARTbox
        :return: None
        """
        self.status_timestamp = read_timestamp
        bitstring = "{:016b}".format(status_bitmap)
        self.system_level_enabled = (bitstring[0] == '1')   # read only
        self.system_online = (bitstring[1] == '1')   # read only

        # Desired state online - R/W, write 00 if no change to current value
        if (bitstring[2:4] == '10'):
            self.desire_enabled_online = False
        elif (bitstring[2:4] == '11'):
            self.desire_enabled_online = True
        elif (bitstring[2:4] == '00'):
            self.desire_enabled_online = None
        else:
            self.logger.warning('Unknown desire enabled online flag: %s' % bitstring[2:4])
            self.desire_enabled_online = None

        # Desired state offline - R/W, write 00 if no change to current value
        if (bitstring[4:6] == '10'):
            self.desire_enabled_offline = False
        elif (bitstring[4:6] == '11'):
            self.desire_enabled_offline = True
        elif (bitstring[4:6] == '00'):
            self.desire_enabled_offline = None
        else:
            self.logger.warning('Unknown desired state offline flag: %s' % bitstring[4:6])
            self.desire_enabled_offline = None

        # Technician override - R/W, write 00 if no change to current value
        if (bitstring[6:8] == '10'):
            self.locally_forced_on = False
            self.locally_forced_off = True
        elif (bitstring[6:8] == '11'):
            self.locally_forced_on = True
            self.locally_forced_off = False
        elif (bitstring[6:8] == '01'):
            self.locally_forced_on = False
            self.locally_forced_off = False
        else:
            self.locally_forced_on = None
            self.locally_forced_off = None

        # Circuit breaker trip - R/W, write 1 to reset the breaker
        self.breaker_tripped = (bitstring[8] == '1')

        # Power state - read only
        self.power_state = (bitstring[9] == '1')

    def status_to_integer(self, write_state=False, write_to=False, write_breaker=False):
        """
        Return a 16 bit integer state bitmap corresponding to the instance data.

        If 'write_state' is True, then the 'desired_state_online' and 'desired_state_offline' will have bitfields
        corresponding to the current instance data, otherwise they will contain '00' (meaning 'do not overwrite').

        If 'write_to' is True, then the 'technicians override' bits will have bitfields corresponding to the
        current instance data (locally_forced_on and locally_forced_off), otherwise they will contain '00'

        If 'write_breaker' is True, then the bit corresponding to the 'reset breaker' action will be 1, otherwise
        it will contain 0 (do not reset the breaker).

        :param write_state: boolean - overwrite current desired_state_online and desired_state_offline fields
        :param write_to: boolean - overwrite 'technicians local override' field
        :param write_breaker - send a 1 in the 'reset breaker' field, otherwise send 0. Local instance data is
                               ignored for this field.
        """
        b = {True:'1', False:'0'}
        bitstring = b[self.system_level_enabled] + b[self.system_online]

        if (self.desire_enabled_online is None) or (not write_state):
            bitstring += '00'
        else:
            bitstring += '1' + b[self.desire_enabled_online]

        if (self.desire_enabled_offline is None) or (not write_state):
            bitstring += '00'
        else:
            bitstring += '1' + b[self.desire_enabled_offline]

        if (self.locally_forced_on is None) or (self.locally_forced_off is None) or (not write_to):
            bitstring += '00'
        elif self.locally_forced_off:
            bitstring += '10'
        elif self.locally_forced_on:
            bitstring += '11'
        else:
            bitstring += '01'

        if write_breaker:   # If we're told to write the 'breaker reset' bit, ignore the local value
            bitstring += '1'
        else:
            bitstring += '0'

        bitstring += b[self.power_state]
        bitstring += '000000'  # pad to 16 bits
        return int(bitstring, 2)


class SMARTbox(transport.ModbusDevice):
    """
    SMARTbox class, instances of which represent each of the ~24 SMARTboxes inside an SKA-Low station, connected to an
    FNDH via a shared low-speed serial bus.

    Attributes are:
    modbus_address: Modbus address of this SMARTbox (1-30)
    mbrv: Modbus register-map revision number for this physical SMARTbox
    pcbrv: PCB revision number for this physical SMARTbox
    register_map: A dictionary mapping register name to (register_number, number_of_registers, description, scaling_function) tuple
    codes: A dictionary mapping status code integer (eg 0) to status code string (eg 'OK'), and LED codes to LED flash states
    fem_temps: A dictionary with port number (1-12) as key, and temperature as value
    cpuid: CPU identifier (integer)
    chipid: Unique ID number (16 bytes), different for every physical SMARTbox
    firmware_version: Firmware revision mumber for this physical SMARTbox
    uptime: Time in seconds since this SMARTbox was powered up
    station_value: Modbus address read back from the SYS_ADDRESS register - should always equal modbus_address
    incoming_voltage: Measured voltage for the (nominal) 48VDC input power (Volts)
    psu_voltage: Measured output voltage for the internal (nominal) 5V power supply
    psu_temp: Temperature of the internal 5V power supply (deg C)
    pcb_temp: Temperature on the internal PCB (deg C)
    outside_temp: Outside temperature (deg C)
    statuscode: Status value, used as a key for self.codes['status'] (eg 0 meaning 'OK')
    status: Status string, obtained from self.codes['status'] (eg 'OK')
    service_led: True if the blue service indicator LED is switched ON.
    indicator_code: LED status value, used as a key for self.codes['led']
    indicator_state: LED status, obtained from self.codes['led']
    readtime: Unix timestamp for the last successful polled data from this SMARTbox
    pdoc_number: Physical PDoC port on the FNDH that this SMARTbox is plugged into. Populated by the station initialisation code on powerup
    thresholds: JSON structure containing the analog threshold values for each port on this SMARTbox
    portconfig: JSON structure containing the port configuration (desired online and offline power state) for each port

    ports: A dictionary with port number (1-12) as the key, and instances of PortStatus() as values.
    """

    def __init__(self, conn=None, modbus_address=None, logger=None):
        """
        Instantiate an instance of SMARTbox() using a connection object, and the modbus address for that physical
        SMARTbox.

        This initialisation function doesn't communicate with the SMARTbox hardware, it just sets up the
        data structures.

        :param conn: An instance of transport.Connection() defining a connection to an FNDH
        :param modbus_address: The modbus station address (1-30) for this physical SMARTbox
        """
        transport.ModbusDevice.__init__(self, conn=conn, modbus_address=modbus_address, logger=logger)

        self.mbrv = None   # Modbus register-map revision number for this physical SMARTbox
        self.pcbrv = None  # PCB revision number for this physical SMARTbox
        self.register_map = {}  # A dictionary mapping register name to (register_number, number_of_registers, description, scaling_function) tuple
        self.codes = {}    # A dictionary mapping status code integer (eg 0) to status code string (eg 'OK'), and LED codes to LED flash states
        self.fem_temps = {}  # Dictionary with FEM number (1-12) as key, and temperature as value
        self.cpuid = ''    # CPU identifier (integer)
        self.chipid = []   # Unique ID number (16 bytes), different for every physical SMARTbox
        self.firmware_version = 0  # Firmware revision mumber for this physical SMARTbox
        self.uptime = 0            # Time in seconds since this SMARTbox was powered up
        self.station_value = 0     # Modbus address read back from the SYS_ADDRESS register - should always equal modbus_address
        self.incoming_voltage = 0.0  # Measured voltage for the (nominal) 48VDC input power (Volts)
        self.psu_voltage = 0.0     # Measured output voltage for the internal (nominal) 5V power supply
        self.psu_temp = 0.0    # Temperature of the internal 5V power supply (deg C)
        self.pcb_temp = 0.0    # Temperature on the internal PCB (deg C)
        self.outside_temp = 0.0    # Outside temperature (deg C)
        self.statuscode = 0    # Status value, used as a key for self.codes['status'] (eg 0 meaning 'OK')
        self.status = ''       # Status string, obtained from self.codes['status'] (eg 'OK')
        self.service_led = None    # True if the blue service indicator LED is switched ON.
        self.indicator_code = None  # LED status value, used as a key for self.codes['led']
        self.indicator_state = ''   # LED status, obtained from self.codes['led']
        self.readtime = 0    # Unix timestamp for the last successful polled data from this SMARTbox
        self.pdoc_number = None   # Physical PDoC port on the FNDH that this SMARTbox is plugged into. Populated by the station initialisation code on powerup
        try:
            # JSON structure containing the analog threshold values for each port on this SMARTbox
            self.thresholds = json.load(open(THRESHOLD_FILENAME, 'r'))
        except Exception:
            self.thresholds = None
        try:
            # JSON structure containing the port configuration (desired online and offline power state) for each port
            allports = json.load(open(PORTCONFIG_FILENAME, 'r'))
            self.portconfig = allports[str(self.modbus_address)]
        except Exception:
            self.portconfig = None

        self.ports = {}  # A dictionary with port number (1-12) as the key, and instances of PortStatus() as values.
        for pnum in range(1, 13):
            self.ports[pnum] = PortStatus(port_number=pnum,
                                          modbus_address=modbus_address,
                                          status_bitmap=0,
                                          current_raw=0,
                                          current=0,
                                          read_timestamp=None,
                                          logger=logging.getLogger(self.logger.name + '.P%02d' % pnum))

    def __str__(self):
        return STATUS_STRING % (self.__dict__) + "\nPorts:\n" + ("\n".join([str(self.ports[pnum]) for pnum in range(1, 13)]))

    def poll_data(self):
        """
        Get all the polled registers from the device, and use the contents to fill in the instance data for this instance.

        :return: True for success, None if there were any errors.
        """
        if self.register_map:  # We've talked to this box before, so we know the actual register map
            tmp_regmap = self.register_map['POLL']
        else:   # We haven't talked to this box, so use a default map to get the registers to read this time
            tmp_regmap = SMARTBOX_POLL_REGS_1
        maxregnum = max([data[0] for data in tmp_regmap.values()])
        maxregname = [name for (name, data) in tmp_regmap.items() if data[0] == maxregnum][0]
        poll_blocksize = maxregnum + (tmp_regmap[maxregname][1] - 1)  # number of registers to read

        # Get a list of tuples, where each tuple is a two-byte register value, eg (0,255)
        try:
            valuelist = self.conn.readReg(modbus_address=self.modbus_address, regnum=1, numreg=poll_blocksize)
        except Exception:
            self.logger.exception('Exception in readReg in poll_data for SMARTbox %d' % self.modbus_address)
            return None

        read_timestamp = time.time()
        if valuelist is None:
            self.logger.error('Error in readReg in poll_data for SMARTbox %d, no data' % self.modbus_address)
            return None

        if len(valuelist) != poll_blocksize:
            self.logger.warning('Only %d registers returned from SMARTbox %d by readReg in poll_data, expected %d' % (len(valuelist),
                                                                                                                      self.modbus_address,
                                                                                                                      poll_blocksize))
            return None

        self.mbrv = valuelist[0][0] * 256 + valuelist[0][1]
        self.pcbrv = valuelist[1][0] * 256 + valuelist[1][1]
        self.register_map = SMARTBOX_REGISTERS[self.mbrv]
        self.codes = SMARTBOX_CODES[self.mbrv]

        self.fem_temps = {}  # Dictionary with FEM number (1-12) as key, and temperature as value
        for regname in self.register_map['POLL'].keys():  # Iterate over all the register names in the current register map
            regnum, numreg, regdesc, scalefunc = self.register_map['POLL'][regname]
            raw_value = valuelist[regnum - 1:regnum + numreg - 1]
            # print('%s: %s' % (regname, raw_value))
            raw_int = None
            scaled_float = None
            if numreg <= 2:
                raw_int = transport.bytestoN(raw_value)
            if scalefunc:
                scaled_float = scalefunc(raw_int, self.pcbrv)
            # print("    int=%s, float=%s"  % (raw_int, scaled_float))
            # Go through all the registers and update the instance data.
            if regname == 'SYS_CPUID':
                self.cpuid = hex(raw_int)
            elif regname == 'SYS_CHIPID':
                bytelist = []
                for byte_tuple in bytelist:
                    bytelist += list(byte_tuple)
                self.chipid = bytes(bytelist)
            elif regname == 'SYS_FIRMVER':
                self.firmware_version = raw_int
            elif regname == 'SYS_UPTIME':
                self.uptime = raw_int
            elif regname == 'SYS_ADDRESS':
                self.station_value = raw_int
            elif regname == 'SYS_48V_V':
                self.incoming_voltage = scaled_float
            elif regname == 'SYS_PSU_V':
                self.psu_voltage = scaled_float
            elif regname == 'SYS_PSUTEMP':
                self.psu_temp = scaled_float
            elif regname == 'SYS_PCBTEMP':
                self.pcb_temp = scaled_float
            elif regname == 'SYS_OUTTEMP':
                self.outside_temp = scaled_float
            elif regname == 'SYS_STATUS':
                self.statuscode = raw_int
                self.status = self.codes['status']['fromid'][self.statuscode]
            elif regname == 'SYS_LIGHTS':
                self.service_led = bool(raw_value[0][0])
                self.indicator_code = raw_value[0][1]
                self.indicator_state = self.codes['led']['fromid'][self.indicator_code]
            elif (len(regname) >= 12) and ((regname[:7] + regname[-4:]) == 'SYS_FEMTEMP'):
                fem_num = int(regname[7:-4])
                self.fem_temps[fem_num] = scaled_float
            elif (len(regname) >= 8) and ((regname[0] + regname[-6:]) == 'P_STATE'):
                pnum = int(regname[1:-6])
                self.ports[pnum].set_status_data(status_bitmap=raw_int, read_timestamp=read_timestamp)
            elif (len(regname) >= 10) and ((regname[0] + regname[-8:]) == 'P_CURRENT'):
                pnum = int(regname[1:-8])
                self.ports[pnum].set_current(current_raw=raw_int, current=scaled_float, read_timestamp=read_timestamp)

        self.readtime = read_timestamp
        return True

    def read_uptime(self):
        """
        Read enough registers to get the register revision number, and the system uptime.

        :return: uptime in seconds, or None if there was an error.
        """
        try:
            valuelist = self.conn.readReg(modbus_address=self.modbus_address, regnum=1, numreg=16)
        except Exception:
            self.logger.exception('Exception in readReg in poll_data for SMARTbox %d' % self.modbus_address)
            return None

        if valuelist is None:
            self.logger.error('Error in readReg in poll_data for SMARTbox %d, no data' % self.modbus_address)
            return None

        if len(valuelist) != 16:
            self.logger.warning('Only %d registers returned from SMARTbox %d by readReg in poll_data, expected %d' % (len(valuelist),
                                                                                                                      self.modbus_address,
                                                                                                                      16))
            return None

        self.mbrv = valuelist[0][0] * 256 + valuelist[0][1]
        self.pcbrv = valuelist[1][0] * 256 + valuelist[1][1]
        self.register_map = SMARTBOX_REGISTERS[self.mbrv]
        self.codes = SMARTBOX_CODES[self.mbrv]
        regnum, numreg, regdesc, scalefunc = self.register_map['POLL']['SYS_UPTIME']
        raw_value = valuelist[regnum - 1:regnum + numreg - 1]
        self.uptime = transport.bytestoN(raw_value)   # I know uptime is 2 registers, 4 bytes
        return self.uptime

    def write_thresholds(self):
        """
        Write the ADC threshold data (loaded on init from a JSON file into self.thresholds) to the SMARTbox.

        :return: True if successful, False on failure, None if self.thresholds is empty
        """
        if self.thresholds is None:
            self.logger.error('No thresholds, exiting')
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
            values = self.thresholds[regname]
            assert len(values) == numreg
            vlist[(regnum - startreg):(regnum - startreg) + numreg] = values

        try:
            res = self.conn.writeMultReg(modbus_address=self.modbus_address, regnum=startreg, valuelist=vlist)
        except:
            self.logger.exception('Exception in transport.writeMultReg():')
            return False

        if res:
            self.logger.info('Wrote thresholds.')
            return True
        else:
            self.logger.info('Could not write thresholds.')
            return False

    def write_portconfig(self):
        """
        Write the current instance data for 'desired port state online' and 'desired port state offline' in each of
        the port status objects, to the SMARTbox.

        :return: True if successful, False on failure
        """
        if not self.register_map:
            self.logger.error('No register map, call poll_data() first')
            return None

        vlist = [0] * 24
        startreg = self.register_map['POLL']['P01_STATE'][0]
        for portnum in range(1, 13):
            vlist[(portnum - 1) * 2] = self.ports[portnum].status_to_integer(write_state=True)
            vlist[(portnum - 1) * 2 + 1] = self.ports[portnum].current_raw

        try:
            res = self.conn.writeMultReg(modbus_address=self.modbus_address, regnum=startreg, valuelist=vlist)
        except:
            self.logger.exception('Exception in transport.writeMultReg():')
            return False

        if res:
            self.logger.info('Wrote portconfig.')
            return True
        else:
            self.logger.info('Could not write portconfig.')
            return False

    def configure(self, thresholds=None, portconfig=None):
        """
        Use the threshold data as given, or in self.thresholds read from the config file on initialisation, and write
        it to the SMARTbox.

        If that succeeds, use the port configuration (desired state online, desired state offline) as given, or in
        self.portconfig read from the config file on initialisation, and write it to the SMARTbox.

        Then, if that succeeds, write a '1' to the status register to tell the micontroller to
        transition out of the 'UNINITIALISED' state.

        :param thresholds: A dictionary containing the ADC thresholds to write to the SMARTbox. If none, use defaults
                           from the JSON file specified in THRESHOLD_FILENAME loaded on initialistion into self.thresholds
        :param portconfig: A dictionary containing the port configuration data to write to the SMARTbox. If none, use
                           defaults from the JSON file specified in PORTCONFIG_FILENAME loaded on initialistion into self.portconfig
        :return: True for sucess
        """
        if thresholds:
            self.thresholds = thresholds

        if portconfig:
            self.portconfig = portconfig

        if not self.register_map:
            self.logger.error('No register map, call poll_data() first')
            return None

        ok = self.write_thresholds()

        if ok:
            for portnum in range(1, 13):
                self.ports[portnum].desire_enabled_online = bool(self.portconfig[str(portnum)][0])
                self.ports[portnum].desire_enabled_offline = bool(self.portconfig[str(portnum)][1])
            ok = self.write_portconfig()
            if ok:
                try:
                    return self.conn.writeReg(modbus_address=self.modbus_address, regnum=self.register_map['POLL']['SYS_STATUS'][0], value=1)
                except:
                    self.logger.exception('Exception in transport.writeReg():')
                    return False
            else:
                self.logger.error('Could not load and write port state configuration.')
        else:
            self.logger.error('Could not load and write threshold data.')
        return False


"""
Use as 'communicate.py smartbox', or:

from pasd import transport
from pasd import smartbox
conn = transport.Connection(hostname='134.7.50.185')  # address of ethernet-serial bridge
# or
conn = transport.Connection(devicename='/dev/ttyS0')  # or 'COM5' for example, under Windows

s = smartbox.SMARTbox(conn=conn, modbus_address=1)
s.poll_data()
s.configure()
"""
