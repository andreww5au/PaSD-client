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
SMARTBOX_REGISTERS_1 = {  # These initial registers will be assumed to be fixed, between register map revisions
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

                        # System threshold configuration registers (not polled)
                        # Note that SYS_48V_V_TH must always be in the first register of the configuration block,
                        #      because it's used to set the starting register for the block-write.
                        'SYS_48V_V_TH': (101, 4, 'Incoming 48VDC voltage CH, CL, WH, WL', conversion.scale_48v),
                        'SYS_PSU_V_TH': (105, 4, 'PSU output voltage CH, CL, WH, WL', conversion.scale_5v),
                        'SYS_PSUTEMP_TH': (109, 4, 'PSU temperature CH, CL, WH, WL', conversion.scale_temp),
                        'SYS_PCBTEMP_TH': (113, 4, 'PCB temperature CH, CL, WH, WL', conversion.scale_temp),
                        'SYS_OUTTEMP_TH': (117, 4, 'Outside temperature CH, CL, WH, WL', conversion.scale_temp),
                        'SYS_FEM01TEMP_TH': (121, 4, 'FEM 1 temperature CH, CL, WH, WL', conversion.scale_temp),
                        'SYS_FEM02TEMP_TH': (125, 4, 'FEM 2 temperature CH, CL, WH, WL', conversion.scale_temp),
                        'SYS_FEM03TEMP_TH': (129, 4, 'FEM 3 temperature CH, CL, WH, WL', conversion.scale_temp),
                        'SYS_FEM04TEMP_TH': (133, 4, 'FEM 4 temperature CH, CL, WH, WL', conversion.scale_temp),
                        'SYS_FEM05TEMP_TH': (137, 4, 'FEM 5 temperature CH, CL, WH, WL', conversion.scale_temp),
                        'SYS_FEM06TEMP_TH': (141, 4, 'FEM 6 temperature CH, CL, WH, WL', conversion.scale_temp),
                        'SYS_FEM07TEMP_TH': (145, 4, 'FEM 7 temperature CH, CL, WH, WL', conversion.scale_temp),
                        'SYS_FEM08TEMP_TH': (149, 4, 'FEM 8 temperature CH, CL, WH, WL', conversion.scale_temp),
                        'SYS_FEM09TEMP_TH': (153, 4, 'FEM 9 temperature CH, CL, WH, WL', conversion.scale_temp),
                        'SYS_FEM10TEMP_TH': (157, 4, 'FEM 10 temperature CH, CL, WH, WL', conversion.scale_temp),
                        'SYS_FEM11TEMP_TH': (161, 4, 'FEM 11 temperature CH, CL, WH, WL', conversion.scale_temp),
                        'SYS_FEM12TEMP_TH': (165, 4, 'FEM 12 temperature CH, CL, WH, WL', conversion.scale_temp),

                        # Port current threshold configuration registers (not polled)

}

SMARTBOX_CODES_1 = {'status':{'fromid':{0:'OK', 1:'WARNING', 2:'ALARM', 3:'RECOVERY', 4:'UNINITIALISED'},
                              'fromname':{'UNINITIALISED':0, 'OK':1, 'ALARM':2, 'WARNING':3, 'RECOVERY':4}},
                    'leds':{'fromid':{0:'OFF', 1:'GREEN', 2:'RED', 3:'YELLOW'},
                            'fromname':{'OFF':0, 'GREEN':1, 'RED':2, 'YELLOW':3}}}


# Dicts with register version number as key, and a dict of registers (defined above) as value
SMARTBOX_REGISTERS = {1: SMARTBOX_REGISTERS_1}
SMARTBOX_CODES = {1: SMARTBOX_CODES_1}

THRESHOLD_FILENAME = 'smartbox_thresholds.json'
PORTCONFIG_FILENAME = 'smartbox_ports.json'

