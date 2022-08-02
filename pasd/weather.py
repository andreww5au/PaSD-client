#!/usr/bin/env python

"""Classes to handle communications with an SKA-Low weather station, using a modified Smartbox

   This code runs on the MCCS side in the control building, and talks to a physical weather station SMARTbox module in the field.
"""

import json
import logging
import time

logging.basicConfig()

from pasd import conversion   # Conversion functions between register values and actual temps/voltages/currents
from pasd import transport    # Modbus API
from pasd import command_api  # System register API, for reset, firmware upload and rapid sampling

# Register definitions - only one mapping here now (SMARTBOX_POLL_REGS_1 and SMARTBOX_CONF_REGS_1 ), and these define
# the registers and codes for Modbus register map revision 1 (where SYS_MBRV==1).
#
# When firmware updates require a new register map and status codes, define new dictionaries SMARTBOX_POLL_REGS_2
# and SMARTBOX_CONF_REGS_2, and add them to the SMARTBOX_REGISTERS dictionary.
#
# When a SMARTbox is contacted, the SYS_MBRV register value (always defined to be in register 1) will be used to load
# the appropriate register map.
#
# Register maps are dictionaries with register name as key, and a tuple of (register_number, number_of_registers,
# description, scaling_function) as value.

MAX_HISTORY = 3600   # Accumulate counts for a max of 1 hour for more precision (eg for rain sensor)
MM_PER_COUNT = 0.2794   # mm of rain for each tick of the rain sensor
KPH_PER_CPS = 2.400    # One count per second represents 2.400 Kilometres per hour of wind speed


FILT_FREQ = 0.5    # 2 second low-pass smoothing on all smartbox sensor readings
SMOOTHED_REGLIST = []

WEATHER_POLL_REGS_1 = {  # These initial registers will be assumed to be fixed, between register map revisions
                        'SYS_MBRV':    (1, 1, 'Modbus register map revision', None),
                        'SYS_PCBREV':  (2, 1, 'PCB Revision number', None),
                        'SYS_CPUID':   (3, 2, 'Microcontroller device ID', None),
                        'SYS_CHIPID':  (5, 8, 'Chip unique device ID', None),
                        'SYS_FIRMVER': (13, 1, 'Firmware version', None),
                        'SYS_UPTIME':  (14, 2, 'Uptime in seconds', None),
                        'SYS_ADDRESS': (16, 1, 'MODBUS station ID', None),

                        # From here on register address and contents can change between firmware revisions
                        'SYS_48V_V':     (17, 1, 'Incoming 48VDC voltage', conversion.scale_48v),
                        'SYS_PSU_V':     (18, 1, 'PSU output voltage', conversion.scale_5v),
                        'SYS_PSUTEMP': (19, 1, 'PSU Temperature', conversion.scale_temp),
                        'SYS_PCBTEMP': (20, 1, 'PCB Temperature', conversion.scale_temp),
                        'SYS_OUTTEMP': (21, 1, 'Outside Temperature', conversion.scale_temp),
                        'SYS_STATUS':  (22, 1, 'System status code', None),
                        'SYS_LIGHTS':  (23, 1, 'LED state codes', None),

                        # Seven sensor inputs, each of which can be read as a raw ADU value
                        # via the SAMPLE_N registers, or as an accumulated (since the last register read)
                        # count of rising/falling edge events in the last PERIOD_N deciseconds (via the COUNT_N and PERIOD_N registers)
                        'SAMPLE_1': (24, 1, 'Sensor 1 - raw ADU', conversion.scale_temp),
                        'SAMPLE_2': (25, 1, 'Sensor 2 - raw ADU', conversion.scale_temp),
                        'SAMPLE_3': (26, 1, 'Sensor 3 - raw ADU', conversion.scale_temp),
                        'SAMPLE_4': (27, 1, 'Sensor 4 - raw ADU', conversion.scale_temp),
                        'SAMPLE_5': (28, 1, 'Sensor 5 - raw ADU', conversion.scale_temp),
                        'SAMPLE_6': (29, 1, 'Sensor 6 - raw ADU', conversion.scale_temp),
                        'SAMPLE_7': (30, 1, 'Sensor 7 - raw ADU', conversion.scale_temp),

                        # Read all COUNT_N and PERIOD_N registers together as a set, so the PERIOD values are correct
                        'COUNT_1': (31, 1, 'Counter 1 - of Sensor 1 events', conversion.scale_none),
                        'COUNT_2': (32, 1, 'Counter 2 - of Sensor 1 events', conversion.scale_none),
                        'COUNT_3': (33, 1, 'Counter 3 - of Sensor 1 events', conversion.scale_none),
                        'COUNT_4': (34, 1, 'Counter 4 - of Sensor 1 events', conversion.scale_none),
                        'COUNT_5': (35, 1, 'Counter 5 - of Sensor 1 events', conversion.scale_none),
                        'COUNT_6': (36, 1, 'Counter 6 - of Sensor 1 events', conversion.scale_none),
                        'COUNT_7': (37, 1, 'Counter 7 - of Sensor 1 events', conversion.scale_none),

                        'PERIOD_1': (38, 1, 'Deciseconds since last COUNT_1 read', conversion.scale_none),
                        'PERIOD_2': (39, 1, 'Deciseconds since last COUNT_2 read', conversion.scale_none),
                        'PERIOD_3': (40, 1, 'Deciseconds since last COUNT_3 read', conversion.scale_none),
                        'PERIOD_4': (41, 1, 'Deciseconds since last COUNT_4 read', conversion.scale_none),
                        'PERIOD_5': (42, 1, 'Deciseconds since last COUNT_5 read', conversion.scale_none),
                        'PERIOD_6': (43, 1, 'Deciseconds since last COUNT_6 read', conversion.scale_none),
                        'PERIOD_7': (44, 1, 'Deciseconds since last COUNT_7 read', conversion.scale_none),

}

