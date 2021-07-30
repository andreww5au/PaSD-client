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

RETURN_BIAS = 0.05

STATUS_STRING = """\
Simulated SMARTBox at address: %(modbus_address)s:
    ModBUS register revision: %(mbrv)s
    PCB revision: %(pcbrv)s
    CPU ID: %(cpuid)s
    CHIP ID: %(chipid)s
    Firmware revision: %(firmware_version)s
    Uptime: %(uptime)s seconds
    R.Address: %(station_value)s
    48V In: %(incoming_voltage)4.2f V
    5V out: %(psu_voltage)4.2f V
    PSU Temp: %(psu_temp)4.2f deg C
    PCB Temp: %(pcb_temp)4.2f deg C
    Outside Temp: %(outside_temp)4.2f deg C
    Status: %(statuscode)s (%(status)s)
    Service LED: %(service_led)s
    Indicator: %(indicator_code)s (%(indicator_state)s)
    Initialised: %(initialised)s
    Online: %(online)s
"""


def random_walk(current_value, mean, scale=1.0, return_bias=RETURN_BIAS):
    """
    Take the current and desired mean values of a simulated sensor value, and generate the next value,
    to simulate a random walk around the mean value, with a bias towards returning to the mean.

    With scale=1.0, typical variation over 1000 samples is roughly +/- 2.0

    :param current_value: Current sensor value, arbitrary units
    :param mean: Desired mean value
    :param scale: Scale factor for variations - a scale of one means jumps of -1.0 to +1.0 every time step
    :param return_bias: Dimensionless factor - increase this to reduce long-term variation around the mean
    :return: Next value for the sensor reading
    """
    return current_value + scale * 2.0 * ((return_bias * (mean - current_value)) + (random.random() - 0.5))