STATUS_STRING = """\
SMARTBox at address: %(station)s:
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
    def __init__(self, port_number, status_bitmap, current, read_timestamp):
        """
        Given a 16 bit integer bitwise state (from a PNN_STATE register), instantiate a port status instance

        :param port_number: integer, 1-12
        :param status_bitmap: integer, 0-65535
        """
        self.port_number = port_number
        self.status_timestamp = None
        self.current_timestamp = None
        self.current = 0.0
        self.status_timestamp = read_timestamp
        self.system_level_enabled = None
        self.system_online = None
        self.desire_enabled_online = None   # Does the MCCS want this port enabled when the device is online
        self.desire_enabled_offline = None   # Does the MCCS want this port enabled when the device is offline
        self.locally_forced_on = None
        self.locally_forced_off = None
        self.breaker_tripped = None
        self.power_state = None

        self.set_current(current, read_timestamp=read_timestamp)
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
                            {False:'Power:ON', True:'Power:OFF', None:'Power:?'}[self.power_state],
                            {False:'', True:'BreakerTrip!', None:'Breaker:?'}[self.breaker_tripped]
                            ]
            status_string = ' '.join(status_items)

        return "P%02d: %s %s" % (self.port_number, current_string, status_string)

    def set_current(self, current, read_timestamp):
        self.current_timestamp = read_timestamp
        self.current = current

    def set_status_data(self, status_bitmap, read_timestamp):
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
            logger.warning('Unknown desire enabled online flag: %s' % bitstring[2:4])
            self.desire_enabled_online = None

        # Desired state offline - R/W, write 00 if no change to current value
        if (bitstring[4:6] == '10'):
            self.desire_enabled_offline = False
        elif (bitstring[4:6] == '11'):
            self.desire_enabled_offline = True
        elif (bitstring[4:6] == '00'):
            self.desire_enabled_offline = None
        else:
            logger.warning('Unknown desired state offline flag: %s' % bitstring[4:6])
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
        """Return a 16 bit integer corresponding to the instance data.

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

        bitstring += '000000'  # pad to 16 bits
        bitstring += b[self.power_state]
        return int(bitstring, 2)


