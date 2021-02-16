#!/usr/bin/env python

"""Classes to handle communications with SKA-Low PaSD 'SMARTbox' elements, 24 of which make
   up an SKA-Low station.
"""

import logging

logging.basicConfig()
logger = logging.getLogger()
logger.level = logging.DEBUG

import conversion
import transport


# Dicts with register name as key, and a tuple of (register_number, number_of_registers, name, scaling_function) as value
FNDH_REGISTERS_1 = {  # These initial registers will be assumed to be fixed, between register map revisions
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

FNDH_CODES_1 = {'status':{'fromid':{0:'UNINITIALISED', 1:'OK', 2:'ALARM', 3:'WARNING', 4:'RECOVERY'},
                          'fromname':{'UNINITIALISED':0, 'OK':1, 'ALARM':2, 'WARNING':3, 'RECOVERY':4}},
                'leds':{'fromid':{0:'OFF', 1:'GREEN', 2:'RED', 3:'YELLOW'},
                        'fromname':{'OFF':0, 'GREEN':1, 'RED':2, 'YELLOW':3}}}


# Dicts with register version number as key, and a dict of registers (defined above) as value
FNDH_REGISTERS = {1: FNDH_REGISTERS_1}
FNDH_CODES = {1: FNDH_CODES_1}


class FNDH(transport.ModbusSlave):
    def __init__(self, conn=None):
        transport.ModbusSlave.__init__(self, conn=conn, station=None)
