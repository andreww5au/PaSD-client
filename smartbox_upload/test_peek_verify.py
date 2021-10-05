#!/usr/bin/env python

import logging
import sys
import zlib
from intelhex import IntelHex
import time

LOGFILE = 'test_upload.log'


if __name__ == '__main__':
    loglevel = logging.INFO

    fh = logging.FileHandler(filename=LOGFILE, mode='w')
    fh.setLevel(logging.DEBUG)   # All log messages go to the log file
    sh = logging.StreamHandler()
    sh.setLevel(loglevel)        # Some or all log messages go to the console
    # noinspection PyArgumentList
    logging.basicConfig(handlers=[fh, sh],
                        level=logging.DEBUG,
                        format='%(levelname)s:%(name)s %(created)14.3f - %(message)s')

    from pasd import transport
    from pasd import smartbox

    tlogger = logging.getLogger('T')
    conn = transport.Connection(hostname=None, devicename='COM6', multidrop=False, logger=tlogger, baudrate=115200)

    slogger = logging.getLogger('SB:%d' % 1)
    s = smartbox.SMARTbox(conn=conn, modbus_address=1, logger=slogger)
    print('Polling SMARTbox as "s" on address %d.' % 1)
    s.poll_data()
#    print('Configuring SMARTbox as "s" on address %d.' % 1)
#    s.configure()
#    s.poll_data()
    print(s)

# System registers
#
# PEEK_ROM_COMMAND = 6
#
# COMMAND 10125
# RESULT_DATA 10126   This is the base address to read peek results from


#######################################
#
# This is very slow but shows an example of how to peek into the Smartbox ROM and compare result to hex file
    print("Reading rom hex file")
    ih = IntelHex("test_rom1.hex")

    print("Segments found:")
    print(ih.segments())

    numWrites = 0  # number of write chunks.  This is used for verifying

    for segment in ih.segments():
        start = segment[0]
        end = segment[1]
        if start < 0x1003000:   # this is the magic dual partition boot config that should never be changed FBOOT
            print("Segment: " + str(start) + " - " + str(end))    # in bytes
            address = start
            while address < end:
                fileValue = ih[address] | (ih[address + 1] << 8) | (ih[address + 2] << 16)

                # peek in bank 0 (active boot) ROM
                romAddress = address >> 1
                regValues = [romAddress & 0xffff, romAddress >> 16, 6]
                s.conn.writeMultReg(modbus_address=1, regnum=10125 - 2, valuelist=regValues)
                peekResult = s.conn.readReg(modbus_address=1, regnum=10126 + 1, numreg=2)
                peekValue = peekResult[0][1] | (peekResult[0][0] << 8) | (peekResult[1][1] << 16)

                # peek the alternate bank (0x400000 offset)
                romAddress = (address >> 1) + 0x400000
                regValues = [romAddress & 0xffff, romAddress >> 16, 6]
                s.conn.writeMultReg(modbus_address=1, regnum=10125 - 2, valuelist=regValues)
                peekResult = s.conn.readReg(modbus_address=1, regnum=10126 + 1, numreg=2)
                altPeekValue = peekResult[0][1] | (peekResult[0][0] << 8) | (peekResult[1][1] << 16)

                if peekValue != fileValue or altPeekValue != fileValue:
                    print("mismatch at " + hex(romAddress) + ": " + hex(fileValue) + ", " + hex(peekValue) + ", " + hex(altPeekValue))
                
                # and do the next address
                address += 4