class SMARTbox(transport.ModbusSlave):
    def __init__(self, conn=None, station=None):
        transport.ModbusSlave.__init__(self, conn=conn, station=station)

        self.mbrv = None
        self.pcbrv = None
        self.register_map = {}
        self.codes = {}
        self.fem_temps = {}  # Dictionary with FEM number (1-12) as key, and temperature as value
        self.mbrv = None
        self.pcbrv = None
        self.register_map = {}
        self.codes = {}
        self.cpuid = ''
        self.chipid = []
        self.firmware_version = 0
        self.uptime = 0
        self.station_value = 0
        self.incoming_voltage = 0.0
        self.psu_voltage = 0.0
        self.psu_temp = 0.0
        self.pcb_temp = 0.0
        self.outside_temp = 0.0
        self.statuscode = 0
        self.status = ''
        self.service_led = None
        self.indicator_code = None
        self.indicator_state = ''
        try:
            self.thresholds = json.load(open(THRESHOLD_FILENAME, 'r'))
        except Exception:
            self.thresholds = None
        try:
            allports = json.load(open(PORTCONFIG_FILENAME, 'r'))
            self.portconfig = allports[self.station]
        except Exception:
            self.portconfig = None

        self.ports = {}
        for pnum in range(1, 13):
            self.ports[pnum] = PortStatus(port_number=pnum, status_bitmap=0, current=0, read_timestamp=None)

    def __str__(self):
        return STATUS_STRING % (self.__dict__) + "\nPorts:\n" + ("\n".join([str(self.ports[pnum]) for pnum in range(1, 13)]))

    def poll_data(self):
        """
        Get all the polled registers from the device, and use the contents to fill in the instance data for this station

        :return:
        """
        bytelist = self.conn.readReg(station=self.station, regnum=1, numreg=59)   # TODO - calculate this value
        read_timestamp = time.time()
        if not bytelist:
            return False
        self.mbrv = transport.bytestoN(bytelist[0])
        self.pcbrv = transport.bytestoN(bytelist[1])
        self.register_map = SMARTBOX_REGISTERS[self.mbrv]
        self.codes = SMARTBOX_CODES[self.mbrv]

        self.fem_temps = {}  # Dictionary with FEM number (1-12) as key, and temperature as value
        for regname in self.register_map.keys():  # Iterate over all the register names in the current register map
            regnum, numreg, regdesc, scalefunc = self.register_map[regname]
            if regnum > 59:    # TODO - calculate this value
                continue    # Skip the configuration registers, as they aren't in polled data.
            raw_value = bytelist[regnum - 1:regnum + numreg - 1]
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
                self.chipid = raw_value   # TODO - is it a string? a hex value?
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
                self.indicator_state = self.codes['leds']['fromid'][self.indicator_code]
            elif (len(regname) >= 12) and ((regname[:7] + regname[-4:]) == 'SYS_FEMTEMP'):
                fem_num = int(regname[7:-4])
                self.fem_temps[fem_num] = scaled_float
            elif (len(regname) >= 8) and ((regname[0] + regname[-6:]) == 'P_STATE'):
                pnum = int(regname[1:-6])
                self.ports[pnum].set_status_data(status_bitmap=raw_int, read_timestamp=read_timestamp)
            elif (len(regname) >= 10) and ((regname[0] + regname[-8:]) == 'P_CURRENT'):
                pnum = int(regname[1:-8])
                self.ports[pnum].set_current(current=scaled_float, read_timestamp=read_timestamp)

    def write_thresholds(self):
        """
        Write the ADC threshold data (loaded on init from a JSON file into self.thresholds) to the SMARTbox.

        :return: True if successful, False on failure, None if self.thresholds is empty
        """
        if self.thresholds is None:
            return None

        # Count how many system threshold registers there are, and create an empty list of register values
        th_reglist = [regname for regname in self.register_map.keys() if regname.endswith('_TH')]
        vlist = [0] * len(th_reglist) * 4

        startreg = self.register_map['SYS_48V_V_TH'][0]  # This is guaranteed to be the first register in the polling block
        for regname in th_reglist:
            regnum, numreg, regdesc, scalefunc = self.register_map[regname]
            values = self.thresholds[regname]
            vlist[(regnum - startreg) * 4:(regnum - startreg) * 4 + 4] = values

        res = self.conn.writeMultReg(station=self.station, regnum=startreg, valuelist=vlist)
        if res:
            return True
        else:
            return False

    def write_portconfig(self):
        """
        Write the 'desired port state online' and 'desired port state offline' data (loaded from a JSON file into
        self.portconfig) to the SMARTbox.

        :return: True if successful, False on failure, None if self.portconfig is empty
        """
        if self.portconfig is None:
            return None

        vlist = [0] * 24
        startreg = self.register_map['P01_STATE'][0]
        for portnum in range(1, 13):
            self.ports[portnum].desire_enabled_online = bool(self.portconfig[portnum][0])
            self.ports[portnum].desire_enabled_offline = bool(self.portconfig[portnum][1])
            vlist[(portnum - 1) * 2] = self.ports[portnum].status_to_integer(write_state=True)

        res = self.conn.writeMultReg(station=self.station, regnum=startreg, valuelist=vlist)
        if res:
            return True
        else:
            return False

    def configure(self):
        """
        Write the threshold data, then if that succeeds, write a '1' to the status register to tell the micontroller to
        transistion out of the 'UNINITIALISED' state.
        :return: True for sucess
        """
        ok = self.write_thresholds()
        stillok = self.write_portconfig()
        if ok and stillok:
            return self.conn.writeReg(station=self.station, regnum=self.register_map['SYS_STATUS'][0], value=1)
        else:
            return False
