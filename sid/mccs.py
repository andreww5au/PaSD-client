#!/usr/bin/env python

"""
Classes to handle communication with the PaSD local MCCS, when it is acting as a Modbus slave. Used by SID device to
query the MCCS instead of the FNDH or a SMARTbox.
"""

import logging

logging.basicConfig()
logger = logging.getLogger()
logger.level = logging.DEBUG

from pasd import transport

MCCS_ADDRESS = 63

# Register numbers for when the MCCS is acting as a Modbus slave) - copied from pasd/station.py
PHYSANT_REGSTART = 0  # One register for each physical antenna, eg 1-256
ANTNUM = 1001   # register holding physical antenna number for service log, R/W.
CHIPID = 1002   # register holding chip ID for service log, R/W.
LOGNUM = 1010   # register holding log entry number (0 is most recent) for service log, R/W.
MESSAGE = 1011   # registers holding Log message text, up to 245 characters (including a null terminator) in up to 123 registers, R/W.
PDOC_REGSTART = 1200  # One register for each PDoC (1-28), eg 1201-1228

# Number of registers of log message block (max of 125 due to Modbus packet length limit),
# where the last two registers are the 4-byte unix timestamp for when the message was logged.
MESSAGE_LEN = 125


class MCCS(transport.ModbusSlave):
    """
    MCCS class, an instance of which represents the PaSD local MCCS software
    """
    def __init__(self, conn=None, modbus_address=MCCS_ADDRESS):
        """
        Instantiate an instance of MCCS() using a connection object, and the modbus address for the MCCS process.

        This initialisation function doesn't communicate with the MCCS, it just sets up the
        data structures.

        :param conn: An instance of transport.Connection() defining a connection to an FNDH
        :param modbus_address: The modbus station address of the MCCS, typically 63
        """
        transport.ModbusSlave.__init__(self, conn=conn, modbus_address=modbus_address)
        self.pdocs = {}   # Dictionary with PDoC port number (1-28) as key, and SMARTbox address (or 0) as value
        self.antennae = {}  # Dictionary with physical antenna number (1-256) as key, and a tuple of
                            # (SMARTbox_address, port_number) as value

    def poll_data(self):
        """
        Fetch the 28 registers corresponding to physical PDoC ports, and get the smartbox addresses connected
        to each of the 28 ports.

        Fetch the 256 registers corresponding to physical antenna numbers, and get
        the SMARTbox and port numbers for each physical antenna.

        :return: True if there were no errors, None on error.
        """
        # Get a list of 28 tuples, where each tuple is a two-byte register value, eg (0,255)
        try:
            valuelist = self.conn.readReg(modbus_address=self.modbus_address, regnum=PDOC_REGSTART + 1, numreg=28)
        except Exception:
            logger.exception('Exception in readReg in poll_data for pdoc mapping from MCCS')
            return None

        self.pdocs = {pdoc_num:(valuelist[pdoc_num - 1][0] * 256 + valuelist[pdoc_num - 1][0]) for pdoc_num in range(1, 29)}

        # Get a list of 256 tuples, where each tuple is a two-byte register value, eg (0,255)
        try:
            valuelist = self.conn.readReg(modbus_address=self.modbus_address, regnum=PHYSANT_REGSTART + 1, numreg=256)
        except Exception:
            logger.exception('Exception in readReg in poll_data for physical antenna mapping from MCCS')
            return None

        self.antennae = {ant_num:valuelist[ant_num - 1] for ant_num in range(1, 256)}
        return True

    def get_log_message(self, desired_antenna=None, desired_chipid=None, desired_lognum=0):
        """
        Return a log entry for the given antenna, chipid, and station, by querying the MCCS over the serial link.

        :param desired_antenna:  # Specifies a single physical antenna (1-256), or 0/None
        :param desired_chipid:  # Specifies a single physical SMARTbox or FNDH unique serial number, or None.
        :param desired_lognum:  # 0/None for the most recent log message, or larger numbers for older messages.
        :return: A tuple of the log entry text, and a unix timestamp for when it was created.
        """
