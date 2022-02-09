#!/usr/bin/env python

import logging
import sys
import zlib
from intelhex import IntelHex
import time

LOGFILE = 'test_upload.log'


if __name__ == '__main__':
    loglevel = logging.INFO

    print("Test Sample Read")

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

# first we read how many samples there are
    print("Issuing sample count command...")

    s.conn.writeReg(modbus_address=1, regnum=10125, value=12)  # sample size command

    result = s.conn.readReg(modbus_address=1, regnum=10126)[0][1]  # results register
    if result == 0:
        print("Result ok.")

        sampleRead = s.conn.readReg(modbus_address=1, regnum=10127)[0]
        sampleCount = sampleRead[0] * 256 + sampleRead[1]   # number of sets of samples
        print("sample count: " + str(sampleCount))

        # at this point we know how many words to read because in
        # test_sample_start we specified 5 registers.  I could return all this in
        # register reads but that doesn't make much sense to...
        numWords =  sampleCount * 5
        resultArray = [0] * numWords  # bizarre...  this is outside my comfort zone...

        # for simple maths, let's poll 100 words at a time even though it could be 124
        numFullReads = numWords // 100
        extraReads = numWords - numFullReads * 100

        # do the full samples
        for i in range(0, numFullReads):
            startAddress = i * 100;
            regValues = [startAddress, 100, 11]  # the starting address, number of words to read and the read command (11)
            s.conn.writeMultReg(modbus_address=1, regnum=10123, valuelist=regValues)   # 10123 = COMMAND_REGISTER - 2.  The 2 bytes before it denote starting address and num words to read
            result = s.conn.readReg(modbus_address=1, regnum=10126)[0][1]  # results register
            if result == 0:
                #print("Read chunk: " + str(i))
                data = s.conn.readReg(modbus_address=1, regnum=10001, numreg=104)  # 104 because 2 CRC words, 2 address words + 100 words data
                #print(data)
                
                # get the CRC
                crcLow = data[0][0] * 256 + data[0][1]
                crcHigh = data[1][0] * 256 + data[1][1]

                # check address/count for matches
                readAddress = data[2][0] * 256 + data[2][1]
                readCount = data[3][0] * 256 + data[3][1]
                print("readAddress: " + str(readAddress))
                #print("readCount: " + str(readCount))
                if readAddress != startAddress or readCount != 100:   # magic 100...
                    print("mismatch in return address and/or size")
                    exit()

                # and the happy fun CRC
                registerBytes = bytearray(102 * 2)
                for j in range(0, 102):   # 2 X Address + 100 words
                    registerBytes[j * 2] = data[j + 2][1]    # + 2 to skip CRC
                    registerBytes[j * 2 + 1] = data[j + 2][0]
                crc32 = zlib.crc32(registerBytes)
                if (crc32 >> 16) != crcHigh or (crc32 & 0xffff) != crcLow:
                    print("crc error on read")
                    print("low: " + str(crcLow) + " mcu:" + str(crc32 & 0xffff))
                    print("high: " + str(crcHigh) + " mcu:" + str(crc32 >> 16))
                    exit()
                
                
                for j in range(0, 100):  # copy to results array
                    resultArray[startAddress + j] = data[4 + j][0] * 256 + data[4 + j][1]
            else:
                print("read failed: " + str(result))
                exit();

        # and the partial sample if there is one
        if extraReads > 0:
            startAddress = numFullReads * 100;
            regValues = [startAddress, extraReads, 11]  # the starting address, number of words to read and the read command (11)
            s.conn.writeMultReg(modbus_address=1, regnum=10123, valuelist=regValues)   # 10123 = COMMAND_REGISTER - 2.  The 2 bytes before it denote starting address and num words to read
            result = s.conn.readReg(modbus_address=1, regnum=10126)[0][1]  # results register
            if result == 0:
                print("Extra samples: " + str(extraReads))
                data = s.conn.readReg(modbus_address=1, regnum=10001, numreg=(4 + extraReads))  # 2 CRC words, 2 address words + extraReads words data
                # print(data)
                
                # get the CRC
                crcLow = data[0][0] * 256 + data[0][1]
                crcHigh = data[1][0] * 256 + data[1][1]

                # check address/count for matches
                readAddress = data[2][0] * 256 + data[2][1]
                readCount = data[3][0] * 256 + data[3][1]
                print("readAddress: " + str(readAddress))
                print("readCount: " + str(readCount))
                if readAddress != startAddress or readCount != extraReads:
                    print("mismatch in return address and/or size")
                    exit()

                # and the happy fun CRC
                registerBytes = bytearray((extraReads + 2) * 2)
                for j in range(0, (extraReads + 2)):   # 2 X Address + extraReads words
                    registerBytes[j * 2] = data[j + 2][1]    # + 2 to skip CRC
                    registerBytes[j * 2 + 1] = data[j + 2][0]
                crc32 = zlib.crc32(registerBytes)
                if (crc32 >> 16) != crcHigh or (crc32 & 0xffff) != crcLow:
                    print("crc error on read")
                    print("low: " + str(crcLow) + " mcu:" + str(crc32 & 0xffff))
                    print("high: " + str(crcHigh) + " mcu:" + str(crc32 >> 16))
                    exit()
                
                for j in range(0, extraReads):  # copy to results array
                    resultArray[startAddress + j] = data[4 + j][0] * 256 + data[4 + j][1]

                # at this point, resultArray should be populated with                                       
            else:
                print("read failed: " + str(result))
                exit();

        
    else:
        print("command failed: " + str(result))
