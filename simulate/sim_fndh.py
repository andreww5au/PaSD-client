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


class SimFNDH(fndh.FNDH):
    """
    An instance of this class simulates a single FNDH, acting as a Modbus slave and responding to 0x03, 0x06 and
    0x10 Modbus commands to read and write registers.
    """
    def __init__(self, conn=None, modbus_address=None, logger=None):
        fndh.FNDH.__init__(self, conn=conn, modbus_address=modbus_address, logger=logger)
        self.online = False   # Will be True if we've heard from the MCCS in the last 300 seconds.
        self.register_map = fndh.FNDH_REGISTERS[1]  # Assume register map version 1
        self.codes = fndh.FNDH_CODES[1]
        self.mbrv = 1   # Modbus register-map revision number for this physical FNDH
        self.pcbrv = 1  # PCB revision number for this physical FNDH
        self.fem_temps = {i:1500 for i in range(1, 13)}  # Dictionary with FEM number (1-12) as key, and temperature as value
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
        self.pcb_temp = 38.0    # Temperature on the internal PCB (deg C)
        self.outside_temp = 34.0    # Outside temperature (deg C)
        self.initialised = False   # True if the system has been initialised by the LMC
        self.statuscode = 4    # Status value, used as a key for self.codes['status'] (eg 0 meaning 'OK')
        self.status = 'UNINITIALISED'       # Status string, obtained from self.codes['status'] (eg 'OK')
        self.service_led = False    # True if the blue service indicator LED is switched ON.
        self.indicator_code = 0  # LED status value, used as a key for self.codes['led']
        self.indicator_state = 'OFF'   # LED status, obtained from self.codes['led']
        self.readtime = 0    # Unix timestamp for the last successful polled data from this FNDH
        self.start_time = 0   # Unix timestamp when this instance started processing
        self.wants_exit = False  # Set to True externally to kill self.mainloop if the box is pseudo-powered-off
        self.sensor_states = {regname:'OK' for regname in self.register_map['CONF']}  # OK, WARNING or RECOVERY

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

    def write_portconfig(self):
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
                    slave_registers[regnum] = self.ports[pnum].status_to_integer(write_state=True, write_to=True)

            for regname in self.register_map['CONF']:
                regnum, numreg, regdesc, scalefunc = self.register_map['CONF'][regname]
                (slave_registers[regnum],
                 slave_registers[regnum + 1],
                 slave_registers[regnum + 2],
                 slave_registers[regnum + 3]) = (scalefunc(x, reverse=True) for x in self.thresholds[regname])

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
                    port.power_sense = False
                    if ( ( (self.online and port.desire_enabled_online)
                           or ((not self.online) and port.desire_enabled_offline)
                           or (port.locally_forced_on) )
                         and (not port.locally_forced_off) ):
                        port_on = True
                        port.power_sense = True
                    port.power_state = port_on

            self.loophook()

        self.logger.info('Ending listen_loop() in SimFNDH')

    def sim_loop(self):
        """
        Runs continuously, simulating hardware processes independent of the communications packet handler
        :return:
        """
        self.start_time = time.time()

        self.logger.info('Started comms thread for FNDH')
        listen_thread = threading.Thread(target=self.listen_loop, daemon=False, name=threading.current_thread().name + '-C')
        listen_thread.start()

        self.logger.info('Started simulation loop for fndh')
        while not self.wants_exit:  # Process packets until we are told to die
            self.uptime = int(time.time() - self.start_time)  # Set the current uptime value

            if (time.time() - self.readtime >= 300) and self.online:  # More than 5 minutes since we heard from MCCS, go offline
                self.online = False
                for port in self.ports.values():
                    port.system_online = False
            elif (time.time() - self.readtime < 300) and (not self.online):  # Less than 5 minutes since we heard from MCCS, go online
                self.online = True
                for port in self.ports.values():
                    port.system_online = True

            self.psu48v1_voltage += (48.1 - self.psu48v1_voltage) * 0.1 + (random.random() - 0.5)
            self.psu48v2_voltage += (48.1 - self.psu48v2_voltage) * 0.1 + (random.random() - 0.5)
            self.psu5v_voltage += (5.1 - self.psu5v_voltage) * 0.01 + (random.random() - 0.05)
            self.psu48v_current += (13.4 - self.psu48v_current) * 0.02 + (random.random() - 0.1)
            self.psu48v_temp += (58.3 - self.psu48v_temp) * 0.1 + (random.random() - 0.5)
            self.psu5v_temp += (55.1 - self.psu5v_temp) * 0.1 + (random.random() - 0.5)
            self.pcb_temp += (38.0 - self.pcb_temp) * 0.1 + (random.random() - 0.5)
            self.outside_temp += (34.0 - self.outside_temp) * 0.1 + (random.random() - 0.5)

            # Test current voltage/temp/current values against threshold and update states
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

                newstate = curstate
                if curvalue > ah:
                    newstate = 'ALARM'
                elif wh > curvalue >= ah:
                    if curstate == 'ALARM':
                        newstate = 'RECOVERY'
                    else:
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

            time.sleep(0.5)

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