class SimSMARTbox(smartbox.SMARTbox):
    """
    An instance of this class simulates a single SMARTbox, acting as a Modbus slave and responding to 0x03, 0x06 and
    0x10 Modbus commands to read and write registers.
    """
    def __init__(self, conn=None, modbus_address=None, logger=None):
        # Inherited from the controller code in pasd/smartbox.py
        smartbox.SMARTbox.__init__(self, conn=conn, modbus_address=modbus_address, logger=logger)
        self.mbrv = 1   # Modbus register-map revision number for this physical SMARTbox
        self.pcbrv = 1  # PCB revision number for this physical SMARTbox
        self.register_map = smartbox.SMARTBOX_REGISTERS[1]  # Assume register map version 1
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
        self.statuscode = smartbox.STATUS_UNINITIALISED    # Status value, one of the smartbox.STATUS_* globals, and used as a key for smartbox.STATUS_CODES (eg 0 meaning 'OK')
        self.status = 'UNINITIALISED'       # Status string, obtained from smartbox.STATUS_CODES global (eg 'OK')
        self.service_led = False    # True if the blue service indicator LED is switched ON.
        self.indicator_code = smartbox.LED_GREENFAST  # LED status value, one of the smartbox.LED_* globals, and used as a key for smartbox.LED_CODES
        self.indicator_state = 'GREENFAST'   # LED status string, obtained from smartbox.LED_CODES
        self.readtime = 0    # Unix timestamp for the last successful polled data from this SMARTbox
        self.pdoc_number = None   # Physical PDoC port on the FNDH that this SMARTbox is plugged into. Populated by the station initialisation code on powerup

        # Only in the smartbox simulator class
        self.start_time = time.time()   # Unix timestamp when this instance started processing
        self.initialised = False   # True if the system has been initialised by the LMC
        self.online = False   # Will be True if we've heard from the MCCS in the last 300 seconds.
        self.shortpress = False   # Set to True to simulate a short button press (cleared when it's handled)
        self.mediumpress = False  # Set to True to simulate a medium button press (cleared when it's handled)
        self.longpress = False    # Set to True to simulate a long button press (never cleared)
        self.wants_exit = False  # Set to True externally to kill self.mainloop if the box is pseudo-powered-off
        # Sensor states, with four thresholds for hysteris (alarm high, warning high, warning low, alarm low)
        # Each has three possible values (OK, WARNING or RECOVERY)
        self.sensor_states = {regname:'OK' for regname in self.register_map['CONF'] if not regname.endswith('_CURRENT_TH')}
        # Port current states, with only one (high) threshold, and fault handling internally. Can only be OK or ALARM
        self.portcurrent_states = {regname:'OK' for regname in self.register_map['CONF'] if regname.endswith('_CURRENT_TH')}

    def __str__(self):
        return STATUS_STRING % (self.__dict__) + "\nPorts:\n" + ("\n".join([str(self.ports[pnum]) for pnum in range(1, 13)]))

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

        Don't do anything that takes a long time in here - this is called in the packet handler thread.

        :return: None
        """
        pass

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

        Note that we traverse around the loop whenever we process an incoming packet, or when waiting for a packet
        times out after around a second.

        :return: None
        """
        while not self.wants_exit:  # Process packets until we are told to die
            # Set up the registers for the physical->smartbox/port mapping:
            slave_registers = {}
            self.uptime = int(time.time() - self.start_time)  # Set the current uptime value

            # Copy the local simulated instance data to the temporary registers dictionary - first the POLL registers
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

            # Now copy the configuration data to the temporary register dictionary
            for regname in self.register_map['CONF']:
                regnum, numreg, regdesc, scalefunc = self.register_map['CONF'][regname]
                if numreg == 1:
                    slave_registers[regnum] = scalefunc(self.thresholds[regname], pcb_version=self.pcbrv, reverse=True)
                elif numreg == 4:
                    (slave_registers[regnum],
                     slave_registers[regnum + 1],
                     slave_registers[regnum + 2],
                     slave_registers[regnum + 3]) = (scalefunc(x, pcb_version=self.pcbrv, reverse=True) for x in self.thresholds[regname])
                else:
                    self.logger.critical('Unexpected number of registers for %s' % regname)

            # Wait up to one second for an incoming packet. On return, we get a set of registers numbers that were
            # read by that packet, and a set of register numbers that were written to by that packet. The
            # temporary slave_registers dictionary has new values for each register in the written_set.
            try:
                read_set, written_set = self.conn.listen_for_packet(listen_address=self.modbus_address,
                                                                    slave_registers=slave_registers,
                                                                    maxtime=1,
                                                                    validation_function=None)
            except:
                self.logger.exception('Exception in transport.listen_for_packet():')
                time.sleep(1)
                continue

            if read_set or written_set:  # The MCCS has talked to us, update the self.readtime timestamp
                self.readtime = time.time()

            # If any registers have been written to, update the local instance attributes from the new values
            if written_set:
                self.handle_register_writes(slave_registers, written_set)

            # Update the on/off state of all the ports, based on local instance attributes
            goodcodes = [smartbox.STATUS_OK, smartbox.STATUS_WARNING]
            if (self.statuscode not in goodcodes):   # If we're not OK or WARNING disable all the outputs
                for port in self.ports.values():
                    port.status_timestamp = time.time()
                    port.current_timestamp = port.status_timestamp
                    port.system_level_enabled = False
                    port.power_state = False
            else:  # Otherwise, set the output state based on online/offline status and the four desired_state bits
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
                        port.current = 2048.0
                    port.power_state = port_on

            self.loophook()

        self.logger.info('Ending listen_loop() in SimSMARTbox')

    def handle_register_writes(self, slave_registers, written_set):
        """
        Take the modified temporary slave_registers dictionary, and the set of register numbers that were modified by
        the packet, and update the local instance attributes.

        Note that writes to many registers are ignored by the SMARTbox, as the data is read-only, so this function
        only needs to handle changes to registers that are R/W.

        :param slave_registers: Dictionary, with register number as the key and register contents as the value
        :param written_set: A set() of register numbers that were modified by the most revent packet.
        :return: None
        """
        # First handle the port state bitmap registers
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

                if bitstring[8] == '1':  # Reset breaker if 1, ignore if 0
                    port.breaker_tripped = False

        # Now update ay new threshold data from the configuration registers.
        for regname in self.register_map['CONF']:
            regnum, numreg, regdesc, scalefunc = self.register_map['CONF'][regname]
            if regnum in written_set:
                if numreg == 1:
                    self.thresholds[regname] = scalefunc(slave_registers[regnum], pcb_version=self.pcbrv)
                else:
                    self.thresholds[regname] = [scalefunc(slave_registers[x], pcb_version=self.pcbrv) for x in range(regnum, regnum + 4)]

        # Now update the service LED state (data in the LSB is ignored, because the microcontroller handles the
        # status LED).
        if self.register_map['POLL']['SYS_LIGHTS'][0] in written_set:  # Wrote to SYS_LIGHTS, so set light attributes
            msb, lsb = divmod(slave_registers[self.register_map['POLL']['SYS_LIGHTS'][0]], 256)
            self.service_led = bool(msb)

        if self.register_map['POLL']['SYS_STATUS'][0] in written_set:  # Wrote to SYS_STATUS, so clear UNINITIALISED state
            self.initialised = True

    def sim_loop(self):
        """
        Runs continuously, simulating hardware processes independent of the communications packet handler.

        Starts the Modbus communications handler (receiving and processing packets) in a different thread, so simulation
        actions don't hold up packet handling.

        :return: None
        """
        self.start_time = time.time()

        self.logger.info('Started comms thread for SMARTbox')
        listen_thread = threading.Thread(target=self.listen_loop, daemon=False, name=threading.current_thread().name + '-C')
        listen_thread.start()

        self.statuscode = smartbox.STATUS_UNINITIALISED
        self.status = 'UNINITIALISED'
        self.indicator_code = smartbox.LED_YELLOWFAST  # Fast flash green - uninitialised
        self.indicator_state = 'YELLOWFAST'

        self.logger.info('Started simulation loop for SMARTbox')
        while not self.wants_exit:  # Process packets until we are told to die
            self.uptime = int(time.time() - self.start_time)  # Set the current uptime value

            # Update the online/offline state, depending on how long it's been since the MCCS last sent a packet to us
            # Note that the port powerup/powerdown as a result of online/offline transitions is handled in the listen_loop
            if (time.time() - self.readtime >= 300) and self.online:   # More than 5 minutes since we heard from MCCS, go offline
                self.online = False
                for port in self.ports.values():
                    port.system_online = False
            elif (time.time() - self.readtime < 300) and (not self.online):   # Less than 5 minutes since we heard from MCCS, go online
                self.online = True
                for port in self.ports.values():
                    port.system_online = True

            time.sleep(0.5)

            # Change the sensor values to generate a random walk around a mean value for each sensor
            self.incoming_voltage = random_walk(self.incoming_voltage, 46.1, scale=0.2)
            self.psu_voltage = random_walk(self.psu_voltage, 5.1, scale=0.05)
            self.psu_temp = random_walk(self.psu_temp, 28.3, scale=0.1)
            self.pcb_temp = random_walk(self.pcb_temp, 27.0, scale=0.1)
            self.outside_temp = random_walk(self.outside_temp, 34.0, scale=0.5)

            if self.initialised:     # Don't bother thresholding sensor values until the thresholds have been set
                # For each threshold register, get the current value and threshold/s from the right local instance attribute
                for regname in self.register_map['CONF']:
                    if regname.endswith('_CURRENT_TH'):
                        curstate = self.portcurrent_states[regname]
                        ah = self.thresholds[regname]
                        wh, wl, al = ah, -1, -2   # Only one threshold for port current, hysteresis handled in firmware
                        curvalue = self.ports[int(regname[1:3])].current
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
                            curvalue = self.sensor_temps[int(regname[9:11])]
                        else:
                            self.logger.critical('Configuration register %s not handled by simulation code')
                            return

                    # Now use the current value and threshold/s to find the new state for that sensor
                    newstate = curstate
                    if curvalue > ah:
                        if curstate != 'ALARM':
                            newstate = 'ALARM'
                    elif wh < curvalue <= ah:
                        if curstate == 'ALARM':
                            newstate = 'RECOVERY'
                        elif curstate != 'RECOVERY':
                            newstate = 'WARNING'
                    elif wl <= curvalue <= wh:
                        newstate = 'OK'
                    elif al <= curvalue < wl:
                        if curstate == 'ALARM':
                            newstate = 'RECOVERY'
                        elif curstate != 'RECOVERY':
                            newstate = 'WARNING'
                    elif curvalue < al:
                        newstate = 'ALARM'

                    # Log any change in state
                    if curstate != newstate:
                        msg = 'Sensor %s transitioned from %s to %s with reading of %4.2f and thresholds of %3.1f,%3.1f,%3.1f,%3.1f'
                        self.logger.warning(msg % (regname[:-3],
                                                   curstate,
                                                   newstate,
                                                   curvalue,
                                                   ah,wh,wl,al))

                    # Record the new state for that sensor in a dictionary with all sensor states
                    if regname.endswith('_CURRENT_TH'):
                        self.portcurrent_states[regname] = newstate
                    else:
                        self.sensor_states[regname] = newstate

            if self.shortpress:   # Unhandled short button press - reset any faults and technician overrides, try again
                self.logger.info('Short button press detected.')
                # Change any 'RECOVERY' sensor states to WARNING
                for regname, value in self.portcurrent_states.items():
                    if value == 'RECOVERY':
                        self.portcurrent_states[regname] = 'WARNING'
                for regname, value in self.sensor_states.items():
                    if value == 'RECOVERY':
                        self.sensor_states[regname] = 'WARNING'

                # Clear any port locally_forced_* bits
                # And reset any tripped software breakers
                for p in self.ports.values():
                    p.locally_forced_on = False
                    p.locally_forced_off = False
                    p.breaker_tripped = False

                self.shortpress = False   # Handled, so clear the flag

            if self.mediumpress:
                self.logger.info('Medium button press detected.')
                # Force all the FEM ports off
                for p in self.ports.values():
                    p.locally_forced_on = False
                    p.locally_forced_off = True
                self.mediumpress = False

            if self.longpress:
                if self.statuscode != smartbox.STATUS_POWERDOWN:
                    self.logger.info('Long button press detected.')   # Only log this once, not every loop
                # Ask for a shutdown
                # Force all the FEM ports off
                for p in self.ports.values():
                    p.locally_forced_on = False
                    p.locally_forced_off = True
                self.statuscode = smartbox.STATUS_POWERDOWN
                self.indicator_code = smartbox.LED_GREENRED
                self.indicator_state = 'GREENRED'
                continue

            # Now update the overall box state, based on all of the sensor states
            if self.initialised:
                if 'ALARM' in self.sensor_states.values():  # If any sensor is in ALARM, so is thw whole box
                    self.statuscode = smartbox.STATUS_ALARM
                    if self.online:
                        self.indicator_code = smartbox.LED_REDSLOW
                    else:
                        self.indicator_code = smartbox.LED_RED
                elif 'RECOVERY' in self.sensor_states.values():  # Otherwise, if any sensor is RECOVERY, so is the whole box
                    self.statuscode = smartbox.STATUS_RECOVERY
                    if self.online:
                        self.indicator_code = smartbox.LED_YELLOWREDSLOW
                    else:
                        self.indicator_code = smartbox.LED_YELLOWRED
                elif 'WARNING' in self.sensor_states.values():  # Otherwise, if any sensor is WARNING, so is the whole box
                    self.statuscode = smartbox.STATUS_WARNING
                    if self.online:
                        self.indicator_code = smartbox.LED_YELLOWSLOW
                    else:
                        self.indicator_code = smartbox.LED_YELLOW
                else:
                    self.statuscode = smartbox.STATUS_OK  # If all sensors are OK, so is the whole box
                    if self.online:
                        self.indicator_code = smartbox.LED_GREENSLOW
                    else:
                        self.indicator_code = smartbox.LED_GREEN
            else:
                self.statuscode = smartbox.STATUS_UNINITIALISED
                self.indicator_code = smartbox.LED_YELLOWFAST  # Fast flash green - uninitialised

            self.status = smartbox.STATUS_CODES[self.statuscode]
            self.indicator_state = smartbox.LED_CODES[self.indicator_code]

        self.logger.info('Ending sim_loop() in SimSMARTbox')


"""
Use as 'simulate.py smartbox', or:

from pasd import transport
from simulate import sim_smartbox
conn = transport.Connection(hostname='134.7.50.185')  # address of ethernet-serial bridge
# or
conn = transport.Connection(devicename='/dev/ttyS0')  # or 'COM5' for example, under Windows

s = sim_smartbox.SimSMARTbox(conn=conn, modbus_address=1)
s.sim_loop()
"""
