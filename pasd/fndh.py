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

from pasd import conversion
from pasd import smartbox
from pasd import transport


# Dicts with register name as key, and a tuple of (register_number, number_of_registers, name, scaling_function) as value
FNDH_POLL_REGS_1 = {  # These initial registers will be assumed to be fixed, between register map revisions
                        'SYS_MBRV':    (1, 1, 'Modbus register map revision', None),
                        'SYS_PCBREV':  (2, 1, 'PCB Revision number', None),
                        'SYS_CPUID':   (3, 2, 'Microcontroller device ID', None),
                        'SYS_CHIPID':  (5, 8, 'Chip unique device ID', None),
                        'SYS_FIRMVER': (13, 1, 'Firmware version', None),
                        'SYS_UPTIME':  (14, 2, 'Uptime in seconds', None),
                        'SYS_ADDRESS': (16, 1, 'MODBUS station ID', None),

                        # From here on can change between firmware revisions
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

FNDH_CONF_REGS_1 = {
                    'SYS_48V1_V':(1001, 4, '48V PSU 1, 48VDC voltage AH, WH, WL, AL', conversion.scale_48v),
                    'SYS_48V2_V':(1005, 4, '48V PSU 2, 48VDC voltage AH, WH, WL, AL', conversion.scale_48v),
                    'SYS_5V_V':(1009, 4, '5V PSU output voltage AH, WH, WL, AL', conversion.scale_5v),
                    'SYS_48V_I':(1013, 4, '48V PSU output current AH, WH, WL, AL', conversion.scale_48vcurrent),
                    'SYS_48V_TEMP':(1017, 4, '48V PSU temperature AH, WH, WL, AL', conversion.scale_temp),
                    'SYS_5V_TEMP':(1021, 4, '5V PSU temperature AH, WH, WL, AL', conversion.scale_temp),
                    'SYS_PCBTEMP_TH':(1025, 4, 'PCB temperature AH, WH, WL, AL', conversion.scale_temp),
                    'SYS_OUTTEMP_TH':(1029, 4, 'Outside temperature AH, WH, WL, AL', conversion.scale_temp),

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
    def __init__(self, port_number, modbus_address, status_bitmap, read_timestamp):
        """
        Instantiate an instance of a PdocStatus() object.

        This initialisation function doesn't communicate with the port hardware, it just sets up the
        data structures.

        :param port_number: Which PDoC port this is (1-28)
        :param modbus_address: Modbus address of the FNDH microcontroller (should always be 31)
        :param status_bitmap: Raw contents of the P<NN>_STATE register for this port (0-65535)
        :param read_timestamp: Unix epoch at the time the P<NN>_STATE register was last read (integer)
        """
        smartbox.PortStatus.__init__(self, port_number, modbus_address, status_bitmap, 0, 0.0, read_timestamp)

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
        self.power_sense = self.breaker_tripped
        self.breaker_tripped = None

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
            status_items = ['Status(%1.1f s) on FNDH %s:' % (time.time() - self.current_timestamp, self.modbus_address),
                            {False:'Disabled', True:'Enabled', None:'??abled?'}[self.system_level_enabled],
                            {False:'Offline', True:'Online', None:'??line?'}[self.system_online],
                            'DesEnableOnline=%s' % self.desire_enabled_online,
                            'DesEnableOffline=%s' % self.desire_enabled_offline,
                            lfstring,
                            {False:'Power:TurnedON', True:'Power:TurnedOFF', None:'Power:?'}[self.power_state],
                            {False:'PowerSense:ON', True:'PowerSense:OFF', None:'PowerSense:?'}[self.breaker_tripped]
                            ]
            status_string = ' '.join(status_items)

        return "P%02d: %s %s" % (self.port_number, current_string, status_string)


class FNDH(transport.ModbusSlave):
    """
    FNDH class, an instance of which represents the microcontroller inside the FNDH in an SKA-Low station, sitting
    (virtually) on the same shared low-speed serial bus used to communicate with the SMARTboxes.

    Attributes are:
    modbus_address: Modbus address of the FNDH (usually 31)
    mbrv: Modbus register-map revision number for this physical FNDH
    pcbrv: PCB revision number for this physical FNDH
    register_map: A dictionary mapping register name to (register_number, number_of_registers, description, scaling_function) tuple
    codes: A dictionary mapping status code integer (eg 0) to status code string (eg 'OK'), and LED codes to LED flash states
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
    statuscode: Status value, used as a key for self.codes['status'] (eg 0 meaning 'OK')
    status: Status string, obtained from self.codes['status'] (eg 'OK')
    service_led: True if the blue service indicator LED is switched ON.
    indicator_code: LED status value, used as a key for self.codes['led']
    indicator_state: LED status, obtained from self.codes['led']
    readtime: Unix timestamp for the last successful polled data from this FNDH
    thresholds: JSON structure containing the analog threshold values for each analogue sensor on this FNDH
    portconfig: JSON structure containing the port configuration (desired online and offline power state) for each port

    ports: A dictionary with port number (1-28) as the key, and instances of PdocStatus() as values.
    """

    def __init__(self, conn=None, modbus_address=None):
        """
        Instantiate an instance of FNDH() using a connection object, and the modbus address for the FNDH
        (usually 31).

        This initialisation function doesn't communicate with the FNDH hardware, it just sets up the
        data structures.

        :param conn: An instance of transport.Connection() defining a connection to an FNDH
        :param modbus_address: Modbus address of the FNDH (usually 31)
        """
        transport.ModbusSlave.__init__(self, conn=conn, modbus_address=modbus_address)

        self.mbrv = None   # Modbus register-map revision number for this physical FNDH
        self.pcbrv = None  # PCB revision number for this physical FNDH
        self.register_map = {}  # A dictionary mapping register name to (register_number, number_of_registers, description, scaling_function) tuple
        self.codes = {}  # A dictionary mapping status code integer (eg 0) to status code string (eg 'OK'), and LED codes to LED flash states
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
        self.statuscode = 0  # Status value, used as a key for self.codes['status'] (eg 0 meaning 'OK')
        self.status = ''  # Status string, obtained from self.codes['status'] (eg 'OK')
        self.service_led = None  # True if the blue service indicator LED is switched ON.
        self.indicator_code = None  # LED status value, used as a key for self.codes['led']
        self.indicator_state = ''  # LED status, obtained from self.codes['led']
        self.readtime = 0    # Unix timestamp for the last successful polled data from this FNDH
        try:
            # JSON structure containing the analog threshold values for each analogue sensor on this FNDH
            self.thresholds = json.load(open(THRESHOLD_FILENAME, 'r'))
        except Exception:
            self.thresholds = None
        try:
            # JSON structure containing the port configuration (desired online and offline power state) for each port
            allports = json.load(open(PORTCONFIG_FILENAME, 'r'))
            self.portconfig = allports[self.modbus_address]
        except Exception:
            self.portconfig = None

        self.ports = {}  # A dictionary with port number (1-28) as the key, and instances of PdocStatus() as values.
        for pnum in range(1, 29):
            self.ports[pnum] = PdocStatus(port_number=pnum,
                                          modbus_address=modbus_address,
                                          status_bitmap=0,
                                          read_timestamp=None)

    def poll_data(self):
        """
        Get all the polled registers from the device, and use the contents to fill in the instance data for this instance.

        :return:True for success, None if there were any errors.
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
                self.chipid = bytes(bytelist).decode('utf8')  # Convert the 16 bytes into a string
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
                self.status = self.codes['status']['fromid'][self.statuscode]
            elif regname == 'SYS_LIGHTS':
                self.service_led = bool(raw_value[0][0])
                self.indicator_code = raw_value[0][1]
                self.indicator_state = self.codes['leds']['fromid'][self.indicator_code]
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

        # Count how many system threshold registers there are, and create an empty list of register values
        conf_reglist = self.register_map['CONF'].keys()
        vlist = [0] * len(conf_reglist) * 4

        startreg = min([data[0] for data in self.register_map['CONF'].values()])
        for regname in conf_reglist:
            regnum, numreg, regdesc, scalefunc = self.register_map['CONF'][regname]
            values = self.thresholds[regname]
            vlist[(regnum - startreg) * 4:(regnum - startreg) * 4 + 4] = values

        res = self.conn.writeMultReg(modbus_address=self.modbus_address, regnum=startreg, valuelist=vlist)
        if res:
            return True
        else:
            return False

    def write_portconfig(self):
        """
        Write the current instance data for 'desired port state online' and 'desired port state offline' in each of
        the port status objects, to the FNDH.

        :return: True if successful, False on failure
        """
        vlist = [0] * 24
        startreg = self.register_map['POLL']['P01_STATE'][0]
        for portnum in range(1, 13):
            vlist[(portnum - 1) * 2] = self.ports[portnum].status_to_integer(write_state=True)
            vlist[(portnum - 1) * 2 + 1] = self.ports[portnum].current_raw

        res = self.conn.writeMultReg(modbus_address=self.modbus_address, regnum=startreg, valuelist=vlist)
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

        if portconfig:
            self.portconfig = portconfig

        ok = self.write_thresholds()
        if not ok:
            logger.error('Could not load and write threshold data.')
            return False

        # Make sure all the ports are off, both online and offline
        for portnum in range(1, 29):
            self.ports[portnum].desire_enabled_online = False
            self.ports[portnum].desire_enabled_offline = False
        ok = self.write_portconfig()
        if not ok:
            logger.error('Could not write port configuration to the FNDH.')
            return False

        # Write state register so the FNDH will transition to 'online'
        self.conn.writeReg(modbus_address=self.modbus_address, regnum=self.register_map['POLL']['SYS_STATUS'][0], value=1)
        return True

    def configure_final(self):
        """
        Use the self.portconfig data to set all the desired_state_online and desired_state_offline
        flags, and write the full set of port data to the FNDH, to turn on all desired ports.

        This is called after the power-on procedure, which turns on all of the ports, one by one, to determine
        which SMARTbox is connected to which PDoC port.
        """
        # Startup finished, now set all the port states as per the saved port configuration:
        for portnum in range(1, 29):
            self.ports[portnum].desire_enabled_online = bool(self.portconfig[portnum][0])
            self.ports[portnum].desire_enabled_offline = bool(self.portconfig[portnum][1])
        ok = self.write_portconfig()
        return ok

