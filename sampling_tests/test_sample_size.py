#!/usr/bin/env python

import logging
import sys
import zlib
import time

LOGFILE = 'test_sample.log'


if __name__ == '__main__':
    print('Test Sample Size')
    
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
    conn = transport.Connection(hostname=None, devicename='COM5', multidrop=False, logger=tlogger, baudrate=19200)

    slogger = logging.getLogger('SB:%d' % 1)
    s = smartbox.SMARTbox(conn=conn, modbus_address=1, logger=slogger)
    print('Polling SMARTbox as "s" on address %d.' % 1)
    s.poll_data()
#    print('Configuring SMARTbox as "s" on address %d.' % 1)
#    s.configure()
#    s.poll_data()
#    print(s)

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
# The COMMAND register must always be the last register written.  This is why it has the highest address
# of all the data comprising a command from CRC upwards.  This works well for bulk multi-register writes
# of program data as the entire 125 registers are sent in one write instruction.
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

#######################################

    print("Issuing sample size command...")

    s.conn.writeReg(modbus_address=1, regnum=10125, value=10)  # sample size command

    result = s.conn.readReg(modbus_address=1, regnum=10126)[0][1]  # results register
    if result == 0:
        print("Result ok.")

        sampleSize = s.conn.readReg(modbus_address=1, regnum=10127)[0]
        print("sample size: " + str(sampleSize[0] * 256 + sampleSize[1]) + " words sample capacity.")
        
    else:
        print("command failed: " + str(result))

    
