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
import smartbox
import transport


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
    def __init__(self, port_number, modbus_address, status_bitmap, read_timestamp):
        smartbox.PortStatus.__init__(self, port_number, modbus_address, status_bitmap, 0, 0.0, read_timestamp)

        self.power_sense = None

    def set_status_data(self, status_bitmap, read_timestamp):
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
            status_items = ['Status(%1.1f s) on SMARTbox %s:' % (time.time() - self.current_timestamp, self.modbus_address),
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
        self.psu48v1_voltage = 0.0
        self.psu48v2_voltage = 0.0
        self.psu5v_voltage = 0.0
        self.psu48v_current = 0.0
        self.psu48v_temp = 0.0
        self.psu5v_temp = 0.0
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

        self.ports = {}
        for pnum in range(1, 29):
            self.ports[pnum] = PdocStatus(port_number=pnum,
                                          modbus_address=modbus_address,
                                          status_bitmap=0,
                                          read_timestamp=None)

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
        Write the 'desired port state online' and 'desired port state offline' data (loaded from a JSON file into
        self.portconfig) to the FNDH.

        :return: True if successful, False on failure, None if self.portconfig is empty
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

    def configure(self, thresholds=None, portconfig=None):
        """
         Get the threshold data (as given, or from the config file), and write it to the FNDH.

         If that succeeds, read the port configuration (desired state online, desired state offline) from the config
         file (if it's not supplied), and write it to the FNDH.

         Then, if that succeeds, write a '1' to the status register to tell the micontroller to
         transition out of the 'UNINITIALISED' state.

         :param thresholds: A dictionary containing the ADC thresholds to write to the FNDH. If none, use defaults
                            from the JSON file specified in THRESHOLD_FILENAME
         :param portconfig: A dictionary containing the port configuration data to write to the FNDH. If none, use
                            defaults from the JSON file specified in PORTCONFIG_FILENAME
         :return: True for sucess
         """
        if thresholds:
            self.thresholds = thresholds

        if portconfig:
            self.portconfig = portconfig

        ok = self.write_thresholds()

        if ok:
            for portnum in range(1, 13):
                self.ports[portnum].desire_enabled_online = bool(self.portconfig[portnum][0])
                self.ports[portnum].desire_enabled_offline = bool(self.portconfig[portnum][1])
            ok = self.write_portconfig()
            if ok:
                return self.conn.writeReg(modbus_address=self.modbus_address, regnum=self.register_map['POLL']['SYS_STATUS'][0], value=1)
            else:
                logger.error('Could not load and write port state configuration.')
        else:
            logger.error('Could not load and write threshold data.')
        return False
