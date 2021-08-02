#!/usr/bin/env python

"""
Simulates a FNDH, acting as a Modbus slave and responding to 0x03, 0x06 and 0x10 Modbus commands
to read and write registers. Used for testing PaSD code.
"""

import logging
import random
import threading
import time


logging.basicConfig()

from pasd import fndh

RETURN_BIAS = 0.025

STATUS_STRING = """\
FNDH at address: %(modbus_address)s:
    ModBUS register revision: %(mbrv)s
    PCB revision: %(pcbrv)s
    CPU ID: %(cpuid)s
    CHIP ID: %(chipid)s
    Firmware revision: %(firmware_version)s
    Uptime: %(uptime)s seconds
    R.Address: %(station_value)s
    48V Out 1: %(psu48v1_voltage)4.2f V (%(psu48v1_voltage_state)s)
    48V Out 2: %(psu48v2_voltage)4.2f V (%(psu48v2_voltage_state)s)
    5V out: %(psu5v_voltage)4.2f V (%(psu5v_voltage_state)s)
    48V Current: %(psu48v_current)4.2f A  (%(psu48v_current_state)s)
    48V Temp: %(psu48v_temp)4.2f deg C (%(psu48v_temp_state)s)
    5V Temp: %(psu5v_temp)4.2f deg C (%(psu5v_temp_state)s)
    PCB Temp: %(pcb_temp)4.2f deg C (%(pcb_temp_state)s)
    Outside Temp: %(outside_temp)4.2f deg C (%(outside_temp_state)s)
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
    :param scale: Scale factor for variations
    :param return_bias: Defaults to 0.1, increase this to reduce variation around the mean
    :return: Next value for the sensor reading
    """
    return current_value + scale * 2.0 * ((return_bias * (mean - current_value)) + (random.random() - 0.5))


