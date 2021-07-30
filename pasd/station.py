#!/usr/bin/env python

"""Classes to handle PaSD communications with an SKA-Low station, 256 of which make
   up the whole of SKA-Low.

   This code runs on the MCCS side in the control building, and talks to an FNDH and up to 28 SMARTbox modules in the field.
"""

import logging
import time

logging.basicConfig()

from pasd import fndh
from pasd import smartbox

SLAVE_MODBUS_ADDRESS = 63   # Address that technician's SID devices use to reach the MCCS as a slave device
FNDH_ADDRESS = 31   # Modbus address of the FNDH controller

# Initial mapping between SMARTbox/port and antenna number
# Here as a dict to show the concept, in reality this would be in a database.
ANTENNA_MAP = {
 1: {1: None, 2: 1, 3: 2, 4: 3, 5: None, 6: 4, 7: 5, 8: 6, 9: 7, 10: 8, 11: 9, 12: 10},
 2: {1: 11, 2: 12, 3: 13, 4: 14, 5: 15, 6: None, 7: 16, 8: 17, 9: 18, 10: 19, 11: 20, 12: 21},
 3: {1: 22, 2: 23, 3: 24, 4: 25, 5: 26, 6: 27, 7: 28, 8: 29, 9: 30, 10: 31, 11: 32, 12: 33},
 4: {1: 34, 2: 35, 3: 36, 4: 37, 5: 38, 6: 39, 7: 40, 8: 41, 9: 42, 10: 43, 11: 44, 12: None},
 5: {1: 45, 2: 46, 3: 47, 4: 48, 5: None, 6: None, 7: 49, 8: 50, 9: None, 10: 51, 11: 52, 12: 53},
 6: {1: 54, 2: 55, 3: 56, 4: 57, 5: 58, 6: 59, 7: 60, 8: 61, 9: 62, 10: 63, 11: 64, 12: 65},
 7: {1: 66, 2: 67, 3: 68, 4: None, 5: 69, 6: 70, 7: None, 8: 71, 9: 72, 10: 73, 11: 74, 12: 75},
 8: {1: 76, 2: 77, 3: 78, 4: 79, 5: 80, 6: 81, 7: 82, 8: 83, 9: 84, 10: 85, 11: 86, 12: 87},
 9: {1: 88, 2: 89, 3: 90, 4: 91, 5: 92, 6: 93, 7: 94, 8: 95, 9: 96, 10: 97, 11: 98, 12: 99},
 10: {1: 100, 2: 101, 3: 102, 4: 103, 5: 104, 6: 105, 7: 106, 8: 107, 9: 108, 10: 109, 11: 110, 12: 111},
 11: {1: 112, 2: 113, 3: 114, 4: 115, 5: 116, 6: 117, 7: 118, 8: 119, 9: 120, 10: 121, 11: None, 12: 122},
 12: {1: 123, 2: 124, 3: 125, 4: 126, 5: 127, 6: 128, 7: 129, 8: None, 9: 130, 10: 131, 11: 132, 12: 133},
 13: {1: 134, 2: 135, 3: 136, 4: 137, 5: 138, 6: 139, 7: 140, 8: 141, 9: None, 10: 142, 11: 143, 12: 144},
 14: {1: 145, 2: 146, 3: None, 4: 147, 5: 148, 6: 149, 7: 150, 8: 151, 9: 152, 10: 153, 11: 154, 12: 155},
 15: {1: 156, 2: 157, 3: 158, 4: 159, 5: 160, 6: 161, 7: 162, 8: 163, 9: 164, 10: 165, 11: 166, 12: 167},
 16: {1: 168, 2: None, 3: 169, 4: 170, 5: 171, 6: 172, 7: 173, 8: 174, 9: 175, 10: 176, 11: 177, 12: 178},
 17: {1: 179, 2: 180, 3: 181, 4: 182, 5: 183, 6: 184, 7: 185, 8: 186, 9: 187, 10: 188, 11: 189, 12: 190},
 18: {1: 191, 2: None, 3: 192, 4: 193, 5: 194, 6: 195, 7: 196, 8: 197, 9: 198, 10: 199, 11: 200, 12: 201},
 19: {1: 202, 2: 203, 3: 204, 4: 205, 5: None, 6: 206, 7: 207, 8: 208, 9: 209, 10: 210, 11: None, 12: 211},
 20: {1: 212, 2: None, 3: 213, 4: 214, 5: 215, 6: 216, 7: 217, 8: 218, 9: 219, 10: 220, 11: 221, 12: 222},
 21: {1: 223, 2: None, 3: 224, 4: 225, 5: 226, 6: 227, 7: 228, 8: 229, 9: 230, 10: 231, 11: 232, 12: 233},
 22: {1: 234, 2: 235, 3: 236, 4: 237, 5: 238, 6: 239, 7: 240, 8: 241, 9: 242, 10: 243, 11: 244, 12: 245},
 23: {1: 246, 2: 247, 3: 248, 4: 249, 5: 250, 6: 251, 7: 252, 8: 253, 9: 254, 10: 255, 11: 256, 12: None},
 24: {1:None, 2:None, 3:None, 4:None, 5:None, 6:None, 7:None, 8:None, 9:None, 10:None, 11:None, 12:None},
 25: {1:None, 2:None, 3:None, 4:None, 5:None, 6:None, 7:None, 8:None, 9:None, 10:None, 11:None, 12:None},
 26: {1:None, 2:None, 3:None, 4:None, 5:None, 6:None, 7:None, 8:None, 9:None, 10:None, 11:None, 12:None},
 27: {1:None, 2:None, 3:None, 4:None, 5:None, 6:None, 7:None, 8:None, 9:None, 10:None, 11:None, 12:None},
 28: {1:None, 2:None, 3:None, 4:None, 5:None, 6:None, 7:None, 8:None, 9:None, 10:None, 11:None, 12:None}
}