# System threshold configuration registers (not polled)
WEATHER_CONF_REGS_1 = {  # thresholds with over-value alarm and warning, as well as under-value alarm and warning
                        'SENSOR_1_CONF': (1001, 4, 'Sample 1: Mode, rise, fall, hold', conversion.scale_none),
                        'SENSOR_2_CONF': (1005, 4, 'Sample 2: Mode, rise, fall, hold', conversion.scale_none),
                        'SENSOR_3_CONF': (1009, 4, 'Sample 3: Mode, rise, fall, hold', conversion.scale_none),
                        'SENSOR_4_CONF': (1013, 4, 'Sample 4: Mode, rise, fall, hold', conversion.scale_none),
                        'SENSOR_5_CONF': (1017, 4, 'Sample 5: Mode, rise, fall, hold', conversion.scale_none),
                        'SENSOR_6_CONF': (1021, 4, 'Sample 6: Mode, rise, fall, hold', conversion.scale_none),
                        'SENSOR_7_CONF': (1025, 4, 'Sample 7: Mode, rise, fall, hold', conversion.scale_none),
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
STATUS_POWERDOWN = 5      # Local tech wants the MCCS to turn off 48V to all FNDH ports in the station (long press)
STATUS_CODES = {-1:'UNKNOWN',
                0:'OK',
                1:'WARNING',
                2:'ALARM',
                3:'RECOVERY',
                4:'UNINITIALISED',
                5:'POWERDOWN'}

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

LED_GREENRED = 50       # Waiting for power-down from MCCS after long button press

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
WEATHER_REGISTERS = {1: {'POLL':WEATHER_POLL_REGS_1, 'CONF':WEATHER_CONF_REGS_1}}

STATUS_STRING = """\
Weather at address: %(modbus_address)s as of %(status_age)d ago:
    ModBUS register revision: %(mbrv)s
    PCB revision: %(pcbrv)s
    CPU ID: %(cpuid)s
    CHIP ID: %(chipid)s
    Firmware revision: %(firmware_version)s
    Uptime: %(uptime)s seconds
    R.Address: %(station_value)s
    Status: %(statuscode)s (%(status)s)
    Service LED: %(service_led)s
    Indicator: %(indicator_code)s (%(indicator_state)s)
    Wind: Direction %(wind_dir)s, speed %(wind_speed)s
    Temperature: %(temperature)s
    Light: %(light)s
    Rain: %(rain_avg)s
"""

# First column is ADU boundary value, second column is azimuth in degrees
WIND_DIRS = [
    (500, None),
    (789, 112.5),
    (912, 67.5),
    (1088, 90.0),
    (1431, 157.5),
    (1817, 135.0),
    (2107, 202.5),
    (2472, 180.0),
    (2823, 22.5),
    (3120, 45.0),
    (3358, 247.5),
    (3477, 225.0),
    (3641, 337.5),
    (3761, 0.0),
    (3848, 292.5),
    (3942, 315.0),
    (4041, 270.0),
    (4095, None),
]

# Table 1 is degreesC x 100 for ADC values on 256 ADU boundaries with tweaks for the two extremes
TEMPS1 = [20000, 12068, 9470, 8004, 6957, 6120, 5406, 4765, 4168, 3592, 3020, 2430, 1798, 1083, 201, -20000]

# Table 2 is delta degreesC x 100 with tweaks for the end points to give 'out of range' values
TEMPS2 = [0, 2598, 1466, 1047, 837, 714, 641, 597, 576, 572, 590, 632, 715, 882, 1294, 0]


class Sensor(object):
    """
    Represents a single one of the 7 mulitpurpose sensor inputs in a weatherstation smartbox. Each sensor is
    read from the microcontroller via the SAMPLE_N, COUNT_N and PERIOD_N registers for that sensor.

    The SAMPLE_N register always contains the instantaneous raw ADC value for that analog input
    The COUNT_N contains the number of rising/falling/both edges seen since the last COUNT_N register read
    The PERIOD_N contains the number of deciseconds since the corresponding COUNT_N register was read and reset.

    The read mode for each sensor is defined in the corresponding COUNT_N_CONF registers - four 16-bit words:
        - MODE:
            = 0 - no counting (COUNT_N and PERIOD_N registers do nothing), use raw value
            = 1 - rising edge count
            = 2 - falling edge count
            = 3 - rising AND falling edge count
            = 4 - stabilised. COUNT_N contains the raw ADC value, but only if it has been
                    stable (less than RISING_EDGE of jitter) over HOLD_TIME seconds.
        - RISING_EDGE - ADC value must be greater than this to count as a rising edge
        - FALLING_EDGE - ADC value must be less than this to count as a falling edge
        - HOLD_TIME - time in MILLIseconds that the value must be high and/or low to count as an edge

    When in an edge detection counting mode the algorithm is quite basic.  Initial "low" state.

        1) Wait for ADU to exceed RISING_EDGE_n value
        2) Wait HOLD_TIME_n milliseconds (can be zero)
        3) If it is still above - transition to high state else go back to 1)
        4) Wait for ADU to fall below FALLING_EDGE_n value
        5) Wait HOLD_TIME_n milliseconds
        6) If it is still below - transition to low state else go back to 4)
        7) go to 1)
    """

    def __init__(self, sid, mode=0, rising_edge=0, falling_edge=0, hold_time=0, logger=logging):
        self.sid = sid
        self.mode = mode
        self.rising_edge = rising_edge
        self.falling_edge = falling_edge
        self.hold_time = hold_time
        self.sample = 0
        self.count = 0
        self.period = 0
        self.history = []   # List of (count, period) tuples for mode 1,2,3 sensors, capped at a total period of MAX_HISTORY
        self.logger = logger

    def push_new(self):
        """
        Add the most recently set count,period pair, to accumulate a history of previous values for more precision

        :return: None
        """
        if self.mode in [1, 2, 3]:
            self.history.append((self.count, self.period))
            total_time = 0.1 * sum([x[1] for x in self.history])   # period values are in tenths of a second
            if total_time >= MAX_HISTORY:
                self.history = self.history[1:]

    def value(self):
        """
        Depending on the mode for this sensor, return either the raw value in self.sample (mode 0), or the
        stabilised value in self.count (mode 4). If mode is 1, 2 or 3, return None and log an error.

        :return: integer - Either a value in ADC, or None if there was an error
        """
        if self.mode == 0:
            return self.sample
        elif self.mode in [1, 2, 3]:
            self.logger.error('Called .value() on a sensor in edge-counting mode.')
            return None
        elif self.mode == 4:
            return self.count   # Stabilised value is in the COUNT_N register
        else:
            self.logger.error('Invalid mode %s for sensor' % self.mode)
            return None

    def rate(self):
        """
        If the sensor is in edge-counting mode, return the rate as the number of pulses per second, as seen over the
        most recent count (using the current values of count and period), otherwise log an error and return None

        :return: float - Either a rate in edges per second, or None if there was an error
        """
        if self.mode in [1, 2, 3]:
            if self.period != 0:
                return 10.0 * float(self.count) / self.period
            else:
                return 0.0
        elif self.mode in [0, 4]:
            self.logger.error('Called .rate() on a sensor not in edge-counting mode.')
            return None
        else:
            self.logger.error('Invalid mode %s for sensor' % self.mode)
            return None

    def avg_data(self):
        """
        If the sensor is in edge-counting mode, return the total count ocer the history period, and the total number of
        seconds, as seen over the aggregated history of count,period measurements (using self.history),
        otherwise log an error and return None, None

        :return: tuple of (total_count, total_seconds)
        """
        if self.mode in [1, 2, 3]:
            tcount = sum([x[0] for x in self.history])
            tperiod = sum([x[1] for x in self.history]) / 10.0
            return tcount, tperiod
        else:
            return None, None

    def __str__(self):
        if self.mode in [1, 2, 3]:
            vs = '%0.4f' % self.rate()
        elif self.mode in [0, 4]:
            vs = '%0.4f' % self.value()
        else:
            vs = '?'
        return "Sensor %d: %s" % (self.sid, vs)

    def __repr__(self):
        return str(self)

    def config_to_registers(self):
        """
        Return a list of four 16-bit integers to write into the appropriate COUNT_N_CONF register block

        :return: A list of 4 16-bit integers
        """
        return [self.mode, self.rising_edge, self.falling_edge, self.hold_time]


class Weather(transport.ModbusDevice):
    """
    Weather SMARTbox class, an instances of which represents a weather station inside an SKA-Low station, connected to an
    FNDH via a shared low-speed serial bus.

    Attributes are:
    modbus_address: Modbus address of this SMARTbox (1-30)
    mbrv: Modbus register-map revision number for this physical SMARTbox
    pcbrv: PCB revision number for this physical SMARTbox
    register_map: A dictionary mapping register name to (register_number, number_of_registers, description, scaling_function) tuple
    sensor_temps: A dictionary with sensor number (1-12) as key, and temperature as value
    cpuid: CPU identifier (integer)
    chipid: Unique ID number (16 bytes), different for every physical SMARTbox
    firmware_version: Firmware revision mumber for this physical SMARTbox
    uptime: Time in seconds since this SMARTbox was powered up
    station_value: Modbus address read back from the SYS_ADDRESS register - should always equal modbus_address
    statuscode: Status value, one of the STATUS_* globals, and used as a key for STATUS_CODES (eg 0 meaning 'OK')
    status: Status string, obtained from STATUS_CODES global (eg 'OK')
    service_led: True if the blue service indicator LED is switched ON.
    indicator_code: LED status value, one of the LED_* globals, and used as a key for LED_CODES
    indicator_state: LED status string, obtained from LED_CODES
    readtime: Unix timestamp for the last successful polled data from this SMARTbox
    pdoc_number: Physical PDoC port on the FNDH that this SMARTbox is plugged into. Populated by the station initialisation code on powerup
    sensors: A dictionary, with 1-7 as the key, and instances of Sensor() as the values
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
        self.sensor_temps = {}  # Dictionary with sensor number (1-12) as key, and (probably) temperature as value
        self.cpuid = ''    # CPU identifier (integer)
        self.chipid = []   # Unique ID number (16 bytes), different for every physical SMARTbox
        self.firmware_version = 0  # Firmware revision mumber for this physical SMARTbox
        self.uptime = 0            # Time in seconds since this SMARTbox was powered up
        self.station_value = 0     # Modbus address read back from the SYS_ADDRESS register - should always equal modbus_address
        self.statuscode = STATUS_UNKNOWN    # Status value, one of the STATUS_* globals, and used as a key for STATUS_CODES (eg 0 meaning 'OK')
        self.status = 'UNKNOWN'       # Status string, obtained from STATUS_CODES global (eg 'OK')
        self.service_led = False    # True if the blue service indicator LED is switched ON.
        self.indicator_code = LED_UNKNOWN  # LED status value, one of the LED_* globals, and used as a key for LED_CODES
        self.indicator_state = 'UNKNOWN'   # LED status string, obtained from LED_CODES
        self.readtime = 0    # Unix timestamp for the last successful polled data from this SMARTbox
        self.pdoc_number = None   # Physical PDoC port on the FNDH that this SMARTbox is plugged into. Populated by the station initialisation code on powerup
        self.sensors = {}
        self.sensors[1] = Sensor(sid=1, mode=2, rising_edge=3800, falling_edge=800, hold_time=100)  # Rain - falling edge
        self.sensors[2] = Sensor(sid=2, mode=1, rising_edge=3800, falling_edge=800, hold_time=20)   # Wind speed - rising edge
        self.sensors[3] = Sensor(sid=3, mode=4, rising_edge=10, falling_edge=0, hold_time=100)  # Wind direction - stabilised
        self.sensors[4] = Sensor(sid=4, mode=0)   # Temperature - raw
        self.sensors[5] = Sensor(sid=5, mode=0)   # Light - raw
        self.sensors[6] = Sensor(sid=6)   # unused
        self.sensors[7] = Sensor(sid=7)   # unused

    def __str__(self):
        tmpdict = self.__dict__.copy()
        tmpdict['status_age'] = time.time() - self.readtime
        tmpdict['wind_dir'] = "?"
        tmpdict['wind_speed'] = "?"
        tmpdict['rain_avg'] = "?"
        tmpdict['temperature'] = "?"
        tmpdict['light'] = "?"
        v = self.wind_dir()
        if v is not None:
            tmpdict['wind_dir'] = "%d degrees E of N" % v
        v = self.wind_speed()
        if v is not None:
            tmpdict['wind_speed'] = "%0.4f km/hour" % v
        v = self.rain_avg()
        if v is not None:
            tmpdict['rain_avg'] = "%0.4f mm/hour" % v
        v = self.temperature()
        if v is not None:
            tmpdict['temperature'] = "%0.2f degC" % v
        v = self.light()
        if v is not None:
            tmpdict['light'] = "%0.4f Lux (%d raw)" % (v, self.sensors[5].value())
        return (STATUS_STRING % tmpdict)

    def __repr__(self):
        return str(self)

    def poll_data(self):
        """
        Get all the polled registers from the device, and use the contents to fill in the instance data for this instance.

        :return: True for success, None if there were any errors.
        """
        if self.register_map:  # We've talked to this box before, so we know the actual register map
            tmp_regmap = self.register_map['POLL']
        else:   # We haven't talked to this box, so use a default map to get the registers to read this time
            tmp_regmap = WEATHER_POLL_REGS_1
        maxregnum = max([data[0] for data in tmp_regmap.values()])
        maxregname = [name for (name, data) in tmp_regmap.items() if data[0] == maxregnum][0]
        poll_blocksize = maxregnum + (tmp_regmap[maxregname][1] - 1)  # number of registers to read

        # Get a list of tuples, where each tuple is a two-byte register value, eg (0,255)
        try:
            valuelist = self.conn.readReg(modbus_address=self.modbus_address, regnum=1, numreg=poll_blocksize)
        except IOError:
            self.logger.info('No data returned by readReg in poll_data for SMARTbox %d' % self.modbus_address)
            return None
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
        self.register_map = WEATHER_REGISTERS[self.mbrv]

        self.sensor_temps = {}  # Dictionary with sensor number (1-12) as key, and (probably) temperature as value
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
            elif regname == 'SYS_STATUS':
                self.statuscode = raw_int
                self.status = STATUS_CODES[self.statuscode]
            elif regname == 'SYS_LIGHTS':
                self.service_led = bool(raw_value[0][0])
                self.indicator_code = raw_value[0][1]
                self.indicator_state = LED_CODES[self.indicator_code]
            elif (regname[:7] == 'SAMPLE_'):
                sensor_num = int(regname[7:])
                self.sensors[sensor_num].sample = raw_int
            elif (regname[:6] == 'COUNT_'):
                sensor_num = int(regname[6:])
                self.sensors[sensor_num].count = raw_int
            elif (regname[:7] == 'PERIOD_'):
                sensor_num = int(regname[7:])
                self.sensors[sensor_num].period = raw_int
                self.sensors[sensor_num].push_new()   # Add the most recent count,period pair to the history
        self.readtime = read_timestamp
        return True

    def read_uptime(self):
        """
        Read enough registers to get the register revision number, and the system uptime.

        :return: uptime in seconds, or None if there was an error.
        """
        try:
            valuelist = self.conn.readReg(modbus_address=self.modbus_address, regnum=1, numreg=16)
        except IOError:
            self.logger.info('No data returned in read_uptime for SMARTbox %d' % self.modbus_address)
            return None
        except:
            self.logger.exception('Exception in readReg in read_uptime for SMARTbox %d' % self.modbus_address)
            return None

        if valuelist is None:
            self.logger.error('Error in readReg in read_uptime for SMARTbox %d, no data' % self.modbus_address)
            return None

        if len(valuelist) != 16:
            self.logger.warning('Only %d registers returned from SMARTbox %d by readReg in read_uptime, expected %d' % (len(valuelist),
                                                                                                                        self.modbus_address,
                                                                                                                        16))
            return None

        self.mbrv = valuelist[0][0] * 256 + valuelist[0][1]
        self.pcbrv = valuelist[1][0] * 256 + valuelist[1][1]
        self.register_map = WEATHER_REGISTERS[self.mbrv]
        regnum, numreg, regdesc, scalefunc = self.register_map['POLL']['SYS_UPTIME']
        raw_value = valuelist[regnum - 1:regnum + numreg - 1]
        self.uptime = transport.bytestoN(raw_value)   # I know uptime is 2 registers, 4 bytes
        return self.uptime

    def wind_dir(self):
        """
        Return the most recently read wind direction, as a compass bearing (0=North, 90=East), using the value of
        sensor 3.

        :return: integer (0-360), or None if the sensor is open circuit or shorted
        """
        v = self.sensors[3].value()
        if v is None:
            return None
        for boundary, azimuth in WIND_DIRS:
            if v < boundary:
                return azimuth
        return None

    def rain_avg(self):
        """
        Return a rolling average of rainfall in mm/hour, using the avg_data() function on sensor 1

        Each count is 0.2794 mm of rain.

        :return: mm of rain per hour
        """
        tcount, tseconds = self.sensors[1].avg_data()
        if not tseconds:  # Invalid response, or zero
            return None
        return 3600 * MM_PER_COUNT * tcount / tseconds

    def wind_speed(self):
        """
        Return the most recent wind speed, in metres per second, using the rate() function on sensor 2

        :return: wind speed in m/s
        """
        cps = self.sensors[2].rate()
        if cps is None:
            return None
        return KPH_PER_CPS * cps

    def temperature(self):
        """
        Return the air temperature, in degrees C, using the value() method of sensor 4

        :return: temperature in degrees C
        """
        v = int(self.sensors[4].value())
        if v is None:
            return None
        temp_ndx = (v & 0x0f00) >> 8
        temps32b = (TEMPS2[temp_ndx] * (v & 0x00ff) + 0x80) >> 8
        return (TEMPS1[temp_ndx] - temps32b) / 100.0

    def light(self):
        """
        Returns the ambient light level in Lux using the value() method of sensor 5

        :return: Light level in Lux
        """
        v = self.sensors[5].value()
        if v is None:
            return None
        return 114400.0 - (v / 4095.0 * 114400.0)   # Assuming a 1.5k pullup resistor

    def configure(self, thresholds=None, portconfig=None):
        """
        Use the threshold data as given, or in self.thresholds read from the config file on initialisation, and write
        it to the SMARTbox.

        If that succeeds, use the port configuration (desired state online, desired state offline) as given, or in
        self.portconfig read from the config file on initialisation, and write it to the SMARTbox.

        Then, if that succeeds, write a '1' to the status register to tell the microcontroller to
        transition out of the 'UNINITIALISED' state.

        :param thresholds: A dictionary containing the ADC thresholds to write to the SMARTbox. If none, use defaults
                           from the JSON file specified in THRESHOLD_FILENAME loaded on initialistion into self.thresholds
        :param portconfig: A dictionary containing the port configuration data to write to the SMARTbox. If none, use
                           defaults from the JSON file specified in PORTCONFIG_FILENAME loaded on initialistion into self.portconfig
        :return: True for sucess
        """

        if not self.register_map:
            self.logger.error('No register map, call poll_data() first')
            return None

        ok = True
        for sensorid, sensor in self.sensors:
            conf_block = sensor.config_to_registers()
            regname = 'SENSOR_%d_CONF' % sensorid
            try:
                tok = self.conn.writeReg(modbus_address=self.modbus_address,
                                         regnum=self.register_map['CONF'][regname][0],
                                         value=conf_block)
                if not tok:
                    ok = False
            except:
                self.logger.exception('Exception in transport.writeReg() in configure:')
                return False

        if ok:
            try:
                return self.conn.writeReg(modbus_address=self.modbus_address, regnum=self.register_map['POLL']['SYS_STATUS'][0], value=1)
            except:
                self.logger.exception('Exception in transport.writeReg() in configure:')
                return False
        else:
            self.logger.error('Error sending sensor configuration.')
        return False

    def reset(self):
        """
        Sends a command to reset the microcontroller.

        :return: None
        """
        command_api.reset_microcontroller(conn=self.conn,
                                          address=self.modbus_address,
                                          logger=self.logger)

    def get_sample(self, interval, reglist):
        """
        Return the sensor data for the registers in reglist, sampled every 'interval' milliseconds, for as long as it
        takes to record 10000 values (5000 samples of 2 registers, 2500 samples of 4 registers, etc).

        :param interval: How often (in milliseconds) to sample the data
        :param reglist:  Which register numbers to sample
        :return: A dictionary with register number as key, and lists of register samples as values.
        """
        result = command_api.start_sample(conn=self.conn,
                                          address=self.modbus_address,
                                          interval=interval,
                                          reglist=reglist,
                                          logger=self.logger)

        if not result:
            self.logger.error('Error starting data sampling.')
            return
        self.logger.info('Start sampling register/s %s every %d milliseconds' % (reglist, interval))

        sample_size = command_api.get_sample_size(conn=self.conn, address=self.modbus_address, logger=self.logger)
        sample_count = 0
        done = False
        while not done:
            sample_count = command_api.get_sample_count(conn=self.conn, address=self.modbus_address, logger=self.logger)
            if sample_count is None:
                self.logger.error('Error monitoring data sampling.')
                return
            elif sample_count >= sample_size // len(reglist):   # Allow for multiregister captures
                done = True

            time.sleep(0.5)

        self.logger.info('Downloading %d samples' % sample_count)
        data = command_api.get_sample_data(conn=self.conn, address=self.modbus_address, reglist=reglist)
        return data

    def save_sample(self, interval, reglist, filename):
        """
        Call get_sample(), then save the results in CSV format in the given filename.

        :param interval: How often (in milliseconds) to sample the data
        :param reglist:  Which register numbers to sample
        :param filename: Filename to save the sample data in
        :return: None
        """
        data = self.get_sample(interval=interval, reglist=reglist)
        if data is None:
            return
        regdict = {}
        for regname in self.register_map['POLL'].keys():
            regnum, numreg, regdesc, scalefunc = self.register_map['POLL'][regname]
            if regnum in reglist:
                regdict[regnum] = regname
        outf = open(filename, 'w')
        outf.write(', '.join([str(regdict[regnum]) for regnum in reglist]) + '\n')
        for i in range(len(data[reglist[0]])):
            outf.write(', '.join(['%d' % data[regnum][i] for regnum in reglist]) + '\n')
        outf.close()

    def set_smoothing(self, freq=FILT_FREQ, reglist=None):
        """
        Apply the given low-pass frequency cutoff to a list of registers. All of the
        registers must be ones containing sensor values (temperatures, voltages, currents).

        :param freq: Low-pass cut off frequency, in Hz, or None to disable filtering
        :param reglist: List of sensor register numbers to apply that filter constant to
        :return:
        """
        filt_constant = command_api.filter_constant(freq)
        for reg in reglist:
            self.conn.writeReg(self.modbus_address, reg, filt_constant)


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
