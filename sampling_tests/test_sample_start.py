#!/usr/bin/env python

import logging
import sys
import zlib
from intelhex import IntelHex
import time

LOGFILE = 'test_upload.log'


if __name__ == '__main__':
    loglevel = logging.INFO

    print("Test Sample Start")

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
    conn = transport.Connection(hostname=None, devicename='COM5', multidrop=False, logger=tlogger, baudrate=19200)

    slogger = logging.getLogger('SB:%d' % 1)
    s = smartbox.SMARTbox(conn=conn, modbus_address=1, logger=slogger)
    print('Polling SMARTbox as "s" on address %d.' % 1)
    s.poll_data()
#    print('Configuring SMARTbox as "s" on address %d.' % 1)
#    s.configure()
#    s.poll_data()
#   print(s)

# System registers
#
# CRC registers.  CRC32 is computed for all registers from ADDRESS to COMMAND, or 10003 - 10125.
# If a command does not write to all registers the CRC is still calculated as if all the registers are initialised with 0
# The CRC is calculated lower byte then upper byte
#
# CRC_LOW 10001
# CRC_HIGH 10002
#
#
# Address of program address to write to.  The count (in registers) is stored in the upper byte of ADDRESS_HIGH_COUNT
#
# ADDRESS_LOW 10003
# ADDRESS_HIGH_COUNT 10004
#
#
# Registers containing program data are store in SEGMENT_DATA.  As the PIC24 has 24-bit instructions these
# are packed - lower (L), middle (M), upper (U) - into the data registers as follows.  For example, 3
# instructions 0, 1, 2 would be stored in registers 10005-9 as follows:
#
# 10005: M0L0  (L0 in lower byte of 10008, M0 in upper byte of 10008)
# 10006: L1U0  (U0 in lower byte of 10006
# 10007: U1M1
# 10008: M2L2
# 10009: U2  (upper byte of 10008 is wasted)
#
# SEGMENT_DATA 10005 - 10124,  120 words of data
#
#
# SAMPLING COMMANDS
#
# Sampling happens asynchronously via a number of commands.  A SAMPLE_START_COMMAND is used to initiate a sampling sequence.
# While this happens, SAMPLE_STATE_COMMAND can be polled for completion, degree complete (SAMPLE_COUNT_COMMAND).  When sampling is complete
# data may be read using SAMPLE_READ_COMMAND although if you keep track of SAMPLE_COUNT_COMMAND you can read right up to the last sample completed.
#
#   SAMPLE_START_COMMAND 7 = start sampling.  The sample parameters are in SEGMENT_DATA
#   SAMPLE_STOP_COMMAND 8  = stop sampling (if running)
#   SAMPLE_STATE_COMMAND 9 = get the sample state
#   SAMPLE_SIZE_COMMAND 10 = get the size of the sampling buffer, result in RESULT_DATA1
#   SAMPLE_READ_COMMAND 11 = read a chunk of sample data
#   SAMPLE_COUNT_COMMAND 12 = read which sampleCount it is up to
#
# COMMAND 10125
#
# For SAMPLE_START_COMMAND, parameters are:
#
# ADDRESS_LOW_REGISTER contains low 16-bits of sampling period in milliseconds
# ADDRESS_HIGH_REGISTER contains high 16-bits of sampling period
#
# SEGMENT_DATA contains number of n registers to sample
# SEGMENT_DATA + 1 contains ModBus address of register 0
# ...
# SEGMENT_DATA + n contains Modbus address of register n - 1
#
#
# The result register has to be separately read as it doesn't map onto MODBUS codes.  It contains
# the result of the last command executed.
#
# RESULT 10126
#
# Result codes:
# 0 = OK
# 1 = ERROR
# 2 = CRC_ERROR
# 3 = UNKNOWN_COMMAND

# this is a pain.  In order to calculate CRC32 we need to give zlib.crc32() an array of bytes
# The CRC is calculated for registers ADDRESS_LOW to COMMAND and these are stored in these
# 246 bytes least significant byte first.
    registerBytes = bytearray(246) # is this auto-zeroed in Python?  Why am I clearing it?

    for i in range(0, 246):  # zot
        registerBytes[i] = 0

    # for sampling, addressLow contains low 16-bits of sample period in milliseconds, addressHigh contains high 16-bits
    # for test, make it every 10ms period
    addressLow = 10
    addressHigh = 0

    # start with so-called address words (which now store log period)
    registerBytes[0] = addressLow & 0xff
    registerBytes[1] = addressLow >> 8
    registerBytes[2] = addressHigh & 0xff
    registerBytes[3] = addressHigh >> 8

    # now, we are into segment data.  Let's record 5 registers.  This is SEGMENT_DATA register which stores number of things to read
    registerBytes[4] = 5
    registerBytes[5] = 0

    # SYS_PSU_V for SEGMENT_DATA1
    registerBytes[6] = 18
    registerBytes[7] = 0

    # P01_CURRENT for SEGMENT_DATA2
    registerBytes[8] = 48
    registerBytes[9] = 0

    # P02_CURRENT for SEGMENT_DATA3
    registerBytes[10] = 49
    registerBytes[11] = 0

    # P03_CURRENT for SEGMENT_DATA4
    registerBytes[12] = 50
    registerBytes[13] = 0

    # P04_CURRENT for SEGMENT_DATA5
    registerBytes[14] = 51
    registerBytes[15] = 0

    numWords = 8;  # just number of words for all of above:  addressLow to whichever SEGMENT_DATA written

    # and the sample start command
    registerBytes[244] = 7   # least sig byte of COMMAND register

    # now, calc crc
    crc32 = zlib.crc32(registerBytes)

    # and build a list for multiwrite
    regValues=[crc32 & 0xffff, crc32 >> 16]
    for i in range(0, numWords):
        regValues.append(registerBytes[i * 2] + (registerBytes[i * 2 + 1] << 8))

    print("writing partial chunk...")
    s.conn.writeMultReg(modbus_address=1, regnum=10001, valuelist=regValues)
    s.conn.writeReg(modbus_address=1, regnum=10125, value=7)  # start sample command

    # read result
    result = s.conn.readReg(modbus_address=1, regnum=10126)[0][1]  # results register
    if result == 0:
        print("Sampling started.")
    else:
        print("command failed: " + str(result))
