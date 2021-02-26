#!/usr/bin/env python

import logging
import time

logging.basicConfig()
logger = logging.getLogger()
logger.level = logging.DEBUG

import fndh
import transport
import smartbox


FNDH_ADDRESS = 31   # Modbus address of the FNDH controller

# Mapping between SMARTbox/port and antenna number
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
 23: {1: 246, 2: 247, 3: 248, 4: 249, 5: 250, 6: 251, 7: 252, 8: 253, 9: 254, 10: 255, 11: 256},
 24: {1:None, 2:None, 3:None, 4:None, 5:None, 6:None, 7:None, 8:None, 9:None, 10:None, 11:None, 12:None},
 25: {1:None, 2:None, 3:None, 4:None, 5:None, 6:None, 7:None, 8:None, 9:None, 10:None, 11:None, 12:None},
 26: {1:None, 2:None, 3:None, 4:None, 5:None, 6:None, 7:None, 8:None, 9:None, 10:None, 11:None, 12:None},
 27: {1:None, 2:None, 3:None, 4:None, 5:None, 6:None, 7:None, 8:None, 9:None, 10:None, 11:None, 12:None},
 28: {1:None, 2:None, 3:None, 4:None, 5:None, 6:None, 7:None, 8:None, 9:None, 10:None, 11:None, 12:None}
}

# Register numbers for log message requests
ANTNUM = 1001   # Antenna number for service log, R/W.
CHIPID = 1002   # Chip ID for service log, R/W.
LOGNUM = 1010   # Log number (0 is most recent) for service log, R/W.
MESSAGE = 1011   # Log message text, up to 245 characters (including a null terminator) in up to 123 registers, R/W.

# Number of registers of log message block (max of 125 due to Modbus packet length limit),
# where the last two registers are the 4-byte unix timestamp for when the message was logged.
MESSAGE_LEN = 125