class SimFNDH(fndh.FNDH):
    """
    An instance of this class simulates a single FNDH, acting as a Modbus slave and responding to 0x03, 0x06 and
    0x10 Modbus commands to read and write registers.
    """
    def __init__(self, conn=None, modbus_address=None, logger=None):
        fndh.FNDH.__init__(self, conn=conn, modbus_address=modbus_address, logger=logger)
        # Inherited from the controller code in pasd/smartbox.py
        self.mbrv = 1   # Modbus register-map revision number for this physical FNDH
        self.pcbrv = 1  # PCB revision number for this physical FNDH
        self.register_map = fndh.FNDH_REGISTERS[1]  # Assume register map version 1
        self.cpuid = 1    # CPU identifier (integer)
        self.chipid = bytes([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16])   # Unique ID number (16 bytes), different for every physical SMARTbox
        self.firmware_version = 1  # Firmware revision mumber for this physical SMARTbox
        self.uptime = 0            # Time in seconds since this FNDH was powered up
        self.station_value = modbus_address     # Modbus address read back from the SYS_ADDRESS register - should always equal modbus_address
        self.psu48v1_voltage = 48.1  # Voltage measured on the output of the first 48VDC power supply (Volts)
        self.psu48v2_voltage = 48.2  # Voltage measured on the output of the second 48VDC power supply (Volts)
        self.psu5v_voltage = 5.1  # Voltage measured on the output of the 5VDC power supply (Volts)
        self.psu48v_current = 13.4  # Total current on the 48VDC bus (Amps)
        self.psu48v_temp = 58.3  # Common temperature for both 48VDC power supplies (deg C)
        self.psu5v_temp = 55.1  # Temperature of the 5VDC power supply (Volts)
        self.pcb_temp = 48.0    # Temperature on the internal PCB (deg C)
        self.outside_temp = 38.0    # Outside temperature (deg C)
        self.statuscode = fndh.STATUS_UNINITIALISED    # Status value, one of the fndh.STATUS_* globals, and used as a key for fndh.STATUS_CODES (eg 0 meaning 'OK')
        self.status = 'UNINITIALISED'       # Status string, obtained from fndh.STATUS_CODES global (eg 'OK')
        self.service_led = False    # True if the blue service indicator LED is switched ON.
        self.indicator_code = fndh.LED_YELLOWFAST  # LED status value, one of the fndh.LED_* globals, and used as a key for fndh.LED_CODES
        self.indicator_state = 'YELLOWFAST'   # LED status string, obtained from fndh.LED_CODES
        self.readtime = 0    # Unix timestamp for the last successful polled data from this FNDH

        # Only in the FNDH simulator class
        self.start_time = 0   # Unix timestamp when this instance started processing
        self.wants_exit = False  # Set to True externally to kill self.mainloop if the box is pseudo-powered-off
        self.sensor_states = {regname:'UNINITIALISED' for regname in self.register_map['CONF']}  # OK, WARNING or RECOVERY
        self.online = False   # Will be True if we've heard from the MCCS in the last 300 seconds.
        self.initialised = False   # True if the system has been initialised by the LMC
        self.shortpress = False   # Set to True to simulate a short button press (cleared when it's handled)
        self.mediumpress = False  # Set to True to simulate a medium button press (cleared when it's handled)
        self.longpress = False    # Set to True to simulate a long button press (never cleared)

    def __str__(self):
        tmpdict = self.__dict__.copy()
        tmpdict['psu48v1_voltage_state'] = self.sensor_states['SYS_48V1_V_TH']
        tmpdict['psu48v2_voltage_state'] = self.sensor_states['SYS_48V2_V_TH']
        tmpdict['psu5v_voltage_state'] = self.sensor_states['SYS_5V_V_TH']
        tmpdict['psu48v_current_state'] = self.sensor_states['SYS_48V_I_TH']
        tmpdict['psu48v_temp_state'] = self.sensor_states['SYS_48V_TEMP_TH']
        tmpdict['psu5v_temp_state'] = self.sensor_states['SYS_5V_TEMP_TH']
        tmpdict['pcb_temp_state'] = self.sensor_states['SYS_PCBTEMP_TH']
        tmpdict['outside_temp_state'] = self.sensor_states['SYS_OUTTEMP_TH']
        return STATUS_STRING % (tmpdict) + "\nPorts:\n" + ("\n".join([str(self.ports[pnum]) for pnum in range(1, 29)]))

    def poll_data(self):
        """
        Stub, not needed for simulated FNDH
        """
        pass

    def read_uptime(self):
        """
        Stub, not needed for simulated FNDH
        """
        pass

    def write_thresholds(self):
        """
        Stub, not needed for simulated FNDH
        """
        pass

    def write_portconfig(self, write_state=True, write_to=False, write_breaker=False):
        """
        Stub, not needed for simulated FNDH
        """
        pass

    def configure(self, thresholds=None, portconfig=None):
        """
        Stub, not needed for simulated FNDH
        """
        pass

    def loophook(self):
        """
        Stub, overwrite if you subclass this to handle more complex simulation. Called every time a packet has
        finished processing, or every few seconds if there haven't been any packets.

        Don't do anything that takes a long time in here - this is called in the packet handler thread.

        :return: None
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
                elif regname == 'SYS_48V1_V':
                    slave_registers[regnum] = scalefunc(self.psu48v1_voltage, reverse=True, pcb_version=self.pcbrv)
                elif regname == 'SYS_48V2_V':
                    slave_registers[regnum] = scalefunc(self.psu48v2_voltage, reverse=True, pcb_version=self.pcbrv)
                elif regname == 'SYS_5V_V':
                    slave_registers[regnum] = scalefunc(self.psu5v_voltage, reverse=True, pcb_version=self.pcbrv)
                elif regname == 'SYS_48V_I':
                    slave_registers[regnum] = scalefunc(self.psu48v_current, reverse=True, pcb_version=self.pcbrv)
                elif regname == 'SYS_48V_TEMP':
                    slave_registers[regnum] = scalefunc(self.psu48v_temp, reverse=True, pcb_version=self.pcbrv)
                elif regname == 'SYS_5V_TEMP':
                    slave_registers[regnum] = scalefunc(self.psu5v_temp, reverse=True, pcb_version=self.pcbrv)
                elif regname == 'SYS_PCBTEMP':
                    slave_registers[regnum] = scalefunc(self.pcb_temp, reverse=True, pcb_version=self.pcbrv)
                elif regname == 'SYS_OUTTEMP':
                    slave_registers[regnum] = scalefunc(self.outside_temp, reverse=True, pcb_version=self.pcbrv)
                elif regname == 'SYS_STATUS':
                    slave_registers[regnum] = self.statuscode
                elif regname == 'SYS_LIGHTS':
                    slave_registers[regnum] = int(self.service_led) * 256 + self.indicator_code
                elif (len(regname) >= 8) and ((regname[0] + regname[-6:]) == 'P_STATE'):
                    pnum = int(regname[1:-6])
                    slave_registers[regnum] = self.ports[pnum].status_to_integer(write_state=True,
                                                                                 write_to=True,
                                                                                 write_breaker=self.ports[pnum].power_sense)

            # Now copy the configuration data to the temporary register dictionary
            for regname in self.register_map['CONF']:
                regnum, numreg, regdesc, scalefunc = self.register_map['CONF'][regname]
                if numreg == 1:
                    slave_registers[regnum] = scalefunc(self.thresholds[regname], reverse=True)
                else:
                    (slave_registers[regnum],
                     slave_registers[regnum + 1],
                     slave_registers[regnum + 2],
                     slave_registers[regnum + 3]) = (scalefunc(x, pcb_version=self.pcbrv, reverse=True) for x in self.thresholds[regname])

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

            if read_set or written_set:  # The MCCS has talked to us, update the last_readtime timestamp
                self.readtime = time.time()

            # If any registers have been written to, update the local instance attributes from the new values
            if written_set:
                self.handle_register_writes(slave_registers, written_set)

            # Update the on/off state of all the ports, based on local instance attributes
            goodcodes = [fndh.STATUS_OK, fndh.STATUS_WARNING]
            if (self.statuscode not in goodcodes):  # If we're not OK or WARNING disable all the outputs
                for port in self.ports.values():
                    port.status_timestamp = time.time()
                    port.current_timestamp = port.status_timestamp
                    port.system_level_enabled = False
                    port.system_online = self.online
                    port.power_state = False
                    port.power_sense = False
            else:  # Otherwise, set the output state based on online/offline status and the four desired_state bits
                for port in self.ports.values():
                    port.status_timestamp = time.time()
                    port.current_timestamp = port.status_timestamp
                    port.system_level_enabled = True
                    port.system_online = self.online
                    port_on = False
                    if ( ( (self.online and port.desire_enabled_online)
                           or ((not self.online) and port.desire_enabled_offline)
                           or (port.locally_forced_on) )
                         and (not port.locally_forced_off) ):
                        port_on = True

                    port.power_state = port_on
                    port.power_sense = port_on

            self.loophook()

        self.loophook()   # Guarantee we run this at least once if self.wants_exit becomes True
        self.logger.info('Ending listen_loop() in SimFNDH')

    def handle_register_writes(self, slave_registers, written_set):
        """
        Take the modified temporary slave_registers dictionary, and the set of register numbers that were modified by
        the packet, and update the local instance attributes.

        Note that writes to many registers are ignored by the FNDH, as the data is read-only, so this function
        only needs to handle changes to registers that are R/W.

        :param slave_registers: Dictionary, with register number as the key and register contents as the value
        :param written_set: A set() of register numbers that were modified by the most revent packet.
        :return: None
        """
        # First handle the port state bitmap registers
        for regnum in range(self.register_map['POLL']['P01_STATE'][0], self.register_map['POLL']['P28_STATE'][0] + 1):
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
            self.longpress = False    # Clear the 'long button press' flag, because the restart process is happening

    def sim_loop(self):
        """
        Runs continuously, simulating hardware processes independent of the communications packet handler

        Starts the Modbus communications handler (receiving and processing packets) in a different thread, so simulation
        actions don't hold up packet handling.

        :return: None
        """
        self.start_time = time.time()

        self.statuscode = fndh.STATUS_UNINITIALISED
        self.status = 'UNINITIALISED'
        self.indicator_code = fndh.LED_YELLOWFAST  # Fast flash green - uninitialised
        self.indicator_state = 'YELLOWFAST'

        self.logger.info('Started comms thread for FNDH')
        listen_thread = threading.Thread(target=self.listen_loop, daemon=False, name=threading.current_thread().name + '-C')
        listen_thread.start()

        self.logger.info('Started simulation loop for FNDH')
        while not self.wants_exit:  # Process packets until we are told to die
            self.uptime = int(time.time() - self.start_time)  # Set the current uptime value

            # Update the online/offline state, depending on how long it's been since the MCCS last sent a packet to us
            # Note that the port powerup/powerdown as a result of online/offline transitions is handled in the listen_loop
            if (time.time() - self.readtime >= 300) and self.online:  # More than 5 minutes since we heard from MCCS, go offline
                self.online = False
                for port in self.ports.values():
                    port.system_online = False
            elif (time.time() - self.readtime < 300) and (not self.online):  # Less than 5 minutes since we heard from MCCS, go online
                self.online = True
                for port in self.ports.values():
                    port.system_online = True

            time.sleep(0.5)

            # Change the sensor values to generate a random walk around a mean value for each sensor
            self.psu48v1_voltage = random_walk(self.psu48v1_voltage, 48.1, scale=0.025)
            self.psu48v2_voltage = random_walk(self.psu48v2_voltage, 48.1, scale=0.025)
            self.psu5v_voltage = random_walk(self.psu5v_voltage, 5.1, scale=0.005)
            self.psu48v_current = random_walk(self.psu48v_current, 13.4, scale=0.015)
            self.psu48v_temp = random_walk(self.psu48v_temp, 58.3, scale=0.025)
            self.psu5v_temp = random_walk(self.psu5v_temp, 55.1, scale=0.025)
            self.pcb_temp = random_walk(self.pcb_temp, 48.1, scale=0.025)
            self.outside_temp = random_walk(self.outside_temp, 38.1, scale=0.025)

            if self.initialised:     # Don't bother thresholding sensor values until the thresholds have been set
                # For each threshold register, get the current value and threshold/s from the right local instance attribute
                for regname in self.register_map['CONF']:
                    ah, wh, wl, al = self.thresholds[regname]
                    curstate = self.sensor_states[regname]
                    if regname == 'SYS_48V1_V_TH':
                        curvalue = self.psu48v1_voltage
                    elif regname == 'SYS_48V2_V_TH':
                        curvalue = self.psu48v2_voltage
                    elif regname == 'SYS_5V_V_TH':
                        curvalue = self.psu5v_voltage
                    elif regname == 'SYS_48V_I_TH':
                        curvalue = self.psu48v_current
                    elif regname == 'SYS_48V_TEMP_TH':
                        curvalue = self.psu48v_temp
                    elif regname == 'SYS_5V_TEMP_TH':
                        curvalue = self.psu5v_temp
                    elif regname == 'SYS_PCBTEMP_TH':
                        curvalue = self.pcb_temp
                    elif regname == 'SYS_OUTTEMP_TH':
                        curvalue = self.outside_temp
                    else:
                        self.logger.critical('Configuration register %s not handled by simulation code')
                        return

                    # Now use the current value and threshold/s to find the new state for that sensor
                    newstate = curstate
                    if curvalue > ah:
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
                        msg = 'Sensor %s transitioned from %s to %s with reading of %4.2f and thresholds of %3.1f, %3.1f, %3.1f, %3.1f'
                        self.logger.warning(msg % (regname[:-3],
                                                   curstate,
                                                   newstate,
                                                   curvalue,
                                                   ah,wh,wl,al))

                    # Record the new state for that sensor in a dictionary with all sensor states
                    self.sensor_states[regname] = newstate

            if self.shortpress:   # Unhandled short button press - reset any faults and technician overrides, try again
                # Change any 'RECOVERY' sensor states to WARNING
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
                # Force all the FEM ports off
                for p in self.ports.values():
                    p.locally_forced_on = False
                    p.locally_forced_off = True
                self.mediumpress = False

            if self.longpress:
                # Ask for a restart (all ports off, then on again every 10 seconds to map smartboxes to PDoC ports)
                # Force all the FEM ports off  - TODO - this must only be one port to be compliant, so we need to maintain
                # our mapping of modbus address to PDoC port over individual port outages
                for p in self.ports.values():
                    p.locally_forced_on = False
                    p.locally_forced_off = True
                self.statuscode = fndh.STATUS_POWERUP
                self.indicator_code = fndh.LED_GREENRED
                self.indicator_state = 'GREENRED'
                continue

            # Now update the overall box state, based on all of the sensor states
            if self.initialised:
                if 'ALARM' in self.sensor_states.values():  # If any sensor is in ALARM, so is thw whole box
                    self.statuscode = fndh.STATUS_ALARM
                    if self.online:
                        self.indicator_code = fndh.LED_REDSLOW
                    else:
                        self.indicator_code = fndh.LED_RED
                elif 'RECOVERY' in self.sensor_states.values():  # Otherwise, if any sensor is RECOVERY, so is the whole box
                    self.statuscode = fndh.STATUS_RECOVERY
                    if self.online:
                        self.indicator_code = fndh.LED_YELLOWREDSLOW
                    else:
                        self.indicator_code = fndh.LED_YELLOWRED
                elif 'WARNING' in self.sensor_states.values():  # Otherwise, if any sensor is WARNING, so is the whole box
                    self.statuscode = fndh.STATUS_WARNING
                    if self.online:
                        self.indicator_code = fndh.LED_YELLOWSLOW
                    else:
                        self.indicator_code = fndh.LED_YELLOW
                else:
                    self.statuscode = fndh.STATUS_OK  # If all sensors are OK, so is the whole box
                    if self.online:
                        self.indicator_code = fndh.LED_GREENSLOW
                    else:
                        self.indicator_code = fndh.LED_GREEN
            else:
                self.statuscode = fndh.STATUS_UNINITIALISED
                self.indicator_code = fndh.LED_YELLOWFAST  # Fast flash green - uninitialised

            self.status = fndh.STATUS_CODES[self.statuscode]
            self.indicator_state = fndh.LED_CODES[self.indicator_code]

        self.logger.info('Ending sim_loop() in SimFNDH')


"""
Use as 'simulate.py fndh', or:

from pasd import transport
from simulate import sim_fndh
conn = transport.Connection(hostname='134.7.50.185')  # address of ethernet-serial bridge
# or
conn = transport.Connection(devicename='/dev/ttyS0')  # or 'COM5' for example, under Windows

f = sim_fndh.SimFNDH(conn=conn, modbus_address=31)
f.sim_loop()
"""
