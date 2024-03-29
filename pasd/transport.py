#!/usr/bin/env python

"""Classes to handle communications with remote devices using Modbus-RTU, either directly via serial port, over an
   ethernet-serial bridge (found in every FNDH), or via a simulated multi-drop shared serial bus to other threads using
   the same Connection instance.

   This code runs on both the MCCS side (in the control building), in a Technician's Serial Interface Device (a
   laptop or handheld device used in the field), and in the simulation software used to emulate FNDH's and SMARTboxes
   for testing.

   All code in this file implements the modbus specification for reading and writing holding registers (functions 0x03,
   0x06 and 0x10), both as a master device and as a slave device. It should work for any Modbus device using only the
   holding register set (40000-49999).
"""

import logging
import time
import socket
import threading

import serial

logging.basicConfig()


TIMEOUT = 1.3   # Wait at most this long for a reply to a modbus message
COMMS_TIMEOUT = 0.001  # Low-level timeout for each call to socket.socket().recv or serial.Serial.write()

VALID_BYTES = {ord(x) for x in '0123456789ABCDEF:\r\n'}

PCLOG = None
# PCLOG = open('./physical.log', 'w')

LCLOG = None
# LCLOG = open('./logical.log', 'w')


# noinspection PyUnusedLocal
def dummy_validate(slave_registers=None):
    return True


