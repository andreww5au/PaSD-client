#!/usr/bin/env python

import logging
import time
import socket
import threading

logging.basicConfig()
logger = logging.getLogger()
logger.level = logging.DEBUG


PACKET_WINDOW_TIME = 0.01   # Time in seconds to wait before and after each packet, to satisfy modbus 28 bit silence requirement
TIMEOUT = 1.0   # Wait at most this long for a reply to a modbus message

SLAVE_MODBUS_ADDRESS = 63   # Address that technician's SID devices use to reach the MCCS as a slave device


# noinspection PyUnusedLocal
def dummy_validate(slave_registers=None):
    return True


class ModbusSlave(object):
    """
    Generic parent class for all modbus slaves that the MCCS can communicate with.

    Child objects will be SMARTbox units themselves, and the FNDH controller.
    """
    def __init__(self, conn=None, modbus_address=None):
        self.conn = conn
        self.modbus_address = modbus_address
        self.reg_version = None
        self.register_map = {}


class Connection(object):
    """
    Class to handle Modbus communications between the MCCS and Modbus-RTU devices connected via an ethernet to serial
    bridge. One instance of this class handles all communications for an entire station.

    It has public methods for acting as a Modbus master, and reading/writing registers on remote devices:
        readReg()
        writeReg()
        writeMultReg()
    And for acting as a Modbus slave, and listening for commands from a bus master device (the Technician's SID):
        listen_for_packet

    """
    def __init__(self, hostname, port=5000):
        """
        Create a new connection instance to the given hostname and port.

        :param hostname: DNS name (or IP address as a string) to connect to
        :param port: port number
        """
        self.sock = None
        self.hostname = hostname
        self.port = port
        self._open_socket()
        self.lock = threading.RLock()

    def _open_socket(self):
        """
        Open a TCP socket to 'self.hostname' on port 'self.port'
        """
        if self.sock is not None:
            try:
                self.sock.close()  # Close any existing socket, ignoring any errors (it might already be closed, or dead)
            except socket.error:
                pass

        try:
            # Open TCP connect to specified port on the specified IP address for the WIZNet board in the FNDH
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
            self.sock.settimeout(0.1)
            self.sock.connect((self.hostname, self.port))
        except socket.error:
            logging.exception('Error opening socket to %s' % self.hostname)

    def _flush(self):
        """
        Flush the input buffer by calling self.sock.recv() until no data is returned. If there's a socket error,
        then close and re-open the socket.
        """
        with self.lock:
            try:
                while self.sock.recv(1000):
                    pass
            except socket.error:
                self._open_socket()

    def _send_as_master(self, message):
        """
        Calculate the CRC and send it and the message (a list of bytes) to the socket 'self.sock'.
        Return a bytelist containing any valid reply (without the CRC), or 'False' if there was no
        reply within TIMEOUT seconds, or if the reply had an invalid CRC.

        :param message: A list of bytes, each in the range 0-255
        :return: A list of bytes, each in the range 0-255, or False if no valid reply was received
        """
        with self.lock:
            self._flush()   # Get rid of any old data in the input queue, and close/re-open the socket if there's an error
            message += getcrc(message)
            time.sleep(PACKET_WINDOW_TIME)
            self.sock.send(bytes(message))  # TODO - This will return the number of bytes sent, which might not be all of them. Use sendall() instead?
            time.sleep(PACKET_WINDOW_TIME)
            replist = []

            stime = time.time()
            # Wait until the timeout trips, or until we have a packet with a valid CRC checksum
            while (time.time() - stime < TIMEOUT) and ((len(replist) < 4) or (getcrc(message=replist[:-2]) != replist[-2:])):
                try:
                    reply = self.sock.recv(2)
                    replist += list(map(int, reply))
                except socket.timeout:
                    pass
                except:
                    logger.exception('Exception in sock.recv()')
                    return False

            logger.debug("Recvd: %s" % str(replist))
            if (len(replist) >= 4) and getcrc(message=replist[:-2]) == replist[-2:]:
                return replist[:-2]
            else:
                logger.error('No valid reply - raw data received: %s' % str(replist))
                return False

    def _send_reply(self, message):
        """
        Calculate the CRC and send it and the message (a list of bytes) to the socket 'self.sock'.
        Do not wait for a reply, because this _is_ a reply (we're acting as a Modbus slave).

        :param message: A list of bytes, each in the range 0-255
        :return: None
        """
        with self.lock:
            self._flush()  # Get rid of any old data in the input queue, and close/re-open the socket if there's an error
            message += getcrc(message)
            time.sleep(PACKET_WINDOW_TIME)
            self.sock.send(bytes(message))  # TODO - This will return the number of bytes sent, which might not be all of them. Use sendall() instead?
            time.sleep(PACKET_WINDOW_TIME)

    def listen_for_packet(self, slave_registers, maxtime=10.0, validation_function=dummy_validate):
        """
        Listen on the socket for an incoming read/write register packet sent by an external bus master (eg, a technician
        in the field). Handle one read/write register call by sending or modifying the contents of the registers passed
        in the 'slave_registers' dictionary. Exit after 'maxtime' seconds, or after processing one packet, whichever
        comes first.

        :param slave_registers: A dictionary with register number (1-9999) as the key, and an integer (0-65535) as the
                                value.
        :param maxtime: Maximum time to listen for, in seconds.
        :param validation_function: Function to call to validate slave_registers contents. If this validation_function
                                    returns false, reply to the sender with an 'Illegal Data Value' exception.
        :return: A tuple of two sets containing all the register numbers that were read-from/written-to during this call.
        """
        start_time = time.time()
        with self.lock:
            while (time.time() - start_time) < maxtime:  # Wait for a good packet until we run out of time
                msglist = []  # Start assembling a new packet
                packet_start_time = start_time + maxtime - TIMEOUT  # Don't wait after 'maxtime' for a new packet
                # Wait until the timeout trips, or until we have a full packet with a valid CRC checksum
                while (time.time() - packet_start_time) < TIMEOUT and ((len(msglist) < 4) or (getcrc(message=msglist[:-2]) != msglist[-2:])):
                    try:
                        data = self.sock.recv(2)
                        msglist += list(map(int, data))
                        if len(msglist) == 2:
                            packet_start_time = time.time()
                    except socket.timeout:
                        pass
                    except:
                        logger.exception('Exception in sock.recv()')
                        return set(), set()

                if ((len(msglist) < 4) or (getcrc(message=msglist[:-2]) != msglist[-2:])):
                    logger.warning('Packet fragment received: %s' % msglist)
                    self._flush()  # Get rid of any old data in the input queue, and close/re-open the socket if there's an error
                    continue    # Discard this packet fragment, keep waiting for a new valid packet

                # Handle the packet contents here
                if msglist[0] != SLAVE_MODBUS_ADDRESS:
                    logger.info('Packet received, but it was addressed to station %d' % msglist[0])
                    continue

                if msglist[1] == 0x03:   # Reading a register
                    regnum = msglist[2] * 256 + msglist[3]
                    numreg = msglist[4] * 256 + msglist[5]
                    replylist = [SLAVE_MODBUS_ADDRESS, 0x03]
                    read_set = set()
                    for r in range(regnum, regnum + numreg):   # Iterate over all requested registers
                        if r not in slave_registers:
                            replylist = [SLAVE_MODBUS_ADDRESS, 0x86, 0x02]  # 0x02 is 'Illegal Data Address'
                            self._send_reply(replylist)
                            logger.error('Reading register %d not allowed, returned exception packet %s' % (r, replylist))
                            continue
                        else:
                            replylist.append(NtoBytes(slave_registers[r], 2))
                            read_set.add(r)
                    self._send_reply(replylist)
                    return read_set, set()
                elif msglist[1] == 0x06:  # Writing a single register
                    regnum = msglist[2] * 256 + msglist[3]
                    value = msglist[4] * 256 + msglist[5]
                    if regnum in slave_registers:
                        slave_registers[regnum] = value
                        replylist = msglist[:-2]   # For success, reply with the same packet: CRC re-added in send_reply()
                    else:
                        replylist = [SLAVE_MODBUS_ADDRESS, 0x86, 0x02]   # 0x02 is 'Illegal Data Address'
                        logger.error('Writing register %d not allowed, returned exception packet %s.' % (regnum, replylist))
                    if not validation_function(slave_registers=slave_registers):
                        replylist = [SLAVE_MODBUS_ADDRESS, 0x86, 0x03]  # 0x03 is 'Illegal Data Value'
                        logger.error('Inconsistent register values, returned exception packet %s.' % (replylist,))
                    else:
                        self._send_reply(replylist)
                        return set(), {regnum}
                elif msglist[1] == 0x10:  # Writing multiple registers
                    regnum = msglist[2] * 256 + msglist[3]
                    numreg = msglist[4] * 256 + msglist[5]
                    numbytes = msglist[6]
                    bytelist = msglist[7:-2]

                    assert len(bytelist) == numbytes == (numreg // 2)
                    written_set = set()
                    for r in range(regnum, regnum + numreg):
                        if r not in slave_registers:
                            replylist = [SLAVE_MODBUS_ADDRESS, 0x90, 0x02]  # 0x02 is 'Illegal Data Address'
                            self._send_reply(replylist)
                            logger.error('Writing register %d not allowed, returned exception packet %s.' % (r, replylist))
                            continue
                        else:
                            value = bytelist[0] * 256 + bytelist[1]
                            bytelist = bytelist[2:]   # Use, then pop off, the first two bytes
                            slave_registers[r] = value
                            written_set.add(r)
                    if not validation_function(slave_registers=slave_registers):
                        replylist = [SLAVE_MODBUS_ADDRESS, 0x86, 0x03]  # 0x03 is 'Illegal Data Value'
                        logger.error('Inconsistent register values, returned exception packet %s.' % (replylist,))
                    else:
                        replylist = [SLAVE_MODBUS_ADDRESS, 0x10] + NtoBytes(regnum, 2) + NtoBytes(numreg, 2)
                        self._send_reply(replylist)
                        return set(), written_set
                else:
                    logger.error('Received modbus packet for function %d - not supported.' % msglist[1])
                    replylist = [SLAVE_MODBUS_ADDRESS, msglist[1] + 0x80, 0x01]
                    self._send_reply(replylist)

        return set(), set()

    def readReg(self, modbus_address, regnum, numreg=1):
        """
        Given a register number and the number of registers to read, return the raw register contents
        of the desired register/s.

        :param modbus_address: MODBUS station number, 0-255
        :param regnum: Register number to read
        :param numreg: Number of registers to read (default 1)
        :return: A list of register values, each a tuple of (MSB, LSB), where MSB and LSB are integers, 0-255
        """

        packet = [modbus_address, 0x03] + NtoBytes(regnum - 1, 2) + NtoBytes(numreg, 2)
        reply = self._send_as_master(packet)

        if not reply:
            return None
        if reply[0] != modbus_address:
            errs = "Sent to station %d, but station %d responded.\n" % (modbus_address, reply[0])
            errs += "Packet: %s\n" % str(reply)
            logger.error(errs)
            return None
        if reply[1] != 3:
            if reply[1] == 0x83:
                excode = reply[2]
                if excode == 2:
                    return "Exception 0x8302: Invalid register address"
                elif excode == 3:
                    return "Exception 0x8303: Register count <1 or >123"
                elif excode == 4:
                    return "Exception 0x8304: Read error on one or more registers"
                else:
                    return "Exception %s: Unknown exception" % (hex(excode + 0x83 * 256),)
            errs = "Unexpected reply received.\n"
            errs += "Packet: %s\n" % str(reply)
            logger.error(errs)
            return None
        blist = reply[3:]
        return [(blist[i], blist[i+1]) for i in range(0, len(blist), 2)]

    def writeReg(self, modbus_address, regnum, value):
        """
        Given a register number and a value, write the data to the given register
        in the given modbus station. Return True if the write succeeded, return False if the
        final register contents are not equal to the value written, and return None if there is any other error.

        If value is an integer, assume it's a 16-bit value and pass it as two bytes, MSB first (network byte order)
        If value is a list of two integers, assume they are 8-bit bytes and pass them in the given order.

        :param modbus_address: MODBUS station number, 0-255
        :param regnum: Register number to read
        :param value: An integer value to write to the (2-byte) register, or a list of two (0-255) integers
        :return: True for success, False if there is an unexpected value in the reply, or None for any other error
        """
        if type(value) == int:
            valuelist = NtoBytes(value, 2)
        elif (type(value) == list) and (len(value) == 2):
            valuelist = value
        else:
            logger.error('Unexpected register value: %s' % value)
            return False

        packet = [0x01, 0x06] + NtoBytes(regnum - 1, 2) + valuelist
        reply = self._send_as_master(packet)
        if not reply:
            return None
        if reply[0] != modbus_address:
            errs = "Sent to station %d, but station %d responded.\n" % (modbus_address, reply[0])
            errs += "Packet: %s\n" % str(reply)
            logger.error(errs)
            return None
        if reply[1] != 6:
            if reply[1] == 0x86:
                excode = reply[2]
                if excode == 2:
                    return "Exception 0x8602: Invalid register address"
                elif excode == 3:
                    return "Exception 0x8603: Register value out of range"
                elif excode == 4:
                    return "Exception 0x8604: Write error on one or more registers"
                else:
                    return "Exception %s: Unknown exception" % (hex(excode + 0x86 * 256),)
            errs = "Unexpected reply received.\n"
            errs += "Packet: %s\n" % str(reply)
            logger.error(errs)
            return None
        if reply != packet:
            return False  # Value returned is not equal to value written
        return True

    def writeMultReg(self, modbus_address, regnum, valuelist):
        """
        Given a starting register number and a list of bytes, write the data to the given register
        in the given modbus station. Return True if the write succeeded, return False if the
        reply doesn't match the data written, and return None if there is any other error.

        :param modbus_address: MODBUS station number, 0-255
        :param regnum: Register number to read
        :param valuelist: A list of register values to write. To write to multiple consecutive registers, pass a list with
                          more than 1 value. Each value can be a single integer (passed as a 16-bit value, MSB first), or
                          a tuple of (MSB, LSB), where MSB and LSB are integers (each 0-255).
        :return: True for success, False if there is an unexpected value in the reply, or None for any other error
        """
        data = []
        for value in valuelist:
            if type(value) == int:
                data += NtoBytes(value, 2)
            elif (type(value) == list) and (len(value) == 2):
                data += value
            else:
                logger.error('Unexpected register value: %s' % value)
                return None

        rlen = len(data) // 2
        packet = [modbus_address, 0x10] + NtoBytes(regnum - 1, 2) + NtoBytes(rlen, 2) + NtoBytes(rlen * 2, 1) + data
        reply = self._send_as_master(packet)
        if not reply:
            return None
        if reply[0] != modbus_address:
            errs = "Sent to station %d, but station %d responded.\n" % (modbus_address, reply[0])
            errs += "Packet: %s\n" % str(reply)
            logger.error(errs)
            return None
        if reply[1] != 0x10:
            if reply[1] == 0x90:
                excode = reply[2]
                if excode == 2:
                    return "Exception 0x9002: Starting or ending register address invalid"
                elif excode == 3:
                    return "Exception 0x9003: Register count <1 or >123, or bytecount<>rlen*2"
                elif excode == 4:
                    return "Exception 0x9004: Write error on one or more registers"
                else:
                    return "Exception %s: Unknown exception" % (hex(excode + 0x90 * 256),)
            errs = "Unexpected reply received.\n"
            errs += "Packet: %s\n" % str(reply)
            logger.error(errs)
            return None
        if (reply[2:4] != NtoBytes(regnum - 1, 2)) or (reply[4:6] != NtoBytes(rlen, 2)):
            return False  # start/number returned is not equal to regnum/rlen written
        return True


def NtoBytes(value, nbytes=2):
    """
    Given an integer value 'value' and a word length 'nbytes',
    convert 'value' into a list of integers from 0-255,  with MSB first
    and LSB last.

    :param value: An integer small enough to fit into the given word length
    :param nbytes: The word length to return
    :return: a list of integers, each in the range 0-255
    """
    assert nbytes in [1, 2, 4]
    if nbytes == 1:
        assert 0 <= value < 256
        return [value]
    elif nbytes == 2:
        assert 0 <= value < 65536
        return list(divmod(value, 256))
    elif nbytes == 4:
        assert 0 <= value < 4294967296
        hw, lw = divmod(value, 65536)
        return list(divmod(hw, 256)) + list(divmod(lw, 256))


def bytestoN(valuelist):
    """
    Given a list or tuple of integers, or a list of tuples, in network order (MSB first), convert to an integer.

    :param valuelist: A list of integers, or tuple of two integers, or a list of tuples of two integers
    :return: An integer
    """
    data = []
    for value in valuelist:
        if type(value) == int:
            data.append(value)
        elif (type(value) == tuple) and (len(value) == 2):
            data += list(value)
        else:
            logger.error('Unexpected value: %s' % value)
            return None

    nbytes = len(data)
    if nbytes != 2 * (nbytes // 2):
        logger.error('Odd number of bytes to convert: %s' % valuelist)
        return None

    return sum([data[i] * (256 ** (nbytes - i - 1)) for i in range(nbytes)])


def getcrc(message=None):
    """
    Calculate and returns the CRC bytes required for 'message' (a list of bytes).

    :param message: A list of bytes, each in the range 0-255
    :return: A list of two integers, each in the range 0-255
    """
    if not message:
        return 0, 0
    crc = 0xFFFF

    for byte in message:
        crc = crc ^ byte
        for bit in range(8):
            b = crc & 0x0001
            crc = (crc >> 1) & 0x7FFF
            if b:
                crc = crc ^ 0xA001
    return [(crc & 0x00FF), ((crc >> 8) & 0x00FF)]