class Station(object):
    def __init__(self, hostname, port):
        self.hostname = hostname
        self.port = port
        self.conn = transport.Connection(hostname=self.hostname, port=self.port)
        self.antennae = {}  # A dict with physical antenna number as key, and smartbox.PortStatus() instances as value
        self.smartboxes = {}  # A dict with smartbox number as key, and smartbox.SMARTbox() instances as value
        self.desired_antenna = None
        self.desired_chipid = None
        self.desired_lognum = 0

        # Initialise self.antennae, and self.smartboxes[N].ports instances, with the physical antenna mapping from
        # the ANTENNA_MAP dictionary. In a real system, this would be replaced with code to instantiate them from
        # database queries.
        for sadd in ANTENNA_MAP.keys():
            smb = smartbox.SMARTbox(conn=self.conn, modbus_address=sadd)
            for pnum in range(1, 13):
                smb.ports[pnum].antenna_number = ANTENNA_MAP[sadd][pnum]
                if ANTENNA_MAP[sadd][pnum] is not None:
                    self.antennae[ANTENNA_MAP[sadd][pnum]] = smb.ports[pnum]
            self.smartboxes[sadd] = smb

        self.fndh = fndh.FNDH(conn=self.conn, modbus_address=FNDH_ADDRESS)

    def poll_data(self):
        """
        Grab status data from all of the SMARTboxes
        :return:
        """
        boxlist = list(self.smartboxes.keys())
        boxlist.sort()
        # First, grab all the data from all the boxes, to keep comms restricted to a short time window
        for sadd in boxlist:
            self.smartboxes[sadd].poll_data()
        self.fndh.poll_data()

        # Now configure and activate any UNINITIALISED boxes, and log any error/warning states
        for sadd in boxlist:
            smb = self.smartboxes[sadd]
            if smb.statuscode > 0:
                logger.warning('SMARTbox %d has status %d (%s)' % (sadd, smb.statuscode, smb.status))

            if smb.statuscode == 4:  # UNINITIALISED
                ok = smb.configure()    # In a real setting, pass in static configuration data from config file or database
                if ok:
                    logger.info('SMARTbox %d configured, it is now online' % sadd)
                else:
                    logger.error('Error configuring SMARTbox %d' % sadd)

        if self.fndh.statuscode > 0:
            logger.warning('FNDH has status %d (%s)' % (self.fndh.statuscode, self.fndh.status))

        if self.fndh.statuscode == 4:  # UNINITIALISED
            ok = self.fndh.configure()     # In a real setting, pass in static configuration data from config file or database
            if ok:
                logger.info('FNDH configured, it is now online')
            else:
                logger.error('Error configuring FNDH')

    def listen(self, maxtime=10.0):
        """
        Listen on the socket for any incoming read/write register packets sent by an external bus master (eg, a technician
        in the field). Handle read/write register calls. Exit after 'maxtime' seconds.

        :param maxtime: Maximum time to listen for, in seconds.
        :return:
        """
        start_time = time.time()
        end_time = start_time + maxtime
        while (time.time() < end_time):  # Process packets until we run out of time
            slave_registers = {port.antenna_number:(port.modbus_address * 256 + port.port_number) for port in self.antennae}

            # Set up the registers for reading/writing log messages
            log_message, timestamp = get_log_entry(station=self.hostname,
                                                   desired_antenna=self.desired_antenna,
                                                   desired_chipid=self.desired_chipid,
                                                   desired_lognum=self.desired_lognum)
            # Make sure it's not too long, is null terminated, and an even length, to pad out to a whole number of registers
            log_message = log_message[:(MESSAGE_LEN - 2) * 2 - 1]  # Truncate to one fewer character than the limit, to make room for a null
            if divmod(len(log_message), 2)[1] == 0:
                log_message += chr(0) + chr(0)
            else:
                log_message += chr(0)
            log_registers = {ANTNUM:self.desired_antenna, LOGNUM:self.desired_lognum}  # Initialise log entry registers
            for i in range(MESSAGE_LEN - 2):  # Iterate over registers in the log message block
                if (i * 2) < len(log_message):
                    log_registers[MESSAGE + i] = [ord(log_message[i * 2]), ord(log_message[i * 2 + 1])]
                else:
                    log_registers[MESSAGE + i] = 0
            log_registers[MESSAGE + MESSAGE_LEN + 1], log_registers[MESSAGE + MESSAGE_LEN + 2] = divmod(timestamp, 65536)

            slave_registers.update(log_registers)    # log entry read/write registers
            read_set, written_set = self.conn.listen_for_packet(slave_registers=slave_registers,
                                                                maxtime=(end_time - time.time()),
                                                                validation_function=validate_mapping)
            for regnum in written_set:
                if 1 <= regnum <= 256:
                    sadd, portnum = divmod(slave_registers[regnum], 256)
                    self.antennae[regnum].antenna_number = None
                    self.antennae[regnum] = self.smartboxes[sadd].ports[portnum]
                    self.antennae[regnum].antenna_number = regnum

            if (ANTNUM in written_set) and (self.desired_antenna != slave_registers[ANTNUM]):
                self.desired_antenna = slave_registers[ANTNUM]
                self.desired_lognum = 0   # New desired antenna, so reset the log message counter
            if (CHIPID in written_set) and (self.desired_chipid != slave_registers[CHIPID:CHIPID + 8]):
                self.desired_chipid = slave_registers[CHIPID:CHIPID + 8]
                self.desired_lognum = 0   # New desired chipid, so reset the log message counter
            if (LOGNUM in written_set) and (self.desired_lognum != slave_registers[LOGNUM]):
                self.desired_lognum = slave_registers[LOGNUM]   # New log message counter

            if MESSAGE in read_set:
                self.desired_lognum += 1   # We've read a log message, so next time use the next message

            if MESSAGE in written_set:
                messagelist = []
                for value in slave_registers[MESSAGE:MESSAGE + MESSAGE_LEN - 2]:  # Last two registers are timestamp
                    messagelist += list(divmod(value, 256))
                save_log_entry(station=self.hostname,
                               desired_antenna=self.desired_antenna,
                               desired_chipid=self.desired_chipid,
                               message=bytes(messagelist).decode('utf8'),
                               message_timestamp=time.time())


def validate_mapping(slave_registers=None):
    """Return True if the physical antenna mapping in registers 1-256 is valid, or False if the same
       SMARTbox and port number is in more than one physical antenna register.
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


def get_log_entry(station=None, desired_antenna=None, desired_chipid=None, desired_lognum=0):
    logger.info('Log entry #%d requested for station:%s, Ant#:%s, chipid=%s' % (desired_lognum,
                                                                                station,
                                                                                desired_antenna,
                                                                                desired_chipid))
    return "Insert a real service log database here.", 1614319283


def save_log_entry(station=None, desired_antenna=None, desired_chipid=None, message=None, message_timestamp=None):
    logger.info('Log entry received at %s for station:%s, Ant#:%s, chipid=%s: %s' % (message_timestamp,
                                                                                     station,
                                                                                     desired_antenna,
                                                                                     desired_chipid,
                                                                                     message))