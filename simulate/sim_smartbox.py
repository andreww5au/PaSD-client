#!/usr/bin/env python

"""
Simulates a SMARTbox, acting as a Modbus slave and responding to 0x03, 0x06 and 0x10 Modbus commands
to read and write registers.
"""

import time

from pasd import smartbox


class SimSMARTbox(smartbox.SMARTbox):
    """
    An instance of this class simulates a single SMARTbox, acting as a Modbus slave and responding to 0x03, 0x06 and
    0x10 Modbus commands to read and write registers.
    """
    def __init__(self, conn=None, modbus_address=None):
        smartbox.SMARTbox.__init__(self, conn=conn, modbus_address=modbus_address)
        self.online = False   # Will be True if we've heard from the MCCS in the last 300 seconds.
        self.register_map = smartbox.SMARTBOX_REGISTERS[1]  # Assume register map version 1
        self.codes = smartbox.SMARTBOX_CODES[1]
        self.mbrv = 1   # Modbus register-map revision number for this physical SMARTbox
        self.pcbrv = 1  # PCB revision number for this physical SMARTbox
        self.codes = {}    # A dictionary mapping status code integer (eg 0) to status code string (eg 'OK'), and LED codes to LED flash states
        self.fem_temps = {i:1500 for i in range(1, 13)}  # Dictionary with FEM number (1-12) as key, and temperature as value
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
        self.statuscode = 4    # Status value, used as a key for self.codes['status'] (eg 0 meaning 'OK')
        self.status = 'UNINITIALISED'       # Status string, obtained from self.codes['status'] (eg 'OK')
        self.service_led = False    # True if the blue service indicator LED is switched ON.
        self.indicator_code = 0  # LED status value, used as a key for self.codes['led']
        self.indicator_state = 'OFF'   # LED status, obtained from self.codes['led']
        self.readtime = 0    # Unix timestamp for the last successful polled data from this SMARTbox
        self.pdoc_number = None   # Physical PDoC port on the FNDH that this SMARTbox is plugged into. Populated by the station initialisation code on powerup
        self.wants_exit = False  # Set to True externally to kill self.mainloop if the box is pseudo-powered-off

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

    def mainloop(self):
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

        :return: None
        """
        start_time = time.time()
        while not self.wants_exit:  # Process packets until we are told to die
            # Set up the registers for the physical->smartbox/port mapping:
            slave_registers = {}
            self.uptime = int(time.time() - start_time)  # Set the current uptime value

            for regname in self.register_map['POLL']:
                regnum, numreg, regdesc, scalefunc = self.register_map['POLL'][regname]
                if regname == 'SYS_CPUID':
                    slave_registers[regnum] = self.cpuid
                elif regname == 'SYS_CHIPID':
                    for i in range(numreg):
                        slave_registers[regnum + i] = self.chipid[i // 2] * 256 + self.chipid[i // 2 + 1]
                elif regname == 'SYS_FIRMVER':
                    slave_registers[regnum] = self.firmware_version
                elif regname == 'SYS_UPTIME':
                    slave_registers[regnum] = self.uptime
                elif regname == 'SYS_ADDRESS':
                    slave_registers[regnum] = self.station_value
                elif regname == 'SYS_48V_V':
                    slave_registers[regnum] = 4096 * self.incoming_voltage / 100.0
                elif regname == 'SYS_PSU_V':
                    slave_registers[regnum] = 4096 * self.psu_voltage / 10.0
                elif regname == 'SYS_PSUTEMP':
                    slave_registers[regnum] = 4096 * (self.psu_temp + 10) / 150.0
                elif regname == 'SYS_PCBTEMP':
                    slave_registers[regnum] = 4096 * (self.pcb_temp + 10) / 150.0
                elif regname == 'SYS_OUTTEMP':
                    slave_registers[regnum] = 4096 * (self.outside_temp + 10) / 150.0
                elif regname == 'SYS_STATUS':
                    slave_registers[regnum] = self.statuscode
                elif regname == 'SYS_LIGHTS':
                    slave_registers[regnum] = int(self.service_led) * 256 + self.indicator_code
                elif (len(regname) >= 12) and ((regname[:7] + regname[-4:]) == 'SYS_FEMTEMP'):
                    fem_num = int(regname[7:-4])
                    slave_registers[regnum] = 4096 * (self.fem_temps[fem_num] + 10) / 150.0
                elif (len(regname) >= 8) and ((regname[0] + regname[-6:]) == 'P_STATE'):
                    pnum = int(regname[1:-6])
                    slave_registers[regnum] = self.ports[pnum].status_to_integer(write_state=True, write_to=True)
                elif (len(regname) >= 10) and ((regname[0] + regname[-8:]) == 'P_CURRENT'):
                    pnum = int(regname[1:-8])
                    slave_registers[regnum] = self.ports[pnum].current_raw

            for regnum in range(1001, 1078):   # Zero all the threshold registers
                slave_registers[regnum] = 0

            read_set, written_set = self.conn.listen_for_packet(listen_address=self.modbus_address,
                                                                slave_registers=slave_registers,
                                                                maxtime=5.0,
                                                                validation_function=None)

            if read_set or written_set:  # The MCCS has talked to us, update the last_readtime timestamp
                self.readtime = time.time()

            if (time.time() - self.readtime >= 300) and self.online:   # More than 5 minutes since we heard from MCCS, go offline
                self.online = False
                for port in self.ports.values():
                    port.system_online = False
            elif (time.time() - self.readtime < 300) and (not self.online):   # Less than 5 minutes since we heard from MCCS, go online
                self.online = True
                for port in self.ports.values():
                    port.system_online = True

            if self.register_map['POLL']['SYS_STATUS'][0] in written_set:   # Wrote to SYS_STATUS, so clear UNINITIALISED state
                self.statuscode = 0
                self.status = self.codes['status'][0]

            if (self.status not in [0, 1]):   # If we're not OK or WARNING, disable all the outputs
                for port in self.ports.values():
                    port.system_level_enabled = False
                    port.power_state = False
            else:
                for port in self.ports.values():
                    port_on = False
                    if ( (self.online and port.desire_enabled_online) or
                         ((not self.online) and port.desire_enabled_offline) or
                         (port.locally_forced_on)) and (not port.locally_forced_off):
                        port_on = True
                    port.power_state = port_on
