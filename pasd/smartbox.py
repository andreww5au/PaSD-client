#!/usr/bin/env python

"""Classes to handle communications with SKA-Low PaSD 'SMARTbox' elements, 24 of which make
   up an SKA-Low station.
"""

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

                        # Note - only a few of these FEM enclosure temps will return valid data
                        'SYS_FEM1TEMP': (23, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_FEM2TEMP': (24, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_FEM3TEMP': (25, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_FEM4TEMP': (26, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_FEM5TEMP': (27, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_FEM6TEMP': (28, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_FEM7TEMP': (29, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_FEM8TEMP': (30, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_FEM9TEMP': (31, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_FEM10TEMP': (32, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_FEM11TEMP': (33, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_FEM12TEMP': (34, 1, 'FEM Temperature', conversion.scale_temp),

                        # Per-port status variables
                        'P01_STATE': (35, 1, 'Port 01 state bitmap', None),
                        'P01_CURRENT': (36, 1, 'Port 01 current', conversion.scale_current),
                        'P02_STATE': (37, 1, 'Port 02 state bitmap', None),
                        'P02_CURRENT': (38, 1, 'Port 02 current', conversion.scale_current),
                        'P03_STATE': (39, 1, 'Port 03 state bitmap', None),
                        'P03_CURRENT': (40, 1, 'Port 03 current', conversion.scale_current),
                        'P04_STATE': (41, 1, 'Port 04 state bitmap', None),
                        'P04_CURRENT': (42, 1, 'Port 04 current', conversion.scale_current),
                        'P05_STATE': (43, 1, 'Port 05 state bitmap', None),
                        'P05_CURRENT': (44, 1, 'Port 05 current', conversion.scale_current),
                        'P06_STATE': (45, 1, 'Port 06 state bitmap', None),
                        'P06_CURRENT': (46, 1, 'Port 06 current', conversion.scale_current),
                        'P07_STATE': (47, 1, 'Port 07 state bitmap', None),
                        'P07_CURRENT': (48, 1, 'Port 07 current', conversion.scale_current),
                        'P08_STATE': (49, 1, 'Port 08 state bitmap', None),
                        'P08_CURRENT': (50, 1, 'Port 08 current', conversion.scale_current),
                        'P09_STATE': (51, 1, 'Port 09 state bitmap', None),
                        'P09_CURRENT': (52, 1, 'Port 09 current', conversion.scale_current),
                        'P10_STATE': (53, 1, 'Port 10 state bitmap', None),
                        'P10_CURRENT': (54, 1, 'Port 10 current', conversion.scale_current),
                        'P11_STATE': (55, 1, 'Port 11 state bitmap', None),
                        'P11_CURRENT': (56, 1, 'Port 11 current', conversion.scale_current),
                        'P12_STATE': (57, 1, 'Port 12 state bitmap', None),
                        'P12_CURRENT': (58, 1, 'Port 12 current', conversion.scale_current),
}

SMARTBOX_CODES_1 = {'status':{'fromid':{0:'UNINITIALISED', 1:'OK', 2:'ALARM', 3:'WARNING', 4:'RECOVERY'},
                              'fromname':{'UNINITIALISED':0, 'OK':1, 'ALARM':2, 'WARNING':3, 'RECOVERY':4}},
                    'leds':{'fromid':{0:'OFF', 1:'GREEN', 2:'RED', 3:'YELLOW'},
                            'fromname':{'OFF':0, 'GREEN':1, 'RED':2, 'YELLOW':3}}}


# Dicts with register version number as key, and a dict of registers (defined above) as value
SMARTBOX_REGISTERS = {1: SMARTBOX_REGISTERS_1}
SMARTBOX_CODES = {1: SMARTBOX_CODES_1}


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
    Service LED ON: %(service_led)s
    Indicator %(indicator_code)s (%(indicator_state)s)
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

    def status_to_integer(self):
        """Return a 16 bit integer corresponding to the instance data.
        """
        b = {True:'1', False:'0'}
        bitstring = b[self.system_level_enabled] + b[self.system_online]

        if self.desire_enabled_online is None:
            bitstring += '00'
        else:
            bitstring += '1' + b[self.desire_enabled_online]

        if self.desire_enabled_offline is None:
            bitstring += '00'
        else:
            bitstring += '1' + b[self.desire_enabled_offline]

        if (self.locally_forced_on is None) or (self.locally_forced_off is None):
            bitstring += '00'
        elif self.locally_forced_off:
            bitstring += '10'
        elif self.locally_forced_on:
            bitstring += '11'
        else:
            bitstring += '01'

        bitstring += b[self.breaker_tripped] + b[self.power_state]
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

        self.ports = {}
        for pnum in range(1, 13):
            self.ports[pnum] = PortStatus(port_number=pnum, status_bitmap=0, current=0, read_timestamp=None)

    def __str__(self):
        return STATUS_STRING % (self.__dict__) + "\nPorts:\n" + ("\n".join([str(self.ports[pnum]) for pnum in range(1, 13)]))

    def get_data(self):
        """
        Get all the registers from the device, and use the contents to fill in the instance data for this station

        :return:
        """
        bytelist = self.conn.readReg(station=self.station, regnum=1, numreg=58)
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
            raw_value = bytelist[regnum - 1:regnum + numreg - 2]
            raw_int = None
            scaled_float = None
            if numreg <= 2:
                raw_int = transport.bytestoN(raw_value)
            if scalefunc:
                scaled_float = scalefunc(raw_int, self.pcbrv)

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
                self.service_led = bool(raw_value[0])
                self.indicator_code = raw_value[1]
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