class Connection(object):
    """
    Class to handle Modbus communications between the MCCS and Modbus-RTU devices connected via an ethernet to serial
    bridge, or directly via a serial port. One instance of this class handles all communications for an entire station.

    An instance of this class is thread-safe - it can be shared between threads, and an internal lock prevents resource
    conflict.

    If .multimode is False, then each thread only writes to the remote device, and only sees incoming
    data from the remote device (whichever thread calls ._read() first will get the data, and strip it from the
    buffer so that other threads won't see it).

    if .multimode is True, then each thread writes to the remote device, and also appends to the input buffers
    for all other threads. When any thread calls ._read(), it reads from the remote device, appends any remote data
    to the input buffers for ALL threads, then pulls and returns the desired number of bytes from its own input buffer.

    It has public methods for acting as a Modbus master, and reading/writing registers on remote devices:
        readReg()
        writeReg()
        writeMultReg()
    And for acting as a Modbus slave, and listening for commands from a bus master device (the Technician's SID):
        listen_for_packet
    """
    def __init__(self, hostname=None, devicename=None, port=5000, baudrate=19200, multidrop=False, logger=None):
        """
        Create a new instance, using either a socket connection to a serial bridge hostname, or a physical serial port,
        or neither

        If 'multidrop' is true, this class can be used for emulating serial traffic between multiple threads, with or
        without an actual remote (serial or socket) connection. When any thread calls ._write(), data is sent to the
        remote device, and also appended to all other thread's input buffers. When any thread calls ._read(), the
        specified number of bytes is read from the remote device and appended to the input buffers for all threads. Then
        the first 'nbytes' of characters are removed from that thread's input buffer, and returned.

        :param hostname: Hostname (or IP address as a string) of a remote ethernet-serial bridge
        :param devicename: Device name of serial port, eg '/dev/ttyS0'
        :param port: Port number for a remote ethernet-serial bridge
        :param baudrate: Connection speed for serial port connection
        :param multidrop: If True, and this connection is shared between multiple threads, each thread will read()
                          any traffic written by any other thread, as well as that coming in from the (optional)
                          remote device, if specified.
        :param logger: A logging.Logger object to use for all log messages, or None (in which case one will be created)
        """
        if logger is None:
            self.logger = logging.getLogger('T')
        else:
            self.logger = logger
        self.readlock = threading.RLock()
        self.writelock = threading.RLock()
        self.sock = None  # socket.socket() object, for an ethernet-serial bridge, or None
        self.ser = None  # serial.Serial() object, for a physical serial port, or None
        self.hostname = hostname   # Hostname (or IP address as a string) of a remote ethernet-serial bridge
        self.port = port  # Port number for a remote ethernet-serial bridge
        self.devicename = devicename  # Device name of serial port, eg '/dev/ttyS0'
        self.baudrate = baudrate  # Connection speed for serial port connection
        self.multidrop = multidrop  # Emulate a multi-drop serial bus between multiple threads
        self.buffers = {}   # Dictionary with thread ID as key, and bytes() objects as values, so each thread has its own
                            # input buffer in multidrop mode.
        self._open()

    def _open(self):
        """
        Opens either a socket.socket connection (if hostname is supplied), or a serial.Serial connection (if
        a devicename is supplied).
        """
        with self.readlock:
            with self.writelock:
                if PCLOG:
                    PCLOG.write('%14.3f %d: Transport opened\n' % (time.time(), threading.get_ident()))
                    PCLOG.flush()

                if self.multidrop:
                    phys_timeout = 0
                else:
                    phys_timeout = COMMS_TIMEOUT

                if self.ser is not None:
                    try:
                        self.ser.close()  # Close any existing socket, ignoring any errors (it might already be closed, or dead)
                    except socket.error:
                        pass

                if self.hostname:  # We want a Socket.socket() connection
                    try:
                        # Open a socket to the ethernet-serial converter
                        self.ser = serial.serial_for_url('socket://%s:%d' % (self.hostname, self.port))
                        self.ser.timeout = phys_timeout
                    except serial.serialutil.SerialException:
                        logging.exception('Error opening socket to %s' % self.hostname)
                elif self.devicename is not None:
                    try:
                        # Open physical serial port for the specified device and speed
                        self.ser = serial.Serial(self.devicename, timeout=phys_timeout, baudrate=self.baudrate)
                    except serial.serialutil.SerialException:
                        logging.exception('Error opening serial port to %s' % self.devicename)
                else:
                    if self.multidrop:
                        self.logger.info('No remote device, emulating a multi-drop serial bus between threads.')
                    else:
                        self.logger.critical("No hostname or devicename, can't open socket or TCP connection")

                # Clear all the shared buffers, if they exist
                for threadid, buffer in self.buffers.items():
                    self.buffers[threadid] = bytes([])

    def _read(self, until=None, nbytes=1000):
        """
        Accepts the number of bytes to read, or an end of packet sequence, and returns that many bytes of data.

        This function will always return almost immediately (after one physical layer timeout - COMMS_TIMOUT, typically
        1 ms. It will return some number of bytes, up to nbytes (if provided), or up to and including the 'until'
        sequence (if provided), if they are available in the buffer. It will never return more than 'nbytes' bytes,
        or past the 'until' sequence, if either are provided. If neither are provided, it will return all the bytes
        available right now in the input buffer (up to a maximum of 1000 bytes).

        If multidrop is False, this simply calls self.sock.recv(bytes) or self.ser.read(nbytes), and returns the result.

        If multidrop is True, when any thread calls ._read(), all data currently in the hardware buffer is read from the
        remote device and appended to the input buffers for all threads. Then the requested characters are removed
        from that thread's input buffer, and returned.

        :param until: A bytes() object containing one or more bytes to read up-to (and including)
        :param nbytes: Maximum number of bytes to return.
        :return: A bytes() object containing up to 'bytes' characters, or up to and including the 'until' pattern.
        """
        ltime = time.time()
        with self.readlock:
            gtime = time.time()
            if gtime - ltime > 0.05:
                self.logger.debug('%d: %5.3f seconds to get readlock in _read' % (threading.get_ident(),
                                                                                  gtime - ltime))
            if self.ser is not None:
                if self.multidrop:
                    remote_data = self.ser.read(1000)
                else:
                    if until:
                        remote_data = self.ser.read_until(expected=until, size=nbytes)
                    else:
                        remote_data = self.ser.read(size=nbytes)
            else:
                remote_data = bytes([])

            if remote_data and PCLOG:
                PCLOG.write('%14.3f %d: Read "%s"\n' % (time.time(),
                                                        threading.get_ident(),
                                                        remote_data))
                PCLOG.flush()

            if not self.multidrop:  # single remote connection only
                return remote_data
            else:
                # Add any remote data received to the end of _all_ of the local buffers, so that other threads will see it
                thread_id = threading.get_ident()
                if thread_id not in self.buffers:
                    self.buffers[thread_id] = bytes([])
                for tid in self.buffers.keys():
                    self.buffers[tid] += remote_data

                if until:   # Return up to and including the pattern given, or nbytes, whichever is smaller
                    upos = self.buffers[thread_id].find(until)
                    if upos >= 0:
                        returnto = min(nbytes, upos + len(until))
                    else:
                        returnto = nbytes
                    data = self.buffers[thread_id][:returnto]
                    self.buffers[thread_id] = self.buffers[thread_id][returnto:]
                else:
                    # Pull the first 'nbytes' characters from the head of our local buffer
                    data = self.buffers[thread_id][:nbytes]
                    self.buffers[thread_id] = self.buffers[thread_id][nbytes:]

                if data and LCLOG:
                    LCLOG.write('%14.3f %d: Read "%s"\n' % (time.time(),
                                                            threading.get_ident(),
                                                            data))
                    LCLOG.flush()

                etime = time.time()
                if etime - gtime > 0.002:
                    self.logger.debug('%d: Spent %5.3f sec holding readlock in _read' % (threading.get_ident(),
                                                                                                 etime - gtime))
                return data

    def _write(self, data):
        """
        Accepts the data to write out, and sends that data to the remote device, and/or the input buffers for other
        threads when self.multidrop is True.

        If self.multidrop is False, this simply writes the given data by calling self.sock.send(data) or self.ser.write(data).

        If self.multidrop is True, when any thread calls ._write(), data is sent to the remote device, and also appended
        to all other thread's input buffers.

        :param data: A bytes() object containing the data to write
        :return: None
        """
        ltime = time.time()
        with self.writelock:
            gtime = time.time()
            if gtime - ltime > 0.05:
                self.logger.debug('%d: %5.3f seconds to get lock in _write' % (threading.get_ident(),
                                                                               gtime - ltime))
            if self.ser is not None:
                self.ser.write(data)

            # Commented out - we don't share written data with other threads, because smartboxes and the FNDH can't talk to each other
            # if self.multidrop:
            #     # Add any data sent to the end of the OTHER local buffers, so that other threads will see it
            #     thread_id = threading.get_ident()
            #     if thread_id not in self.buffers:
            #         self.buffers[thread_id] = bytes([])
            #     for tid in self.buffers.keys():
            #         if tid != thread_id:   # Don't add it to my read buffer, because I sent it.
            #             self.buffers[tid] += data

        if PCLOG:
            PCLOG.write('%14.3f %d: Write "%s"\n' % (time.time(),
                                                     threading.get_ident(),
                                                     data))
            PCLOG.flush()

        return None

    def _flush(self):
        """
        Flush the input buffer by calling self._read() until no data is returned. If there's a socket error, or a serial
        communications error, then close and re-open the socket.
        """
        ltime = time.time()
        with self.readlock:
            gtime = time.time()
            if gtime - ltime > 0.05:
                self.logger.debug('%d: %5.3f seconds to get lock in _flush' % (threading.get_ident(),
                                                                               gtime - ltime))
            data = b''
            newdata = b'X'
            try:
                while newdata:
                    newdata = self._read(nbytes=1000)
                    data += newdata
            except:
                self.logger.exception('Exception while flushing input buffer, re-opening comms object')
                time.sleep(1.0)
                self._open()

        if PCLOG:
            PCLOG.write('%14.3f %d: Flushed %s."\n' % (time.time(),
                                                       threading.get_ident(),
                                                       data))
            PCLOG.flush()

    def _send_reset_as_master(self, message):
        """
        Calculate the LRC and send a reset message (as a list of bytes) to the socket 'self.sock'.
        We cannot expect a response to this, since the microprocessor we're talking to will execute a reset
        killing any response before it gets out. We're therefore sending in the blind and assuming it worked!
        """

        fullmessage = message + getlrc(message)
        modbusstring = ':' + to_ascii(fullmessage)
        self.logger.debug('_send_reset_as_master(): %s' % modbusstring)
        self._write((modbusstring + '\r\n').encode('ascii'))

    def _send_as_master(self, message):
        """
        Calculate the CRC and send it and the message (a list of bytes) to the socket 'self.sock'.
        Return a bytelist containing any valid reply (without the CRC), or 'False' if there was no
        reply within TIMEOUT seconds, or if the reply had an invalid CRC.

        This method will always either return a list of bytes, or throw an exception.

        If the wrong protocol is defined in the PROTOCOL global, it will throw ValueError.
        If a socket or serial exception is thrown by the underlaying communications layer, that exception will be logged and re-raised.
        If no reply is received in TIMEOUT seconds, an IOError is raised.

        :param message: A list of integers, each in the range 0-255
        :return: A list of integers, each in the range 0-255, or False if no valid reply was received
        """
        self._flush()   # Get rid of any old data in the input queue, and close/re-open the socket if there's an error
        self.logger.debug('_send_as_master(): %s' % message)
        fullmessage = message + getlrc(message)
        self._write((':' + to_ascii(fullmessage) + '\r\n').encode('ascii'))

        replist = []  # Entire message, including CRC, as a list of integers
        datalist = []  # Message without CRC byte/s
        stime = time.time()
        mstring = ''   # ASCII hex packet contents, in ASCII protocol. Empty string otherwise
        crcgood = False

        # Wait until the timeout trips, or until we have a packet delimited by ':' and '\r\n'
        while ( ( ((time.time() - stime < TIMEOUT + 1) and mstring) or
                  ((time.time() - stime < TIMEOUT) and not mstring) ) and
                (not mstring.endswith('\r\n')) ):
            try:
                # Strip off any characters that are not valid Modbus/ASCII - they will be line errors from PDoC turn-on transients
                reply_bytes = bytes([c for c in self._read(until=b'\r\n', nbytes=1000) if c in VALID_BYTES])
                # Convert the bytes object to a string, now that we know everything left is Modbus/ASCII
                reply_raw = reply_bytes.decode('ascii')
                reply = ''.join([x for x in reply_raw if x != chr(0)])
                if reply != reply_raw:
                    self.logger.debug('%d Nulls removed from %s' % (len(reply_raw) - len(reply), repr(reply)))
                if (not mstring) and reply and not (reply.startswith(':')):   # Unexpected first character, ignore it and keep reading
                    self.logger.debug('%d: %d bytes: ?"%s"' % (threading.get_ident(),
                                                               len(reply),
                                                               repr(reply)))
                    time.sleep(0.001)
                    continue
                mstring += reply
            except UnicodeDecodeError:
                self.logger.debug('%d: ??' % (threading.get_ident()))
                pass  # Ignore non-ascii characters
            except:
                self.logger.exception('Exception in sock.recv()')
                raise
            time.sleep(0.001)

        if len(mstring) > 3 and mstring.startswith(':') and mstring.endswith('\r\n'):
            try:
                replist = from_ascii(mstring[1:-2])
            except ValueError:   # Non ASCII-hex characters in reply
                self.logger.error('Non ASCII-Hex characters in reply: %s' % mstring[1:-2])
                raise IOError
            if getlrc(message=replist[:-1]) == [replist[-1],]:
                crcgood = True
                datalist = replist[:-1]
        elif mstring:
            self.logger.debug('Packet fragment received by send_as_master() after %f: %s' % (time.time() - stime, mstring))
        else:
            self.logger.debug('No data received by send_as_master() after %f: %s' % (time.time() - stime, mstring))

        self.logger.debug("Recvd: %s/%s" % (mstring.rstrip(), str(replist)))
        if crcgood:
            return datalist
        else:
            self.logger.debug('No valid reply - raw data received: %s' % str(replist))
            raise IOError

    def _send_reply(self, message):
        """
        Calculate the CRC and send it and the message (a list of bytes) to the socket 'self.sock'.
        Do not wait for a reply, because this _is_ a reply (we're acting as a Modbus slave).

        :param message: A list of bytes, each in the range 0-255
        :return: None
        """
        self.logger.debug("%d: _send_reply: %s" % (threading.get_ident(), message))
        # self._flush()  # Get rid of any old data in the input queue, and close/re-open the socket if there's an error
        fullmessage = message + getlrc(message)
        self._write((':' + to_ascii(fullmessage) + '\r\n').encode('ascii'))
        self.logger.debug("%d: _send_reply finished" % (threading.get_ident()))

    def listen_for_packet(self, listen_address, slave_registers, maxtime=10.0, validation_function=dummy_validate):
        """
        Listen on the socket for an incoming read/write register packet sent by an external bus master (eg, a technician
        in the field). Handle one read/write register call by sending or modifying the contents of the registers passed
        in the 'slave_registers' dictionary. Exit after 'maxtime' seconds, or after processing one valid packet, whichever
        comes first. Note that if a packet results in an exception reply (invalid register number, invlaid data, etc),
        then it will continue waiting for a valid packet until the maxtime elapses.

        NOTE - the slave_registers dictionary will be modified in place with the results of any packet that results
               in a valid register write. If a register write fails, because of an invalid register number, or because
               the validation function returns False, then the slave_registers dict is left unchanged.

        :param listen_address: Modbus address to listen for packets on.
        :param slave_registers: A dictionary with register number (1-9999) as the key, and an integer (0-65535) as the
                                value. Modified in-place by packets that write registers (0x06 or 0x10).
        :param maxtime: Maximum time to listen for, in seconds.
        :param validation_function: Function to call to validate slave_registers contents. If this validation_function
                                    returns false, reply to the sender with an 'Illegal Data Value' exception. .
        :return: A tuple (read_set, written_set) - two sets containing all the register numbers that were read-from or
                 written-to by the packet processed in this call to listen_for_packet().
        """
        registers_backup = slave_registers.copy()   # store a copy of all the slave registers passed in on entry
        start_time = time.time()

        while time.time() < (start_time + maxtime):  # Wait for a good packet until we run out of time
            msglist = []  # Message without CRC byte/s
            mstring = ''  # ASCII hex packet contents, in ASCII protocol. Empty string otherwise
            crcgood = False
            # Wait until the timeout trips, or until we have a packet delimited by ':' and '\r\n'
            while ( ( ((time.time() - start_time < maxtime + 1) and mstring) or
                      ((time.time() - start_time < maxtime) and not mstring) ) and
                    (not mstring.endswith('\r\n')) ):
                try:
                    reply = self._read(until=b'\r\n', nbytes=1000).decode('ascii')
                    if (not mstring) and reply and not (reply.startswith(':')):  # Unexpected first character, ignore it and keep reading
                        self.logger.debug('%d: ?"%s"' % (threading.get_ident(), reply))
                        time.sleep(0.001)
                        continue
                    mstring += reply
                except UnicodeDecodeError:
                    self.logger.debug('%d: ??' % (threading.get_ident()))
                    time.sleep(0.001)
                    pass   # Ignore non-ascii characters
                except:
                    self.logger.exception('Exception in sock.recv()')
                    raise
                time.sleep(0.001)

            if len(mstring) > 3 and mstring.startswith(':') and mstring.endswith('\r\n'):
                try:
                    replist = from_ascii(mstring[1:-2])
                except ValueError:  # Non ASCII-hex characters in reply
                    self.logger.error('Non ASCII-Hex characters in reply: %s' % mstring[1:-2])
                    raise IOError
                if getlrc(message=replist[:-1]) == [replist[-1],]:
                    crcgood = True
                    msglist = replist[:-1]
            elif mstring:
                self.logger.debug('Packet fragment received: %s' % mstring)
                time.sleep(0.2)
                self._flush()  # Get rid of any old data in the input queue, and close/re-open the socket if there's an error
                continue  # Discard this packet fragment, keep waiting for a new valid packet
            else:
                continue   # It's not an error to not receive a packet, because we're in slave mode

            if not msglist:
                return set(), set()

            self.logger.debug("%d: Received: %s=%s" % (threading.get_ident(), mstring, str(msglist)))

            if ((0 < len(msglist) < 3) or (not crcgood)):
                self.logger.warning('Packet Fragment received: %s' % msglist)
                time.sleep(0.2)
                self._flush()  # Get rid of any old data in the input queue, and close/re-open the socket if there's an error
                return set(), set()    # Discard this packet fragment, return control to the caller

            # Handle the packet contents here
            if msglist[0] != listen_address:
                if self.multidrop:
                    self.logger.debug('Packet received by %d, but it was addressed to station %d' % (listen_address, msglist[0]))
                else:
                    self.logger.info('Packet received by %d, but it was addressed to station %d' % (listen_address, msglist[0]))
                return set(), set()    # Discard this packet, return control to the caller

            if msglist[1] == 0x03:   # Reading one or more registers
                regnum = msglist[2] * 256 + msglist[3] + 1   # Packet contains register number - 1
                numreg = msglist[4] * 256 + msglist[5]
                replylist = [listen_address, 0x03, numreg * 2]
                read_set = set()
                read_error = False
                for r in range(regnum, regnum + numreg):   # Iterate over all requested registers
                    if r not in slave_registers:
                        read_error = True
                        self.logger.error('Bad read register: %d' % r)
                    else:
                        replylist += list(divmod(slave_registers[r], 256))
                        read_set.add(r)
                if read_error:
                    replylist = [listen_address, 0x83, 0x02]  # 0x02 is 'Illegal Data Address'
                    self._send_reply(replylist)
                    self.logger.error('Reading unknown register not allowed, returned exception packet %s' % (replylist,))
                    return set(), set()    # Discard this packet, return control to the caller
                self._send_reply(replylist)
                return read_set, set()
            elif msglist[1] == 0x06:  # Writing a single register
                regnum = msglist[2] * 256 + msglist[3] + 1   # Packet contains register number - 1
                value = msglist[4] * 256 + msglist[5]
                if regnum in slave_registers:
                    slave_registers[regnum] = value
                else:
                    replylist = [listen_address, 0x86, 0x02]   # 0x02 is 'Illegal Data Address'
                    self.logger.error('Writing register %d not allowed, returned exception packet %s.' % (regnum, replylist))
                    self._send_reply(replylist)
                    return set(), set()    # Return, indicating that the packet did nothing

                if (validation_function is not None) and (not validation_function(slave_registers=slave_registers)):
                    slave_registers[regnum] = registers_backup[regnum]   # Put back the original contents of that register
                    replylist = [listen_address, 0x86, 0x03]  # 0x03 is 'Illegal Data Value'
                    self.logger.error('Inconsistent register values, returned exception packet %s.' % (replylist,))
                    self._send_reply(replylist)
                    return set(), set()  # Return, indicating that the packet did nothing
                else:
                    self._send_reply(msglist)    # For success, reply with the same packet
                    return set(), {regnum}

            elif msglist[1] == 0x10:  # Writing multiple registers
                regnum = msglist[2] * 256 + msglist[3] + 1   # Packet contains register number - 1
                numreg = msglist[4] * 256 + msglist[5]
                numbytes = msglist[6]
                bytelist = msglist[7:]

                assert len(bytelist) == numbytes == (numreg * 2)
                written_set = set()
                write_error = False
                for r in range(regnum, regnum + numreg):
                    if r not in slave_registers:
                        write_error = True
                        self.logger.error('Bad write register: %d' % r)
                    else:
                        value = bytelist[0] * 256 + bytelist[1]
                        bytelist = bytelist[2:]   # Use, then pop off, the first two bytes
                        slave_registers[r] = value
                        written_set.add(r)

                if write_error:
                    for r2 in range(regnum, regnum + numreg):
                        if r2 in slave_registers:
                            slave_registers[r2] = registers_backup[r2]
                    replylist = [listen_address, 0x90, 0x02]  # 0x02 is 'Illegal Data Address'
                    self._send_reply(replylist)
                    self.logger.error('Writing unknown register/s not allowed, returned exception packet %s.' % (replylist,))
                    return set(), set()    # Return, indicating that the packet did nothing

                if (validation_function is not None) and (not validation_function(slave_registers=slave_registers)):
                    for r in range(regnum, regnum + numreg):
                        slave_registers[r] = registers_backup[r]
                    replylist = [listen_address, 0x86, 0x03]  # 0x03 is 'Illegal Data Value'
                    self._send_reply(replylist)
                    self.logger.error('Inconsistent register values, returned exception packet %s.' % (replylist,))
                    return set(), set()  # Return, indicating that the packet did nothing
                else:
                    replylist = [listen_address, 0x10] + NtoBytes(regnum - 1, 2) + NtoBytes(numreg, 2)
                    self._send_reply(replylist)
                    return set(), written_set
            else:
                self.logger.error('Received modbus packet for function %d - not supported.' % msglist[1])
                replylist = [listen_address, msglist[1] + 0x80, 0x01]
                self._send_reply(replylist)
                return set(), set()  # Return, indicating that the packet did nothing

        return set(), set()

    def readReg(self, modbus_address, regnum, numreg=1):
        """
        Given a register number and the number of registers to read, return the raw register contents
        of the desired register/s.

        This function will always either return a list of register value tuples from a validated packet, or throw an exception.

        If a validated packet is received, but that packet is a Modbus exception, then ValueError is raised, indicating
        a problem with the packet contents, as parsed by the remote device.

        If no reply is received after retrying, or only a corrupted reply was received, then IOError is raised,
        indicating a communications problem with the remote device.

        :param modbus_address: MODBUS station number, 0-255
        :param regnum: Register number to read
        :param numreg: Number of registers to read (default 1)
        :return: A list of register values, each a tuple of (MSB, LSB), where MSB and LSB are integers, 0-255
        """

        packet = [modbus_address, 0x03] + NtoBytes(regnum - 1, 2) + NtoBytes(numreg, 2)
        stime = time.time()  # When we started trying to read the register
        while (time.time() - stime) < (TIMEOUT * 4):
            try:
                reply = self._send_as_master(packet)
            except ValueError:  # Bad protocol global
                raise
            except:  # No reply, or error from the communications layer
                self.logger.debug('Communications error in send_as_master, resending.')
                time.sleep(1)
                self._flush()
                continue

            if not reply:
                self.logger.debug('No reply to readReg from initial packet, resending.')
                time.sleep(1)
                self._flush()
                continue

            if reply[0] != modbus_address:
                errs = "Sent to station %d, but station %d responded. Resending.\n" % (modbus_address, reply[0])
                errs += "Packet: %s\n" % str(reply)
                self.logger.error(errs)
                time.sleep(1)
                self._flush()
                continue

            if reply[1] != 3:
                if reply[1] == 0x83:
                    excode = reply[2]
                    if excode == 2:
                        self.logger.error("Exception 0x8302: Invalid register address. Aborting.")
                    elif excode == 3:
                        self.logger.error("Exception 0x8303: Register count <1 or >123. Aborting.")
                    elif excode == 4:
                        self.logger.error("Exception 0x8304: Read error on one or more registers. Aborting.")
                    elif excode == 11:
                        self.logger.error("Exception 0x830b: Gateway detected a missing response from client. Aborting.")
                        raise IOError    # It's a communications failure, not a protocol error
                    else:
                        self.logger.error("Exception %s: Unknown exception. Aborting." % (hex(excode + 0x83 * 256),))
                    raise ValueError
                errs = "Unexpected reply received. Resending.\n"
                errs += "Packet: %s\n" % str(reply)
                self.logger.error(errs)
                time.sleep(1)
                self._flush()
                continue

            if len(reply) > 4:
                blist = reply[3:]
                return [(blist[i], blist[i+1]) for i in range(0, len(blist), 2)]
            else:
                errs = "Short reply received. Resending.\n"
                errs += "Packet: %s\n" % str(reply)
                self.logger.error(errs)
                time.sleep(1)
                self._flush()
                continue

        self.logger.error('No valid reply received for readReg(). Giving up.')
        raise IOError

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
            self.logger.error('Unexpected register value: %s' % value)
            return False

        packet = [modbus_address, 0x06] + NtoBytes(regnum - 1, 2) + valuelist

        stime = time.time()
        while (time.time() - stime) < (TIMEOUT * 4):
            try:
                reply = self._send_as_master(packet)
            except ValueError:  # Bad protocol global
                raise
            except:  # No reply, or error from the communications layer
                self.logger.debug('Communications error in send_as_master, resending.')
                time.sleep(1)
                self._flush()
                continue

            if not reply:
                self.logger.debug('No reply from send_as_master, resending.')
                time.sleep(1)
                self._flush()
                continue

            if reply[0] != modbus_address:
                errs = "Sent to station %d, but station %d responded.\n" % (modbus_address, reply[0])
                errs += "Packet: %s\n" % str(reply)
                self.logger.error(errs)
                time.sleep(1)
                self._flush()
                continue

            if reply[1] != 6:
                if reply[1] == 0x86:
                    excode = reply[2]
                    if excode == 2:
                        self.logger.error("Exception 0x8602: Invalid register address")
                    elif excode == 3:
                        self.logger.error("Exception 0x8603: Register value out of range")
                    elif excode == 4:
                        self.logger.error("Exception 0x8604: Write error on one or more registers")
                    elif excode == 11:
                        self.logger.error("Exception 0x860b: Gateway detected a missing response from client. Aborting.")
                        raise IOError    # It's a communications failure, not a protocol error
                    else:
                        self.logger.error("Exception %s: Unknown exception" % (hex(excode + 0x86 * 256),))
                    raise ValueError
                errs = "Unexpected reply received.\n"
                errs += "Packet: %s\n" % str(reply)
                self.logger.error(errs)
                time.sleep(1)
                self._flush()
                continue

            if reply != packet:  # The _send_as_master() method adds the CRC to the packet list, in place, so strip it
                self.logger.error('writeReg: %s != %s' % (reply, packet))
                time.sleep(1)
                self._flush()
                continue   # Value returned is not equal to value written

            return True

        self.logger.error('Too many errors in writeReg, giving up.')
        return False

    def writeReset(self, modbus_address, regnum, value):
        """
        This is a special case of writeReg()
        Have to handle this specially since nobody is going to reply
        """

        if type(value) == int:
            valuelist = NtoBytes(value, 2)
        elif (type(value) == list) and (len(value) == 2):
            valuelist = value
        else:
            self.logger.error('Unexpected register value: %s' % value)
            return

        packet = [modbus_address, 0x06] + NtoBytes(regnum - 1, 2) + valuelist

        try:
            self._send_reset_as_master(packet)
        except ValueError:
            raise
        except:
            self.logger.debug('Communications error in send_reset_as_master, giving up.')
            time.sleep(1)
            self._flush()
            return
        
        self.logger.debug('Reset command sent.')

    def writeMultReg(self, modbus_address, regnum, valuelist):
        """
        Given a starting register number and a list of bytes, write the data to the given register
        in the given modbus station. Return True if the write succeeded, return False if the
        reply doesn't match the data written, and return None if there is any other error.

        :param modbus_address: MODBUS station number, 0-255
        :param regnum: Register number to read
        :param valuelist: A list of register values to write. To write to multiple consecutive registers, pass a list with
                          more than 1 value. Each value can be a single integer (passed as a 16-bit value, MSB first), or
                          a tuple or list of (MSB, LSB), where MSB and LSB are integers (each 0-255).
        :return: True for success, False if there is an unexpected value in the reply, or None for any other error
        """
        data = []
        for value in valuelist:
            if type(value) == int:
                data += NtoBytes(value, 2)   # Convert a 16-bit integer to a list of two bytes, and append it
            elif ((type(value) == list) or (type(value) == tuple)) and (len(value) == 2):
                data += list(value)   # Append a list of two bytes as individual values (and convert to a list if given a tuple)
            else:
                self.logger.error('Unexpected register value: %s' % value)
                return None

        rlen = len(data) // 2   # data is now a list of individual 8-bit bytes, but rlen is the number of registers
        packet = [modbus_address, 0x10] + NtoBytes(regnum - 1, 2) + NtoBytes(rlen, 2) + NtoBytes(rlen * 2, 1) + data

        stime = time.time()
        while (time.time() - stime) < (TIMEOUT * 4):
            try:
                reply = self._send_as_master(packet)
            except ValueError:  # Bad protocol global
                raise
            except:  # No reply, or error from the communications layer
                self.logger.debug('Communications error in send_as_master, resending.')
                time.sleep(1)
                self._flush()
                continue

            if not reply:
                self.logger.debug('No reply from send_as_master, resending.')
                time.sleep(1)
                self._flush()
                continue

            if reply[0] != modbus_address:
                errs = "Sent to station %d, but station %d responded.\n" % (modbus_address, reply[0])
                errs += "Packet: %s\n" % str(reply)
                self.logger.error(errs)
                time.sleep(1)
                self._flush()
                continue

            if reply[1] != 0x10:
                if reply[1] == 0x90:
                    excode = reply[2]
                    if excode == 2:
                        self.logger.error("Exception 0x9002: Starting or ending register address invalid")
                    elif excode == 3:
                        self.logger.error("Exception 0x9003: Register count <1 or >123, or bytecount<>rlen*2")
                    elif excode == 4:
                        self.logger.error("Exception 0x9004: Write error on one or more registers")
                    elif excode == 11:
                        self.logger.error("Exception 0x900b: Gateway detected a missing response from client. Aborting.")
                        raise IOError    # It's a communications failure, not a protocol error
                    else:
                        self.logger.error("Exception %s: Unknown exception" % (hex(excode + 0x90 * 256),))
                    raise ValueError
                errs = "Unexpected reply received.\n"
                errs += "Packet: %s\n" % str(reply)
                self.logger.error(errs)
                time.sleep(1)
                self._flush()
                continue

            if (reply[2:4] != NtoBytes(regnum - 1, 2)) or (reply[4:6] != NtoBytes(rlen, 2)):
                time.sleep(1)
                self._flush()
                continue  # start/number returned is not equal to regnum/rlen written

            return True

        self.logger.error('Too many errors in writeMultReg, giving up.')
        return False


