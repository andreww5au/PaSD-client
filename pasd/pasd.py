#!/usr/bin/env python

import logging
import time
import socket

logging.basicConfig()
logger = logging.getLogger()
logger.level = logging.DEBUG


PACKET_WINDOW_TIME = 0.01   # Time in seconds to wait before and after each packet, to satisfy modbus 28 bit silence requirement
TIMEOUT = 1.0   # Wait at most this long for a reply to a modbus message

# Example 'read' register definitions
RRegs = {100:(1, 1.0, 'V', 0.0, 'Average Line-Line AC RMS Voltage'),
         101:(1, 1.0, 'A', 0.0, 'Average AC RMS Current') }

# Example 'write' register definitions
WRegs = {300:(1, 1, 'BOOL', 0, 'Bypass Cooldown'),
         302:(1, 1, 'OPMODE', 0, 'Engine Operating Mode Command') }


def open_socket(hostname, port=1234):
    """
    Given a hostname, open a TCP socket to port 'port', and return the socket.
    If a socket can't be opened, return None

    :param hostname: DNS name (or IP address as a string) to connect to
    :param port: port number
    :return: A socket.socket object, or None
    """
    try:
        # Open TCP connect to port 1234 of GPIB-ETHERNET
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        sock.settimeout(0.1)
        sock.connect((hostname, port))
        return sock
    except socket.error:
        logging.exception('Error opening socket to %s' % hostname)
        return None


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
        return NtoBytes(hw, 2) + NtoBytes(lw, 2)


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


def send(sock, message):
    """
    Calculate the CRC and send it and the message (a list of bytes) to the socket 'sock'.
    Return a bytelist containing any valid reply (without the CRC), or 'False' if there was no
    reply within TIMEOUT seconds, or if the reply had an invalid CRC.

    :param sock: A socket.socket object
    :param message: A list of bytes, each in the range 0-255
    :return: A list of bytes, each in the range 0-255, or False if no valid reply was received
    """
    message += getcrc(message)
    time.sleep(PACKET_WINDOW_TIME)
    sock.send(''.join(map(chr, message)))
    time.sleep(PACKET_WINDOW_TIME)
    replist = []

    stime = time.time()
    # Wait until the timeout trips, or until we have a packet with a valid CRC checksum
    while (time.time() - stime < TIMEOUT) and ((len(replist) < 4) or (getcrc(message=replist[:-2]) != replist[-2:])):
        try:
            reply = sock.recv(2)
            replist += list(map(ord, reply))
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


def readReg(sock, station, regnum, rawlen=1):
    """
    Given a register number, determine the register length, and return the
    raw register contents as a list of bytes.

    :param sock: A socket.socket object
    :param station: MODBUS station number, 0-255
    :param regnum: Register number to read
    :param rawlen: If regnum is not defined in RRegs, number of registers to read
    :return: A list of integers, each 0-255
    """
    if regnum in RRegs:
        rlen, rscale, runits, roff, rdesc = RRegs[regnum]
    else:
        rlen = rawlen

    packet = [station, 0x03] + NtoBytes(regnum - 1, 2) + NtoBytes(rlen, 2)
    reply = send(sock, packet)

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
    return reply[3:]


def writeReg(sock, station, regnum, value):
    """
    Given a register number and a value (passed as an integer), write the data to the given register
    in the given modbus station. Return True if the write succeeded, return False if the
    final register contents are not equal to the value written, and return None if there is any other error.

    :param sock: A socket.socket object
    :param station: MODBUS station number, 0-255
    :param regnum: Register number to read
    :param value: An integer value to write to the (2-byte) register
    :return: True for success, False if there is an unexpected value in the reply, or None for any other error
    """
    packet = [0x01, 0x06] + NtoBytes(regnum - 1, 2) + NtoBytes(value, 2)
    reply = send(sock, packet)
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


def writeMultReg(sock, station, regnum, data):
    """
    Given a starting register number and a list of bytes, write the data to the given register
    in the given modbus station. Return True if the write succeeded, return False if the
    reply doesn't match the data written, and return None if there is any other error.

    :param sock: A socket.socket object
    :param station: MODBUS station number, 0-255
    :param regnum: Register number to read
    :param data: A list integer values (0-255) to write to the (2-byte) register
    :return: True for success, False if there is an unexpected value in the reply, or None for any other error
    """
    rlen = len(data) // 2
    if 2 * rlen != len(data):    # Not an even number of bytes to send (each register is 2 bytes)
        logger.error('Must be an even number of bytes of data to write, not %d' % len(data))
        return None

    packet = [station, 0x10] + NtoBytes(regnum - 1, 2) + NtoBytes(rlen, 2) + NtoBytes(rlen * 2, 1) + data
    reply = send(sock, packet)
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
