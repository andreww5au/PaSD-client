#!/usr/bin/env python

"""
Simulates a SMARTbox, acting as a Modbus slave and responding to 0x03, 0x06 and 0x10 Modbus commands
to read and write registers. Used for testing PaSD code.
"""

import logging
import random
import threading
import time

logging.basicConfig()

from pasd import smartbox

RETURN_BIAS = 0.1


def random_walk(current_value, mean, scale=1.0, return_bias=RETURN_BIAS):
    """
    Take the current and desired mean values of a simulated sensor value, and generate the next value,
    to simulate a random walk around the mean value, with a bias towards returning to the mean.

    With scale=1.0, typical variation over 1000 samples is roughly +/- 2.0

    :param current_value: Current sensor value, arbitrary units
    :param mean: Desired mean value
    :param scale: Scale factor for variations
    :param return_bias: Defaults to 0.1, increase this to reduce variation around the mean
    :return: Next value for the sensor reading
    """
    return current_value + scale * ((return_bias * (mean - current_value)) + (random.random() - 0.5))


class SimSMARTbox(smartbox.SMARTbox):
    """
    An instance of this class simulates a single SMARTbox, acting as a Modbus slave and responding to 0x03, 0x06 and
    0x10 Modbus commands to read and write registers.
    """
    def __init__(self, conn=None, modbus_address=None, logger=None):
        smartbox.SMARTbox.__init__(self, conn=conn, modbus_address=modbus_address, logger=logger)
        self.online = False   # Will be True if we've heard from the MCCS in the last 300 seconds.
        self.register_map = smartbox.SMARTBOX_REGISTERS[1]  # Assume register map version 1
        self.codes = smartbox.SMARTBOX_CODES[1]
        self.mbrv = 1   # Modbus register-map revision number for this physical SMARTbox
        self.pcbrv = 1  # PCB revision number for this physical SMARTbox
        self.sensor_temps = {i:33.33 for i in range(1, 13)}  # Dictionary with sensor number (1-12) as key, and temperature as value
        self.cpuid = 1    # CPU identifier (integer)
        self.chipid = bytes([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15])   # Unique ID number (16 bytes), different for every physical SMARTbox
        self.firmware_version = 1  # Firmware revision mumber for this physical SMARTbox
        self.uptime = 0            # Time in seconds since this SMARTbox was powered up
        self.station_value = modbus_address     # Modbus address read back from the SYS_ADDRESS register - should always equal modbus_address
        self.incoming_voltage = 47.9  # Measured voltage for the (nominal) 48VDC input power (Volts)
        self.psu_voltage = 5.1     # Measured output voltage for the internal (nominal) 5V power supply
        self.psu_temp = 45.0    # Temperature of the internal 5V power supply (deg C)
        self.pcb_temp = 38.0    # Temperature on the internal PCB (deg C)
        self.outside_temp = 34.0    # Outside temperature (deg C)
        self.initialised = False   # True if the system has been initialised by the LMC
        self.statuscode = 4    # Status value, used as a key for self.codes['status'] (eg 0 meaning 'OK')
        self.status = 'UNINITIALISED'       # Status string, obtained from self.codes['status'] (eg 'OK')
        self.service_led = False    # True if the blue service indicator LED is switched ON.
        self.indicator_code = 0  # LED status value, used as a key for self.codes['led']
        self.indicator_state = 'OFF'   # LED status, obtained from self.codes['led']
        self.readtime = 0    # Unix timestamp for the last successful polled data from this SMARTbox
        self.start_time = time.time()   # Unix timestamp when this instance started processing
        self.pdoc_number = None   # Physical PDoC port on the FNDH that this SMARTbox is plugged into. Populated by the station initialisation code on powerup
        self.wants_exit = False  # Set to True externally to kill self.mainloop if the box is pseudo-powered-off
        # Sensor states, with four thresholds for hysteris (alarm high, warning high, warning low, alarm low)
        # Each has three possible values (OK, WARNING or RECOVERY)
        self.sensor_states = {regname:'OK' for regname in self.register_map['CONF'] if not regname.endswith('_CURRENT_TH')}
        # Port current states, with only one (high) threshold, and fault handling internally. Can only be OK or ALARM
        self.portcurrent_states = {regname:'OK' for regname in self.register_map['CONF'] if regname.endswith('_CURRENT_TH')}

    def poll_data(self):
        """
        Stub, not needed for simulated SMARTbox
        """
        pass

    def read_uptime(self):
        """
        Stub, not needed for simulated SMARTbox
        """
        pass

    def write_thresholds(self):
        """
        Stub, not needed for simulated SMARTbox
        """
        pass

    def write_portconfig(self):
        """
        Stub, not needed for simulated SMARTbox
        """
        pass

    def configure(self, thresholds=None, portconfig=None):
        """
        Stub, not needed for simulated SMARTbox
        """
        pass

    def loophook(self):
        """
        Stub, overwrite if you subclass this to handle more complex simulation. Called every time a packet has
        finished processing, or every few seconds if there haven't been any packets.
        :return:
        """

    def listen_loop(self):
        """
        Listen on the socket for any incoming read/write register packets sent by an external bus master (eg, the MCCS).

        The transport.Connection.listen_for_packet() method exits after the first valid packet processed, to allow
        the calling code to handle side-effects from register read/write operations (for example, multiple reads from
        the same register block returning different values). This code loops forever, and each time, it:

        1) Sets up the slave_registers dictionary with the current box state.
        3) Calls self.conn.listen_for_packet(), which returns all of the register numbers read or written by a packet
           (if one was processed in that call). If no packets are received, it will return at the specified maxtime.
        4) Uses the list of written registers to update the box state, and update the 'heard from MCCS' timestamp.
        5) If any registers are in the 'read' list, update the 'heard from MCCS' timestamp.

        Note that we only traverse around the loop whenever we process an incoming packet

        :return: None
        """
        while not self.wants_exit:  # Process packets until we are told to die
            # Set up the registers for the physical->smartbox/port mapping:
            slave_registers = {}
            self.uptime = int(time.time() - self.start_time)  # Set the current uptime value

            for regname in self.register_map['POLL']:
                regnum, numreg, regdesc, scalefunc = self.register_map['POLL'][regname]
                if regname == 'SYS_MBRV':
                    slave_registers[regnum] = self.mbrv
                elif regname == 'SYS_PCBREV':
                    slave_registers[regnum] = self.pcbrv
                elif regname == 'SYS_CPUID':
                    slave_registers[regnum], slave_registers[regnum + 1] = divmod(self.cpuid, 65536)
                elif regname == 'SYS_CHIPID':
                    for i in range(numreg):
                        slave_registers[regnum + i] = self.chipid[i // 2] * 256 + self.chipid[i // 2 + 1]
                elif regname == 'SYS_FIRMVER':
                    slave_registers[regnum] = self.firmware_version
                elif regname == 'SYS_UPTIME':
                    slave_registers[regnum], slave_registers[regnum + 1] = divmod(self.uptime, 65536)
                elif regname == 'SYS_ADDRESS':
                    slave_registers[regnum] = self.station_value
                elif regname == 'SYS_48V_V':
                    slave_registers[regnum] = scalefunc(self.incoming_voltage, reverse=True, pcb_version=self.pcbrv)
                elif regname == 'SYS_PSU_V':
                    slave_registers[regnum] = scalefunc(self.psu_voltage, reverse=True, pcb_version=self.pcbrv)
                elif regname == 'SYS_PSUTEMP':
                    slave_registers[regnum] = scalefunc(self.psu_temp, reverse=True, pcb_version=self.pcbrv)
                elif regname == 'SYS_PCBTEMP':
                    slave_registers[regnum] = scalefunc(self.pcb_temp, reverse=True, pcb_version=self.pcbrv)
                elif regname == 'SYS_OUTTEMP':
                    slave_registers[regnum] = scalefunc(self.outside_temp, reverse=True, pcb_version=self.pcbrv)
                elif regname == 'SYS_STATUS':
                    slave_registers[regnum] = self.statuscode
                elif regname == 'SYS_LIGHTS':
                    slave_registers[regnum] = int(self.service_led) * 256 + self.indicator_code
                elif (regname[:9] == 'SYS_SENSE'):
                    sensor_num = int(regname[9:])
                    slave_registers[regnum] = scalefunc(self.sensor_temps[sensor_num], reverse=True, pcb_version=self.pcbrv)
                elif (len(regname) >= 8) and ((regname[0] + regname[-6:]) == 'P_STATE'):
                    pnum = int(regname[1:-6])
                    slave_registers[regnum] = self.ports[pnum].status_to_integer(write_state=True, write_to=True)
                elif (len(regname) >= 10) and ((regname[0] + regname[-8:]) == 'P_CURRENT'):
                    pnum = int(regname[1:-8])
                    slave_registers[regnum] = self.ports[pnum].current_raw

            for regname in self.register_map['CONF']:
                regnum, numreg, regdesc, scalefunc = self.register_map['CONF'][regname]
                if numreg == 1:
                    slave_registers[regnum] = scalefunc(self.thresholds[regname][0], reverse=True)
                elif numreg == 4:
                    (slave_registers[regnum],
                     slave_registers[regnum + 1],
                     slave_registers[regnum + 2],
                     slave_registers[regnum + 3]) = (scalefunc(x, reverse=True) for x in self.thresholds[regname])
                else:
                    self.logger.critical('Unexpected number of registers for %s' % regname)

            try:
                read_set, written_set = self.conn.listen_for_packet(listen_address=self.modbus_address,
                                                                    slave_registers=slave_registers,
                                                                    maxtime=1,
                                                                    validation_function=None)
            except:
                self.logger.exception('Exception in transport.listen_for_packet():')
                time.sleep(1)
                continue

            if self.register_map['POLL']['SYS_UPTIME'][0] in read_set:
                self.logger.debug('Uptime read: %14.3f' % self.uptime)

            if read_set or written_set:  # The MCCS has talked to us, update the last_readtime timestamp
                self.readtime = time.time()

            for regnum in range(self.register_map['POLL']['P01_STATE'][0], self.register_map['POLL']['P12_STATE'][0] + 1):
                if regnum in written_set:
                    port = self.ports[(regnum - self.register_map['POLL']['P01_STATE'][0]) + 1]
                    status_bitmap = slave_registers[regnum]
                    bitstring = "{:016b}".format(status_bitmap)

                    # Desired state online - R/W, write 00 if no change to current value
                    if (bitstring[2:4] == '10'):
                        port.desire_enabled_online = False
                    elif (bitstring[2:4] == '11'):
                        port.desire_enabled_online = True
                    elif (bitstring[2:4] == '00'):
                        pass
                    else:
                        self.logger.warning('Unknown desire enabled online flag: %s' % bitstring[2:4])
                        port.desire_enabled_online = None

                    # Desired state offline - R/W, write 00 if no change to current value
                    if (bitstring[4:6] == '10'):
                        port.desire_enabled_offline = False
                    elif (bitstring[4:6] == '11'):
                        port.desire_enabled_offline = True
                    elif (bitstring[4:6] == '00'):
                        pass
                    else:
                        self.logger.warning('Unknown desired state offline flag: %s' % bitstring[4:6])
                        port.desire_enabled_offline = None

                    # Technician override - R/W, write 00 if no change to current value
                    if (bitstring[6:8] == '10'):
                        port.locally_forced_on = False
                        port.locally_forced_off = True
                    elif (bitstring[6:8] == '11'):
                        port.locally_forced_on = True
                        port.locally_forced_off = False
                    elif (bitstring[6:8] == '01'):
                        port.locally_forced_on = False
                        port.locally_forced_off = False
                    else:
                        pass

                    if bitstring[8] == '1':  # Reset breaker
                        port.breaker_tripped = False

            for regname in self.register_map['CONF']:
                regnum, numreg, regdesc, scalefunc = self.register_map['CONF'][regname]
                if regnum in written_set:
                    self.thresholds[regname] = [scalefunc(slave_registers[x]) for x in range(regnum, regnum + 4)]

            if self.register_map['POLL']['SYS_LIGHTS'][0] in written_set:  # Wrote to SYS_LIGHTS, so set light attributes
                msb, lsb = divmod(slave_registers[self.register_map['POLL']['SYS_LIGHTS'][0]], 256)
                self.service_led = bool(msb)
                self.indicator_code = lsb
                self.indicator_state = self.codes['led']['fromid'][lsb]

            if self.register_map['POLL']['SYS_STATUS'][0] in written_set:   # Wrote to SYS_STATUS, so clear UNINITIALISED state
                self.initialised = True
                # We can't write to the statuscode or status, because it might be in a WARNING, ALARM or RECOVERY state
                # self.statuscode = 0
                # self.status = self.codes['status']['fromid'][0]

            if (self.statuscode not in [0, 1]):   # If we're not OK or WARNING, disable all the outputs
                for port in self.ports.values():
                    port.status_timestamp = time.time()
                    port.current_timestamp = port.status_timestamp
                    port.system_level_enabled = False
                    port.power_state = False
            else:
                for port in self.ports.values():
                    port.status_timestamp = time.time()
                    port.current_timestamp = port.status_timestamp
                    port.system_level_enabled = True
                    port_on = False
                    port.current_raw = 0
                    port.current = 0.0
                    if ( ( (self.online and port.desire_enabled_online)
                           or ((not self.online) and port.desire_enabled_offline)
                           or (port.locally_forced_on) )
                         and (not port.locally_forced_off) ):
                        port_on = True
                        port.current_raw = 2048
                        port.current = 50.0
                    port.power_state = port_on

            self.loophook()

    def sim_loop(self):
        """
        Runs continuously, simulating hardware processes independent of the communications packet handler
        :return:
        """
        self.start_time = time.time()

        self.logger.info('Started comms thread for Smartbox')
        listen_thread = threading.Thread(target=self.listen_loop, daemon=False, name=threading.current_thread().name + '-C')
        listen_thread.start()

        self.logger.info('Started simulation loop for smartbox')
        while not self.wants_exit:  # Process packets until we are told to die
            self.uptime = int(time.time() - self.start_time)  # Set the current uptime value

            if (time.time() - self.readtime >= 300) and self.online:   # More than 5 minutes since we heard from MCCS, go offline
                self.online = False
                for port in self.ports.values():
                    port.system_online = False
            elif (time.time() - self.readtime < 300) and (not self.online):   # Less than 5 minutes since we heard from MCCS, go online
                self.online = True
                for port in self.ports.values():
                    port.system_online = True

            time.sleep(0.5)

            if not self.initialised:
                continue   # Don't bother simulating sensor values until the thresholds have been set

            self.incoming_voltage = random_walk(self.incoming_voltage, 48.1, scale=2.0)
            self.psu_voltage = random_walk(self.psu_voltage, 5.1, scale=0.5)
            self.psu_temp = random_walk(self.psu_temp, 58.3, scale=3.0)
            self.pcb_temp = random_walk(self.pcb_temp, 38.0, scale=3.0)
            self.outside_temp = random_walk(self.outside_temp, 34.0, scale=3.0)

            # Test current voltage/temp/current values against threshold and update states
            for regname in self.register_map['CONF']:
                if regname.endswith('_CURRENT_TH'):
                    curstate = self.portcurrent_states[regname]
                    ah = self.thresholds[regname][0]
                    wh, wl, al = ah, -1, -2   # Only one threshold for port current, hysteresis handled in firmware
                    curvalue = self.ports[int(regname[1:3])].current
                    print(regname, ah, wh, wl, al, curvalue)
                else:
                    curstate = self.sensor_states[regname]
                    ah, wh, wl, al = self.thresholds[regname]
                    if regname == 'SYS_48V_V_TH':
                        curvalue = self.incoming_voltage
                    elif regname == 'SYS_PSU_V_TH':
                        curvalue = self.psu_voltage
                    elif regname == 'SYS_PSUTEMP_TH':
                        curvalue = self.psu_temp
                    elif regname == 'SYS_PCBTEMP_TH':
                        curvalue = self.pcb_temp
                    elif regname == 'SYS_OUTTEMP_TH':
                        curvalue = self.outside_temp
                    elif regname.startswith('SYS_SENSE'):
                        curvalue = self.sensor_temps[int(regname[9:])]
                    else:
                        self.logger.critical('Configuration register %s not handled by simulation code')
                        return
                    print(regname, ah, wh, wl, al, curvalue)

                newstate = curstate
                if curvalue > ah:
                    if curstate != 'ALARM':
                        newstate = 'ALARM'
                elif wh > curvalue >= ah:
                    if curstate == 'ALARM':
                        newstate = 'RECOVERY'
                    elif curstate != 'WARNING':
                        newstate = 'WARNING'
                elif wl >= curvalue >= wh:
                    newstate = 'OK'
                elif al <= curvalue < wl:
                    if curstate == 'ALARM':
                        newstate = 'RECOVERY'
                    else:
                        newstate = 'WARNING'
                elif curvalue < al:
                    newstate = 'ALARM'

                if curstate != newstate:
                    self.logger.warning('Sensor %s transitioned from %s to ALARM with reading of %4.2f' % (regname[:-3],
                                                                                                           curstate,
                                                                                                           curvalue))

                if regname.endswith('_CURRENT_TH'):
                    self.portcurrent_states[regname] = newstate
                else:
                    self.sensor_states[regname] = newstate

            if 'ALARM' in self.sensor_states.values():
                self.status = 'ALARM'
            elif 'WARNING' in self.sensor_states.values():
                self.status = 'WARNING'
            elif 'RECOVERY' in self.sensor_states.values():
                self.status = 'RECOVERY'
            elif not self.initialised:
                self.status = 'UNINITIALISED'
            else:
                self.status = 'OK'

            self.statuscode = self.codes['status']['fromname'][self.status]

        self.logger.info('Ending sim_loop() in SimSMARTbox')


"""
Use as 'simulate.py smartbox', or:

from pasd import transport
from simulate import sim_smartbox
conn = transport.Connection(hostname='134.7.50.185')  # address of ethernet-serial bridge
# or
conn = transport.Connection(devicename='/dev/ttyS0')  # or 'COM5' for example, under Windows

s = sim_smartbox.SimSMARTbox(conn=conn, modbus_address=1)
s.mainloop()
"""