class ModbusDevice(object):
    """
    Generic parent class for all modbus slaves that the MCCS can communicate with.

    Child objects will be SMARTbox units themselves, and the FNDH controller.
    """
    def __init__(self, conn=None, modbus_address=None, logger=None):
        self.conn = conn
        self.modbus_address = modbus_address
        self.reg_version = None
        self.register_map = {}
        if logger is None:
            self.logger = logging.getLogger('SB.%d' % modbus_address)
        else:
            self.logger = logger


###################################
# Utility functions
#

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
            raise ValueError('Unexpected value - must be an int or 2-tuple: %s' % value)

    nbytes = len(data)
    if nbytes != 2 * (nbytes // 2):
        raise ValueError('Odd number of bytes to convert: %s' % valuelist)

    return sum([data[i] * (256 ** (nbytes - i - 1)) for i in range(nbytes)])


def getlrc(message=None):
    """
    Calculate and returns the LRC byte required for 'message' (a list of bytes).

    :param message: A list of bytes, each in the range 0-255
    :return: A list of one integer, in the range 0-255
    """
    if not message:
        return 0
    lrc = (0 - sum(message)) & 0xFF   # Twos-complement of the sum of the message bytes, masked to 8 bits
    return [lrc, ]


def to_ascii(message=None):
    """
    Take a message list (a list of integers) and convert each integer to an a two-character ASCII hex value. Return
    as a string.

    :param message: A list of integers, each 0-255
    :return: A string containing the ASCII hex representation of all the integers in the list.
    """
    if (min(message) < 0) or max(message) > 255:
        raise ValueError

    return ''.join(['%02X' % v for v in message])


def from_ascii(mstring):
    """
    Take a string full of ASCII-hex values (and nothing else), and convert it to a list of integers, each 0-255.

    :param mstring: A string of letters, each 0-9, or A-F, or a-f. String must have an even number of characters.
    :return: A list of integers, each 0-255
    """
    data = mstring.upper()
    numbytes, remainder = divmod(len(data), 2)
    if remainder != 0:
        raise ValueError

    return [int(data[i] + data[i + 1], 16) for i in range(0, numbytes * 2, 2)]