# Register numbers for when the MCCS is acting as a Modbus slave)
PHYSANT_REGSTART = 0  # One register for each physical antenna, eg 1-256
ANTNUM = 1001   # register holding physical antenna number for service log, R/W.
CHIPID = 1002   # register holding chip ID for service log, R/W.
LOGNUM = 1010   # register holding log entry number (0 is most recent) for service log, R/W.
MESSAGE = 1011   # registers holding Log message text, up to 245 characters (including a null terminator) in up to 123 registers, R/W.
PDOC_REGSTART = 1200  # One register for each PDoC (1-28), eg 1201-1228

# Number of registers of log message block (max of 125 due to Modbus packet length limit),
# where the last two registers are the 4-byte unix timestamp for when the message was logged.
MESSAGE_LEN = 125


class Station(object):
    """
    Class representing an SKA-Low station - an instance of this class controls the PaSD for a single station.

    It acts as a Modbus master for a few seconds every few minutes, polling telemetry data from the SMARTboxes and
    FNDH that make up the station. For the rest of the time, it acts as a Modbus slave, waiting for incoming packets
    a technician's Service Interface Device. These could be for changes to the physical antenna mapping, or to read
    or write short service log entries referring to the FNDH, a SMARTBox, or the station as a whole.

    Constant attributes (don't change after initialisation):
        hostname: The DNS name (or IP address as a string) for the ethernet-serial bridge in the FNDH for this station
        port: The port number for the ethernet-serial bridge server, for TCP connections or as a UDP packet destination
        conn: An instance of transport.Connection() connected to self.port on self.hostname

    Attributes that define the mapping between physical antenna number and which SMARTbox/port they are connected to:
        antennae: A dict with physical antenna number (1-256) as key, and smartbox.PortStatus() instances as value
        smartboxes: A dict with smartbox address (1-30) as key, and smartbox.SMARTbox() instances as value

    Attributes used to mediate requests to read and write service log entries for a SMARTbox, antenna, or station.
        servicelog_desired_antenna: Specifies a single physical antenna (1-256), or 0/None
        servicelog_desired_chipid: Specifies a single physical SMARTbox or FNDH unique serial number, or None.
        servicelog_desired_lognum: 0/None for the most recent log message, or larger numbers for older messages.

    Note that only one of 'servicelog_desired_antenna' and 'servicelog_desired_chipid' can be non-zero. If both are
    zero, then the user is requesting/writing a log message associated with the station as a whole.

    In reality, the service log entries would be stored in a site-wide database (SMARTboxes might be moved from station
    to station), so the code handling them here is a simple demo function.
    """
    def __init__(self, conn, station_id=None, logger=None, smartbox_class=smartbox.SMARTbox, fndh_class=fndh.FNDH):
        """
        Instantiate an instance of Station() using the connection object for this given
        station.

        This initialisation function doesn't communicate with any of the station hardware, it just sets up the
        data structures.

        :param conn: An instance of transport.Connection() for the transport layer.
        :param station_id: An integer, unique for each physical station.
        :param logger: A logging.logger() instance to log messages to, or None to create a new one.
        :param smartbox_class: A class to use when creating a SMARTbox() instance inside this stattion
        :param fndh_class: A class to use when creating the FNDH() instance for this station
        """
        self.conn = conn  # An instance of transport.Connection()
        self.station_id = station_id
        self.online = False    # True if the station is powered up
        self.smartbox_class = smartbox_class
        self.fndh_class = fndh_class
        self.antennae = {}  # A dict with physical antenna number (1-256) as key, and smartbox.PortStatus() instances as value
        self.smartboxes = {}  # A dict with smartbox address (1-30) as key, and smartbox.SMARTbox() instances as value
        self.servicelog_desired_antenna = None  # Specifies a single physical antenna (1-256), or 0/None
        self.servicelog_desired_chipid = None  # Specifies a single physical SMARTbox or FNDH unique serial number, or None.
        self.servicelog_desired_lognum = 0  # 0/None for the most recent log message, or larger numbers for older messages.
        
        if logger is None:
            self.logger = logging.getLogger('S')
        else:
            self.logger = logger

        # Initialise self.antennae, and self.smartboxes[N].ports instances, with the dummy physical antenna mapping from
        # the ANTENNA_MAP dictionary. In a real system, this would be replaced with code to instantiate them from
        # database queries.
        for sadd in ANTENNA_MAP.keys():
            smb = self.smartbox_class(conn=self.conn, modbus_address=sadd, logger=logging.getLogger('SB:%d' % sadd))
            for pnum in range(1, 13):
                smb.ports[pnum].antenna_number = ANTENNA_MAP[sadd][pnum]
                if ANTENNA_MAP[sadd][pnum] is not None:
                    self.antennae[ANTENNA_MAP[sadd][pnum]] = smb.ports[pnum]
            self.smartboxes[sadd] = smb

        self.fndh = self.fndh_class(conn=self.conn, modbus_address=FNDH_ADDRESS, logger=logging.getLogger('FNDH:%d' % FNDH_ADDRESS))

    def startup(self):
        """
        Configure and start up the FNDH. THe startup sequence is:

            1) Write the threshold level data to the FNDH micocontroller, and configure all the PDoC ports to stay turned
               off in both 'online' and 'offline' states.
            2) Transition the FNDH from UNINITIALISED to 'OK' by writing to the system status register.
            3) Force ON all the PDoC ports, one by one, with a 10 second delay between ports. For each physical port (1-28),
               record the Unix timestamp (seconds since epoch) that it was turned on.
            4) Loop over all possible SMARTbox addresses (1-30), interrogating each to see if it's online, and if so,
               to read back the system 'uptime' count in seconds. Subtract that value from the current timestamp to
               work out when that box booted.
            5) Use the PDoC port 'power on' times for ports 1-28, and the calculated boot times for each of the SMARTboxes
               that responds, to work out which SMARTbox is connected to which PDoC port.
            6) Record that mapping by setting the .pdoc_number attribute in each SMARTbox instance in self.smartboxes,
               and by setting the .smartbox_address attribute in each of the PdocStatus instances in self.fndh.ports
            7) Finish by setting the real 'desired_state_online' and 'desired_state_offline' values for all of the PDoC
               ports, and writing that to the FNDH.
        """
        self.online = None   # Failure in the middle of this process means the state is unknown
        ok = self.fndh.poll_data()
        if not ok:
            self.logger.error('No reply from FNDH - aborting station startup.')
            return False

        ok = self.fndh.configure_all_off()   # Transition the FNDH to online, but with all PDoC ports turned off
        if not ok:
            self.logger.error('Could not configure FNDH - aborting station startup.')
            return False

        # Turn on all the ports, one by one, with a 10 second interval between each port
        port_on_times = {}   # Unix timestamp at which each port number was turned on
        for portnum in range(1, 29):
            time.sleep(10)
            self.fndh.ports[portnum].desire_enabled_online = True
            self.logger.info('Turning on PDoC port %d' % portnum)
            ok = self.fndh.write_portconfig(write_state=True, write_to=True)
            port_on_times[portnum] = int(time.time())
            if not ok:
                self.logger.error('Could not write port configuration to the FNDH when turning on port %d.' % portnum)
                return False

        # Read the uptimes for all possible SMARTbox addresses, to work out when they were turned on
        address_on_times = {}   # Unix timestamp at which each SMARTbox booted, according to the uptime
        for sadd in range(1, 31):   # All possible SMARTbox addresses
            if sadd in self.smartboxes:
                smb = self.smartboxes[sadd]
            else:   # If this address isn't in the saved antenna map, create a temporary SMARTbox instance.
                smb = self.smartbox_class(conn=self.conn, modbus_address=sadd)

            uptime = None
            try:
                uptime = smb.read_uptime()
            except:
                pass

            if uptime is None:
                address_on_times[sadd] = 0
                continue
            else:
                self.logger.info('Uptime of %d (%d) from SMARTbox at address %d' % (uptime, time.time() - uptime, sadd))

            address_on_times[sadd] = time.time() - uptime
            if sadd not in self.smartboxes:  # If this SMARTbox isn't in the antenna map, save it in the the smartbox dictionary
                self.smartboxes[sadd] = smb

        self.logger.info('ON times: %s' % port_on_times)
        self.logger.info('ADDRESS times: %s' % address_on_times)

        for portnum in range(1, 29):
            ontime = port_on_times[portnum]
            # Get a list of (address, difftime) tuples where address is modbus address, and difftime is how long it took to
            # boot the smartbox at that address after this port was turned on (skipping boxes that we heard from before the port
            # was turned on).
            diffs = [(anum, (address_on_times[anum] - ontime)) for anum in address_on_times.keys() if address_on_times[anum] > ontime]
            diffs.sort(key=lambda x: x[1])   # sort by time difference
            if (diffs is not None) and (diffs[0][1] < 10.0):
                sadd = diffs[0][0]   # Modbus address of the SMARTbox on this PDoC port number
                self.smartboxes[sadd].pdoc_number = portnum
                self.fndh.ports[portnum].smartbox_address = sadd
                self.logger.info('Assigned SMARTbox %d to PDoC port %d' % (sadd, portnum))

        # Finish FNDH configuration, setting the default desired_state_online/offline flags (typically turning on all ports)
        ok = self.fndh.configure_final()
        if not ok:
            self.logger.error('Could not do final configuration of FNDH during startup.')
            return False

        self.online = True
        return True

    def shutdown(self):
        """
        Power down all PDoC ports on the FNDH.

        :return: True for success, False for failure
        """
        allok = True
        for portnum in range(1, 29):
            time.sleep(1)
            self.fndh.ports[portnum].desire_enabled_online = True
            self.logger.info('Turning off PDoC port %d' % portnum)
            ok = self.fndh.write_portconfig()
            if not ok:
                allok = False
                self.logger.error('Could not write port configuration to the FNDH when turning on port %d.' % portnum)
        if allok:
            self.online = False
        else:
            self.online = None   # We failed to turn off the PDoC ports, so we don't know the state
        return allok

    def poll_data(self):
        """
        Poll the FNDH microcontroller, asking each for all of the registers in the 'POLL' set, to get the latest state
        and telemetry data. If the FNDH is in the 'UNINITIALISED' state, indicating that it hasn't been configured by
        the MCCS since power-up, then go through a full startup() procedure configure it, bring it online, and determine
        the mapping between PDoC ports and SMARTbox address,.

        Then iterate over all possible SMARTbox addresses (1-30), asking each of them for all of the registers in the
        'POLL' set, to get the latest state and telemetry data. If any of the SMARTboxes are in the 'UNINITIALISED'
        state, configure them and bring them online. Add any 'unknown' SMARTboxes (not already in self.smartboxes) to
        the instance data.

        If neither the FNDH nor any of the SMARTboxes have been power cycled and need to be configured, this poll_data()
        function should take ~10 seconds for a fully populated station.

        :return: None
        """
        # First, check the FNDH, and go through the full startup procedure if it's been power cycled since the last poll
        fndh_ok = self.fndh.poll_data()
        if fndh_ok:
            if self.fndh.statuscode != fndh.STATUS_OK:
                self.logger.warning('FNDH has status %d (%s)' % (self.fndh.statuscode, self.fndh.status))
            if self.fndh.statuscode == fndh.STATUS_UNINITIALISED:  # UNINITIALISED
                fndh_ok = self.startup()     # In a real setting, pass in static configuration data from config file or database
                if fndh_ok:
                    self.logger.info('FNDH configured, it is now online with all PDoC ports mapped.')
                else:
                    self.logger.error('Error starting up FNDH')
        else:
            self.logger.error('Error calling poll_data() for FNDH')

        # Next, grab all the data from all possible SMARTboxes, to keep comms restricted to a short time window
        for sadd in range(1, 31):
            if sadd not in self.smartboxes:   # Check for a new SMARTbox with this address
                smb = self.smartbox_class(conn=self.conn, modbus_address=sadd)
                test_ok = smb.poll_data()
                if test_ok:
                    self.smartboxes[sadd] = smb   # If we heard a reply, add it to self.smartboxes, if not, ignore it
            else:
                smb_ok = self.smartboxes[sadd].poll_data()
                if not smb_ok:
                    self.logger.error('Error calling poll_data for SMARTbox %d' % sadd)

        # If any of the SMARTboxes have had a long button-press (indicating that a local technician wants that SMARTbox
        # to be powered down), then it will set it's status code and indicator LED code to the 'WANTS_POWERDOWN' value.
        # Check all the SMARTboxes for that LED code, and if set, force the matching PDoC port on the FNDH into the
        # 'locally_forced_off' state.
        # Note that this can only be reversed by having the technician press the service button on the FNDH, to clear
        # the technician override bits.
        send_portstate = False
        for smb in self.smartboxes.values():
            if smb.statuscode == smartbox.STATUS_POWERDOWN:
                for p in self.fndh.ports.values():
                    p.locally_forced_off = True
                    send_portstate = True

        if send_portstate:
            self.fndh.write_portconfig(write_to=True)

        # Now configure and activate any UNINITIALISED boxes, and log any error/warning states
        for sadd in range(1, 31):
            if sadd in self.smartboxes:
                smb = self.smartboxes[sadd]
                if smb.statuscode != smartbox.STATUS_OK:
                    self.logger.warning('SMARTbox %d has status %d (%s)' % (sadd, smb.statuscode, smb.status))

                if smb.statuscode == smartbox.STATUS_UNINITIALISED:  # UNINITIALISED
                    ok = smb.configure()    # In a real setting, pass in static configuration data from config file or database
                    if ok:
                        self.logger.info('SMARTbox %d configured, it is now online' % sadd)
                    else:
                        self.logger.error('Error configuring SMARTbox %d' % sadd)

        # If the FNDH has had a long button-press (indicating that a local technician wants that station
        # to be powered down and restarted with a full smartbox address detection sequence), then it will set it's
        # status code and indicator LED code to the 'POWERUP' value.
        if self.fndh.statuscode == fndh.STATUS_POWERUP:
            self.startup()

    def listen(self, maxtime=60.0):
        """
        Listen on the socket for any incoming read/write register packets sent by an external bus master (eg, a technician
        in the field). Handle any read/write register calls. Exit after 'maxtime' seconds (typically a few minutes).

        The transport.Connection.listen_for_packet() method exits after the first valid packet processed, to allow
        the calling code to handle side-effects from register read/write operations (for example, multiple reads from
        the same register block returning different values). This code loops until the specified maxtime, and for
        each, it:

        1) Sets up the slave_registers dictionary with the current physical antenna number to SMARTbox/port number
           mapping.
        2) Sets up the slave_registers dictionary with the next log message for the SID to read, given the current
           values of servicelog_desired_antenna, servicelog_desired_chipid, and servicelog_desired_lognum.
        3) Calls self.conn.listen_for_packet(), which returns all of the register numbers read or written by a packet
           (if one was processed in that call). If no packets are received, it will return at the specified maxtime.
        4) Uses the list of written registers to update the mapping between physical antenna number and SMARTbox/port
           number, or to save a new service log message.
        5) Uses the list of read registers to increment the log message counter to the next message, if a service log
           message was read.

        :param maxtime: Maximum time to listen for, in seconds (typically a few minutes).
        :return: None
        """
        start_time = time.time()
        end_time = start_time + maxtime
        while (time.time() < end_time):  # Process packets until we run out of time
            # Set up the registers for the physical->smartbox/port mapping:
            slave_registers = {n:None for n in range(1, 257)}
            for port in self.antennae.values():
                if port is not None:
                    slave_registers[port.antenna_number] = port.modbus_address * 256 + port.port_number

            # Set up the registers for the PDoC port number to smartbox address mapping:
            pdoc_registers = {(PDOC_REGSTART + pdoc_num):self.fndh.ports[pdoc_num].smartbox_address for pdoc_num in self.fndh.ports.keys()}
            slave_registers.update(pdoc_registers)

            # Set up the registers for reading/writing log messages
            log_message, timestamp = self.get_log_entry(desired_antenna=self.servicelog_desired_antenna,
                                                        desired_chipid=self.servicelog_desired_chipid,
                                                        desired_lognum=self.servicelog_desired_lognum)
            # Make sure it's not too long, is null terminated, and an even length, to pad out to a whole number of registers
            log_message = log_message[:(MESSAGE_LEN - 2) * 2 - 1]  # Truncate to one fewer character than the limit, to make room for a null
            if divmod(len(log_message), 2)[1] == 0:
                log_message += chr(0) + chr(0)
            else:
                log_message += chr(0)
            log_registers = {ANTNUM:self.servicelog_desired_antenna, LOGNUM:self.servicelog_desired_lognum}  # Initialise log entry registers
            for i in range(8):
                if self.servicelog_desired_chipid is not None:
                    log_registers[CHIPID + i] = self.servicelog_desired_chipid[i]
                else:
                    log_registers[CHIPID + i] = 0
            for i in range(MESSAGE_LEN - 2):  # Iterate over registers in the log message block
                if (i * 2) < len(log_message):
                    log_registers[MESSAGE + i] = ord(log_message[i * 2]) * 256 + ord(log_message[i * 2 + 1])
                else:
                    log_registers[MESSAGE + i] = 0
            log_registers[MESSAGE + MESSAGE_LEN - 2], log_registers[MESSAGE + MESSAGE_LEN - 1] = divmod(timestamp, 65536)

            slave_registers.update(log_registers)    # log entry read/write registers
            try:
                read_set, written_set = self.conn.listen_for_packet(listen_address=SLAVE_MODBUS_ADDRESS,
                                                                    slave_registers=slave_registers,
                                                                    maxtime=(end_time - time.time()),
                                                                    validation_function=validate_mapping)
            except:
                self.logger.exception('Exception in transport.listen_for_packet():')
                time.sleep(1)
                continue

            for regnum in written_set:
                if 1 <= regnum <= 256:
                    sadd, portnum = divmod(slave_registers[regnum], 256)
                    if self.antennae[regnum].antenna_number is not None:  # If there is already a SMARTbox instance mapped to this antenna
                        self.antennae[regnum].antenna_number = None          # then unmap it
                    if sadd in self.smartboxes:  # If we have a SMARTbox with this address, map it to this antenna
                        self.antennae[regnum] = self.smartboxes[sadd].ports[portnum]
                        self.antennae[regnum].antenna_number = regnum     # And update it's antenna_number attribute
                    else:
                        self.antennae[regnum] = None   # No SMARTbox instance for the given address.

            if (ANTNUM in written_set) and (self.servicelog_desired_antenna != slave_registers[ANTNUM]):
                self.servicelog_desired_antenna = slave_registers[ANTNUM]
                self.servicelog_desired_lognum = 0   # New desired antenna, so reset the log message counter
            if (CHIPID in written_set) and (self.servicelog_desired_chipid != [slave_registers[i] for i in range(CHIPID, CHIPID + 8)]):
                self.servicelog_desired_chipid = [slave_registers[i] for i in range(CHIPID, CHIPID + 8)]
                self.servicelog_desired_lognum = 0   # New desired chipid, so reset the log message counter
            if (LOGNUM in written_set) and (self.servicelog_desired_lognum != slave_registers[LOGNUM]):
                self.servicelog_desired_lognum = slave_registers[LOGNUM]   # New log message counter

            if MESSAGE in read_set:
                self.servicelog_desired_lognum += 1   # We've read a log message, so next time use the next message

            if MESSAGE in written_set:
                messagelist = []
                for value in [slave_registers[i] for i in range(MESSAGE, MESSAGE + MESSAGE_LEN - 2)]:  # Last two registers are timestamp
                    messagelist += list(divmod(value, 256))
                self.save_log_entry(desired_antenna=self.servicelog_desired_antenna,
                                    desired_chipid=self.servicelog_desired_chipid,
                                    message=bytes(messagelist).decode('utf8'),
                                    message_timestamp=time.time())

    def get_log_entry(self, desired_antenna=None, desired_chipid=None, desired_lognum=0):
        """
        Dummy function to return a log entry for the given antenna, chipid, and station. In reality, these log entries
        would be in a database.

        :param desired_antenna:  # Specifies a single physical antenna (1-256), or 0/None
        :param desired_chipid:  # Specifies a single physical SMARTbox or FNDH unique serial number, or None.
        :param desired_lognum:  # 0/None for the most recent log message, or larger numbers for older messages.
        :return: A tuple of the log entry text, and a unix timestamp for when it was created.
        """
        self.logger.info('Log entry #%d requested for station:%s, Ant#:%s, chipid=%s' % (desired_lognum,
                                                                                         self.station_id,
                                                                                         desired_antenna,
                                                                                         desired_chipid))
        return ("Insert a real service log database here: %d." % desired_lognum, 1614319283)

    def save_log_entry(self, desired_antenna=None, desired_chipid=None, message=None,
                       message_timestamp=None):
        """
        Dummy function to write a log entry for the given antenna, chipid, and station. In reality, these log entries
        would be in a database.

        :param desired_antenna: integer: Specifies a single physical antenna (1-256), or 0/None
        :param desired_chipid: bytes: Specifies a single physical SMARTbox or FNDH unique serial number, or None.
        :param message: string: Message text
        :param message_timestamp: integer: Unix timestamp
        :return: True for success, False for failure
        """
        self.logger.info('Log entry received at %s for station:%s, Ant#:%s, chipid=%s: %s' % (message_timestamp,
                                                                                              self.station_id,
                                                                                              desired_antenna,
                                                                                              desired_chipid,
                                                                                              message))
        return True

    def mainloop(self):
        """
        Runs forever, polling the FNDH and SMARTboxes once a minute (as a Modbus master), and spending the rest of the time
        acting as a Modbus slave, waiting for commands from a technician's SID.
        """
        while True:
            self.poll_data()
            self.listen(maxtime=60)


def validate_mapping(slave_registers=None):
    """Return True if the physical antenna mapping in registers 1-256 is valid, or False if the same
       SMARTbox and port number is in more than one physical antenna register.

       This function is passed into transport.Connection.listen_for_packet() as a parameter, and used to validate the
       slave_registers dictionary after any packet that writes one or more registers. If the function returns False,
       the packet gets an exception code as a reply and the register changes are discarded.

       :param slave_registers: A dictionary with register number (1-9999) as key, and integers (0-65535) as values.
    """
    seen = set()
    for regnum in slave_registers.keys():
        if 1 <= regnum <= 256:
            if slave_registers[regnum] != 0:
                if slave_registers[regnum] in seen:
                    return False
                else:
                    seen.add(slave_registers[regnum])
    return True


"""
Use as 'communicate.py station', or:

from pasd import transport
from pasd import station
conn = transport.Connection(hostname='134.7.50.185')  # address of ethernet-serial bridge
# or
conn = transport.Connection(devicename='/dev/ttyS0')  # or 'COM5' for example, under Windows

s = station.Station(conn=conn, station_id=1)
s.startup()
"""
