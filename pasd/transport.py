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


class ModbusSlave(object):
    """
    Generic parent class for all modbus slaves that the MCCS can communicate with.

    Child objects will be SMARTbox units themselves, and the FNDH controller.
    """
    def __init__(self, conn=None, station=None):
        self.conn = conn
        self.station = station
        self.reg_version = None
        self.register_map = {}


class Connection(object):
    def __init__(self, hostname, port=5000):
        self.sock = None
        self.open_socket(hostname=hostname, port=port)
        self.lock = threading.RLock()

    def open_socket(self, hostname, port=1234):
        """
        Given a hostname, open a TCP socket to port 'port'

        :param hostname: DNS name (or IP address as a string) to connect to
        :param port: port number
        """
        try:
            # Open TCP connect to specified port on the specified WIZNet board in the FNDH
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
            self.sock.settimeout(0.1)
            self.sock.connect((hostname, port))
        except socket.error:
            logging.exception('Error opening socket to %s' % hostname)

    def send_as_master(self, message):
        """
        Calculate the CRC and send it and the message (a list of bytes) to the socket 'sock'.
        Return a bytelist containing any valid reply (without the CRC), or 'False' if there was no
        reply within TIMEOUT seconds, or if the reply had an invalid CRC.

        :param message: A list of bytes, each in the range 0-255
        :return: A list of bytes, each in the range 0-255, or False if no valid reply was received
        """
        with self.lock:
            message += getcrc(message)
            time.sleep(PACKET_WINDOW_TIME)
            self.sock.send(bytes(message))
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

    def readReg(self, station, regnum, numreg=1):
        """
        Given a register number, return the raw register contents as a list of bytes.

        :param station: MODBUS station number, 0-255
        :param regnum: Register number to read
        :param numreg: Number of registers to read (default 1)
        :return: A list of integers, each 0-255
        """

        packet = [station, 0x03] + NtoBytes(regnum - 1, 2) + NtoBytes(numreg, 2)
        reply = self.send_as_master(packet)

        if not reply:
            return None
        if reply[0] != station:
            errs = "Sent to station %d, but station %d responded.\n" % (station, reply[0])
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

    def writeReg(self, station, regnum, value):
        """
        Given a register number and a value, write the data to the given register
        in the given modbus station. Return True if the write succeeded, return False if the
        final register contents are not equal to the value written, and return None if there is any other error.

        If value is an integer, assume it's a 16-bit value and pass it as two bytes, MSB first (network byte order)
        If value is a list of two integers, assume they are 8-bit bytes and pass them in the given order.

        :param station: MODBUS station number, 0-255
        :param regnum: Register number to read
        :param value: An integer value to write to the (2-byte) register, or a list of two (8 bit) integers
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
        reply = self.send_as_master(packet)
        if not reply:
            return None
        if reply[0] != station:
            errs = "Sent to station %d, but station %d responded.\n" % (station, reply[0])
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

    def writeMultReg(self, station, regnum, valuelist):
        """
        Given a starting register number and a list of bytes, write the data to the given register
        in the given modbus station. Return True if the write succeeded, return False if the
        reply doesn't match the data written, and return None if there is any other error.

        :param station: MODBUS station number, 0-255
        :param regnum: Register number to read
        :param valuelist: A list of register values to write. To write to multiple consecutive registers, pass a list with
                          more than 1 value. Each value can be a single integer (passed as a 16-bit value, MSB first), or
                          a tuple of two integers (each 0-255).
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
        packet = [station, 0x10] + NtoBytes(regnum - 1, 2) + NtoBytes(rlen, 2) + NtoBytes(rlen * 2, 1) + data
        reply = self.send_as_master(packet)
        if not reply:
            return None
        if reply[0] != station:
            errs = "Sent to station %d, but station %d responded.\n" % (station, reply[0])
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

"""
        self.mbrv = transport.bytestoN(bytelist[0])
        self.pcbrv = transport.bytestoN(bytelist[1])
        self.register_map = SMARTBOX_REGISTERS[self.mbrv]
        self.codes = SMARTBOX_CODES[self.mbrv]
        self.cpuid = ''
        self.chipid = []
        self.firmware_version = 0
        self.uptime = 0
        self.station_value = 0
        self.incoming_voltage = 0.0
        self.psu_voltage = 0.0
        self.psu_temp = 0.0
        self.pcb_temp = 0.0
        self.outside_temp = 0.0
        self.statuscode = 0
        self.status = ''
        self.service_led = None
        self.indicator_code = None
        self.indicator_state = ''
"""