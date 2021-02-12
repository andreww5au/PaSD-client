#!/usr/bin/env python

import logging
import time
import socket
import threading

import conversion

logging.basicConfig()
logger = logging.getLogger()
logger.level = logging.DEBUG


PACKET_WINDOW_TIME = 0.01   # Time in seconds to wait before and after each packet, to satisfy modbus 28 bit silence requirement
TIMEOUT = 1.0   # Wait at most this long for a reply to a modbus message

# Dicts with register name as key, and a tuple of (register_number, number_of_registers, name, scaling_function) as value
SMARTBOX_REGISTERS_1 = {'SYS_PCBREV':  (2, 1, 'PCB Revision number', None),
                        'SYS_CPUID':   (3, 2, 'Microcontroller device ID', None),
                        'SYS_CHIPID':  (5, 8, 'Chip unique device ID', None),
                        'SYS_FIRMVER': (13, 1, 'Firmware version', None),
                        'SYS_UPTIME':  (14, 1, 'Uptime in seconds', None),
                        'SYS_ADDRESS': (15, 1, 'MODBUS station ID', None),

                        'SYS_48V':     (16, 1, 'Incoming 48VDC voltage', conversion.scale_48v),
                        'SYS_PSU':     (17, 1, 'PSU output voltage', conversion.scale_5v),
                        'SYS_PSUTEMP': (18, 1, 'PSU Temperature', conversion.scale_temp),
                        'SYS_PCBTEMP': (19, 1, 'PCB Temperature', conversion.scale_temp),
                        'SYS_FEMTEMP': (20, 1, 'FEM Temperature', conversion.scale_temp),
                        'SYS_OUTTEMP': (21, 1, 'Outside Temperature', conversion.scale_temp)
                        }

FNDH_REGISTERS_1 = {}


# Dicts with register version number as key, and a dict of registers (defined above) as value
SMARTBOX_REGISTERS = {1: SMARTBOX_REGISTERS_1}
FNDH_REGISTERS = {1: FNDH_REGISTERS_1}


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


class SMARTbox(ModbusSlave):
    def __init__(self, conn=None):
        ModbusSlave.__init__(self, conn=conn, station=None)

    def get_register_map(self):
        """Get the contents of register 1 from the device (the register map revision number), and use it
           to look up the relevant register map
        """
        reslist = self.conn.readReg(sock=self.conn, station=self.station, regnum=1)
        if reslist:
            self.reg_version = reslist[0] * 256 + reslist[1]
        else:
            return

        self.register_map = SMARTBOX_REGISTERS[self.reg_version]


class Connection(object):
    def __init__(self, hostname, port=5000):
        self.sock = None
        self.open_socket(hostname=hostname, port=port)

    def open_socket(self, hostname, port=1234):
        """
        Given a hostname, open a TCP socket to port 'port'

        :param hostname: DNS name (or IP address as a string) to connect to
        :param port: port number
        """
        try:
            # Open TCP connect to port 1234 of GPIB-ETHERNET
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
            self.sock.settimeout(0.1)
            self.sock.connect((hostname, port))
        except socket.error:
            logging.exception('Error opening socket to %s' % hostname)

    def send(self, message):
        """
        Calculate the CRC and send it and the message (a list of bytes) to the socket 'sock'.
        Return a bytelist containing any valid reply (without the CRC), or 'False' if there was no
        reply within TIMEOUT seconds, or if the reply had an invalid CRC.

        :param message: A list of bytes, each in the range 0-255
        :return: A list of bytes, each in the range 0-255, or False if no valid reply was received
        """
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
        reply = self.send(packet)

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

    def writeReg(self, station, regnum, value):
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
        reply = self.send(packet)
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

    def writeMultReg(self, station, regnum, data):
        """
        Given a starting register number and a list of bytes, write the data to the given register
        in the given modbus station. Return True if the write succeeded, return False if the
        reply doesn't match the data written, and return None if there is any other error.

        :param sock: A socket.socket object
        :param station: MODBUS station number, 0-255
        :param regnum: Register number to read
        :param data: A list integer values (0-255) to write. To write to multiple consecutive registers, pass a list with more than 2 values
        :return: True for success, False if there is an unexpected value in the reply, or None for any other error
        """

        rlen = len(data) // 2
        if 2 * rlen != len(data):    # Not an even number of bytes to send (each register is 2 bytes)
            logger.error('Must be an even number of bytes of data to write, not %d' % len(data))
            return None

        packet = [station, 0x10] + NtoBytes(regnum - 1, 2) + NtoBytes(rlen, 2) + NtoBytes(rlen * 2, 1) + data
        reply = self.send(packet)
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
