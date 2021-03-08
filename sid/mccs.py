#!/usr/bin/env python

"""
Class to handle communication with the PaSD local MCCS, when it is acting as a Modbus slave. Used by SID device to
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


class MCCS(transport.ModbusDevice):
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
        transport.ModbusDevice.__init__(self, conn=conn, modbus_address=modbus_address)
        self.pdocs = {}   # Dictionary with PDoC port number (1-28) as key, and SMARTbox address (or 0) as value
        self.antennae = {}  # Dictionary with physical antenna number (1-256) as key, and a tuple of
                            # (SMARTbox_address, port_number) as value

    def read_antennae(self):
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
        try:   # Limit is 125 register values in a single packet, so split this into three readReg() calls
            valuelist = self.conn.readReg(modbus_address=self.modbus_address, regnum=PHYSANT_REGSTART + 1, numreg=100)
            valuelist += self.conn.readReg(modbus_address=self.modbus_address, regnum=PHYSANT_REGSTART + 101, numreg=100)
            valuelist += self.conn.readReg(modbus_address=self.modbus_address, regnum=PHYSANT_REGSTART + 201, numreg=56)
        except Exception:
            logger.exception('Exception in readReg in poll_data for physical antenna mapping from MCCS')
            return None

        self.antennae = {ant_num:valuelist[ant_num - 1] for ant_num in range(1, 256)}
        return True

    def map_antenna(self, phys_num, smartbox_address, port_number):
        """
        Associate the given physical antenna number (1-256), and associate it with port number 'port_number' (1-12) on
        the SMARTbox with address 'smartbox_address'.

        If any physical antenna was already mapped to the given SMARTbox address and port, then unmap that physical
        antenna first (so it's not mapped to any SMARTbox/port).

        Then write the new mapping to the remote MCCS to update the remote database.

        :param phys_num: physical antenna number (1-256)
        :param smartbox_address: SMARTbox modbus address (1-30)
        :param port_number: FEM port number inside SMARTbox (1-12)
        :return: True if there were no errors, None on error.
        """
        unmapped_regnum = None
        mapped_regnum = None
        for antnum in range(1,257):
            if self.antennae[antnum] == (smartbox_address, port_number):
                if antnum != phys_num:   # Another smartbox/port is already mapped to this physical antenna, so unmap it.
                    self.antennae[antnum] = (0, 0)
                    unmapped_regnum = antnum
            elif antnum == phys_num:   # Add the new smartbox/port for this physical antenna number
                self.antennae[antnum] = (smartbox_address, port_number)
                mapped_regnum = antnum

        ok = True
        if unmapped_regnum:
            ok = self.conn.writeMultReg(modbus_address=self.modbus_address,
                                        regnum=unmapped_regnum,
                                        valuelist=[0])
            if ok:
                logger.info('Disconnected antenna %d from port %d on SMARTbox %d.' % (unmapped_regnum, smartbox_address, port_number))

        if mapped_regnum and ok:
            ok = self.conn.writeMultReg(modbus_address=self.modbus_address,
                                        regnum=mapped_regnum,
                                        valuelist=[smartbox_address * 256 + port_number])
            if ok:
                logger.info('Connected antenna %d to port %d on SMARTbox %d.' % (mapped_regnum, smartbox_address, port_number))
        return ok

    def get_log_message(self, desired_antenna=None, desired_chipid=None, desired_lognum=0):
        """
        Return a log entry for the given antenna, chipid, and station, by querying the MCCS over the serial link.

        :param desired_antenna:  # Specifies a single physical antenna (1-256), or 0/None
        :param desired_chipid:  # Specifies a single physical SMARTbox or FNDH serial number (bytes() object), or None.
        :param desired_lognum:  # 0/None for the most recent log message, or larger numbers for older messages.
        :return: None if there was an error, or A tuple of the log entry text, and a unix timestamp for when it was created
        """
        if desired_antenna is None:
            des_ant = 0
        else:
            des_ant = desired_antenna

        if desired_chipid is None:
            des_chip = [0] * 8
        else:
            des_chip = [desired_chipid[i * 2] * 256 + desired_chipid[i * 2 + 1] for i in range(8)]

        if desired_lognum is None:
            des_log = 0
        else:
            des_log = desired_lognum

        valuelist = [des_ant] + des_chip + [des_log]
        ok = self.conn.writeMultReg(modbus_address=self.modbus_address, regnum=ANTNUM, valuelist=valuelist)

        if ok:
            return self.get_next_log_message()
        else:
            return None

    def get_next_log_message(self):
        """
        Return the next (older in time) log message from the MCCS, using the previously defined desired antenna
        number, chipid, and/or starting log message number.

        :return: None if there was an error, or A tuple of the log entry text, and a unix timestamp for when it was created
        """
        messagelist = self.conn.readReg(modbus_address=self.modbus_address, regnum=MESSAGE, numreg=MESSAGE_LEN)
        if messagelist is None:
            return None

        message_timestamp = transport.bytestoN(messagelist[-2:])

        # Convert a list of MESSAGE_LEN-2 tuples of (msb, lsb) into a string, terminated at the first 0 byte.
        charlist = []
        for regvalue in messagelist[:-2]:
            for b in regvalue:
                if b > 0:
                    charlist.append(b)
                else:
                    break
        return bytes(charlist).decode('utf8'), message_timestamp


"""
from sid import mccs
from pasd import transport
conn = transport.Connection(devicename='COM6')
m = mccs.MCCS(conn=conn)
"""