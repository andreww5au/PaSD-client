"""
Code to handle commands to the microcontroller using the system register block, 10001-10126, including uploading
new firmware, resetting the microcontroller, and starting/stopping/reading fast-sampling sensor data from a smartbox or
FNPC.

System registers definitions:

----------------------------------------------------------
CRC_LOW: 10001
CRC_HIGH: 10002

CRC registers.  CRC32 is computed for all registers from ADDRESS to COMMAND, or 10003 - 10125.
If a command does not write to all registers the CRC is still calculated as if all the registers are initialised with 0
The CRC is calculated lower byte then upper byte


----------------------------------------------------------
ADDRESS_LOW: 10003
ADDRESS_HIGH_COUNT: 10004

Address registers (for firmware upload) - the 24-bit program memory address to write to.  The count (in registers) is stored
in the upper byte of ADDRESS_HIGH_COUNT


----------------------------------------------------------
SEGMENT_DATA: 10005 - 10124,  120 words of data

Segment data registers - For firmware uploads, as the PIC24 has 24-bit instructions these
are packed - lower (L), middle (M), upper (U) - into the data registers as follows.  For example, 3
instructions 0, 1, 2 would be stored in registers 10005-9 as follows:

        10005: M0L0  (L0 in lower byte of 10008, M0 in upper byte of 10008)
        10006: L1U0  (U0 in lower byte of 10006
        10007: U1M1
        10008: M2L2
        10009: U2  (upper byte of 10008 is wasted)


----------------------------------------------------------
COMMAND: 10125

The COMMAND register must always be the last register written.  This is why it has the highest address
of all the data comprising a command from CRC upwards.  This works well for bulk multi-register writes
of program data as the entire 125 registers are sent in one write instruction.

    ERASE_COMMAND = 1 - erase and prepare to update
    WRITE_SEGMENT_COMMAND = 2 - write segment defined by ADDRESS and SEGMENT_DATA
    VERIFY_COMMAND = 3
    UPDATE_COMMAND = 4
    RESET_COMMAND = 5
    SAMPLE_START_COMMAND = 7 - start sampling.  The sample parameters are in SEGMENT_DATA
    SAMPLE_STOP_COMMAND = 8  - stop sampling (if running)
    SAMPLE_STATE_COMMAND = 9 - get the sample state
    SAMPLE_SIZE_COMMAND = 10 - get the size of the sampling buffer, result in RESULT_DATA1
    SAMPLE_READ_COMMAND = 11 - read a chunk of sample data
    SAMPLE_COUNT_COMMAND = 12 - read which sampleCount it is up to


----------------------------------------------------------
RESULT: 10126

The result register has to be separately read as it doesn't map onto MODBUS codes.  It contains
the result of the last command executed.

Result codes are:
    0 = OK
    1 = ERROR
    2 = CRC_ERROR
    3 = UNKNOWN_COMMAND


----------------------------------------------------------
SAMPLING:

Sampling happens asynchronously via a number of commands.  A SAMPLE_START_COMMAND is used to initiate a sampling sequence.
While this happens, SAMPLE_STATE_COMMAND can be polled for completion, or you can ask for the number of samples
taken so far (SAMPLE_COUNT_COMMAND).  When sampling is complete, data may be read using SAMPLE_READ_COMMAND,
although if you keep track of SAMPLE_COUNT_COMMAND you can read right up to the last sample completed.


Written by Teik Oh, modified by Andrew Williams
"""

import logging
import zlib

logging.basicConfig()

ERASE_COMMAND = 1          # erase and prepare to update
WRITE_SEGMENT_COMMAND = 2  # write segment defined by ADDRESS and SEGMENT_DATA
VERIFY_COMMAND = 3
UPDATE_COMMAND = 4
RESET_COMMAND = 5          # Reset the microcontroller. Checks CRC.

SAMPLE_START_COMMAND = 7   # start sampling.The sample parameters are in SEGMENT_DATA. Checks CRC.
SAMPLE_STOP_COMMAND = 8    # stop sampling( if running). Does not check CRC.
SAMPLE_STATE_COMMAND = 9   # get the sample state. Does not check CRC.
SAMPLE_SIZE_COMMAND = 10   # get the size of the sampling buffer, result in RESULT_DATA1. Does not check CRC.
SAMPLE_READ_COMMAND = 11   # read a chunk of sample data. Does not check CRC on command, but sends CRC with data.
SAMPLE_COUNT_COMMAND = 12  # read which sampleCount it is up to. Does not check CRC.


def reset_microcontroller(conn, address, logger=logging):
    """
    Resets the current sampling job, immediately.

    :param conn: A pasd.transport.Connection() object
    :param address: Modbus address
    :param logger: A logging.logger object, or defaults to the logging module with basicConfig() called
    :return: True for success, False on failure
    """
    logger.debug("Issuing sample reset command")

    registerBytes = bytearray(246)
    registerBytes[244] = RESET_COMMAND  # Reset command, in the least sig byte of COMMAND register

    crc32 = zlib.crc32(registerBytes)
    regValues = [crc32 & 0xffff, crc32 >> 16]
    conn.writeMultReg(modbus_address=address, regnum=10001, valuelist=regValues)
    conn.writeReg(modbus_address=address, regnum=10125, value=RESET_COMMAND)  # reset


def start_sample(conn, address, interval, reglist, logger=logging):
    """
    Start sampling the given list of registers, every 'interval' milliseconds, and recording those samples
    into an interval buffer, to be read later with the read_samples() function.

    :param conn: A pasd.transport.Connection() object
    :param address: Modbus address
    :param interval: Interval between samples, in milliseconds, up to 32 bits
    :param reglist: List of integer register numbers to sample
    :param logger: A logging.logger object, or defaults to the logging module with basicConfig() called
    :return: True for success, False on failure
    """
    # this is a pain.  In order to calculate CRC32 we need to give zlib.crc32() an array of bytes
    # The CRC is calculated for registers ADDRESS_LOW to COMMAND and these are stored in these
    # 246 bytes least significant byte first.
    registerBytes = bytearray(246)    # Initialised with all zeroes

    # The first four bytes store the (32-bit) number of milliseconds between each sample
    registerBytes[0] = int(interval) & 0xff
    registerBytes[1] = (int(interval) & 0xff00) >> 8
    registerBytes[2] = (int(interval) & 0xff0000) >> 16
    registerBytes[3] = int(interval) >> 24

    # The next two bytes hold the number of registers to sample
    registerBytes[5], registerBytes[4] = divmod(len(reglist), 256)

    # now we store the register numbers
    i = 6   # Byte address for the first register number
    for regnum in reglist:
        registerBytes[i+1], registerBytes[i] = divmod(regnum, 256)
        i += 2

    numWords = len(reglist) + 3  # just number of words for all of above:  addressLow to whichever SEGMENT_DATA written

    # and the sample start command. Note that this is here so the CRC is calculated correctly - it's sent in a
    # separate writeReg() call, not as part of the registerBytes array.
    registerBytes[244] = SAMPLE_START_COMMAND  # least sig byte of COMMAND register

    # now, calc crc
    crc32 = zlib.crc32(registerBytes)

    # and build a list for conn.writeMultReg
    regValues = [crc32 & 0xffff, crc32 >> 16]
    for i in range(0, numWords):
        regValues.append(registerBytes[i * 2] + (registerBytes[i * 2 + 1] << 8))

    logger.debug("writing command chunk")
    conn.writeMultReg(modbus_address=address, regnum=10001, valuelist=regValues)
    conn.writeReg(modbus_address=address, regnum=10125, value=SAMPLE_START_COMMAND)  # start sample command

    # read result
    result = conn.readReg(modbus_address=address, regnum=10126)[0][1]  # results register
    if result == 0:
        logger.info("Sampling started.")
        return True
    else:
        logger.error("Sampling failed: " + str(result))
        return False


def stop_sample(conn, address, logger=logging):
    """
    Stops sampling, immediately.

    :param conn: A pasd.transport.Connection() object
    :param address: Modbus address
    :param logger: A logging.logger object, or defaults to the logging module with basicConfig() called
    :return: True for success, False on failure
    """
    logger.debug("Issuing sample stop command")

    conn.writeReg(modbus_address=address, regnum=10125, value=SAMPLE_STOP_COMMAND)  # sample stop command

    result = conn.readReg(modbus_address=address, regnum=10126)[0][1]  # results register
    if result == 0:
        logger.info("Sampling stopped")
        return True
    else:
        logger.error("Sampling stop failed: " + str(result))
        return False


def get_sample_count(conn, address, logger=logging):
    """
    Returns the current sample count of an active sample process.

    :param conn: A pasd.transport.Connection() object
    :param address: Modbus address
    :param logger: A logging.logger object, or defaults to the logging module with basicConfig() called
    :return: Number of samples connected, or None on failure
    """
    logger.debug("Issuing sample count command")

    conn.writeReg(modbus_address=address, regnum=10125, value=SAMPLE_COUNT_COMMAND)  # sample count command

    result = conn.readReg(modbus_address=address, regnum=10126)[0][1]  # results register
    if result == 0:
        sampleCount_pair = conn.readReg(modbus_address=address, regnum=10127)[0]
        logger.info("sample count: " + str(sampleCount_pair[0] * 256 + sampleCount_pair[1]))
        return sampleCount_pair[0] * 256 + sampleCount_pair[1]
    else:
        logger.error("Sampling count failed: " + str(result))
        return None


def get_sample_size(conn, address, logger=logging):
    """
    Returns the total number of words available to store sample data

    :param conn: A pasd.transport.Connection() object
    :param address: Modbus address
    :param logger: A logging.logger object, or defaults to the logging module with basicConfig() called
    :return: Number of words in the sample buffer space, or None on failure
    """
    logger.debug("Issuing sample size command")

    conn.writeReg(modbus_address=address, regnum=10125, value=SAMPLE_SIZE_COMMAND)  # sample size command

    result = conn.readReg(modbus_address=address, regnum=10126)[0][1]  # results register
    if result == 0:
        sampleSize_pair = conn.readReg(modbus_address=address, regnum=10127)[0]
        logger.info("sample size: " + str(sampleSize_pair[0] * 256 + sampleSize_pair[1]))
        return sampleSize_pair[0] * 256 + sampleSize_pair[1]
    else:
        logger.error("Sampling size failed: " + str(result))
        return None


def get_sample_state(conn, address, logger=logging):
    """
    Returns the current sampling state - 0 = STOPPED, 1 = SAMPLING

    :param conn: A pasd.transport.Connection() object
    :param address: Modbus address
    :param logger: A logging.logger object, or defaults to the logging module with basicConfig() called
    :return: 0 = STOPPED, 1 = SAMPLING, or None on failure
    """
    logger.debug("Issuing sample state command")

    conn.writeReg(modbus_address=address, regnum=10125, value=SAMPLE_STATE_COMMAND)  # sample state command

    result = conn.readReg(modbus_address=address, regnum=10126)[0][1]  # results register
    if result == 0:
        sampleState = conn.readReg(modbus_address=address, regnum=10127)[0][1]
        logger.info("sample state: %d" % sampleState)
        return sampleState
    else:
        logger.error("Sampling size state: " + str(result))
        return None


def get_sample_data(conn, address, reglist, logger=logging):
    """
    Returns the sampled sensor data

    :param conn: A pasd.transport.Connection() object
    :param address: Modbus address
    :param reglist: List of integer register numbers to sample
    :param logger: A logging.logger object, or defaults to the logging module with basicConfig() called
    :return: 0 = STOPPED, 1 = SAMPLING, or None on failure
    """
    conn.writeReg(modbus_address=address, regnum=10125, value=SAMPLE_COUNT_COMMAND)  # sample count command

    result = conn.readReg(modbus_address=address, regnum=10126)[0][1]  # results register
    if result == 0:
        logger.debug("Count result ok.")

        sampleRead = conn.readReg(modbus_address=address, regnum=10127)[0]
        sampleCount = sampleRead[0] * 256 + sampleRead[1]  # number of sets of samples
        print("sample count: " + str(sampleCount))

        # at this point we know how many words to read because in
        # test_sample_start we specified 5 registers.  I could return all this in
        # register reads but that doesn't make much sense to...
        numWords = sampleCount * len(reglist)
        resultArray = [0] * numWords   # Multiplying a list of items by N repeats it N times

        # for simple maths, let's poll 100 words at a time even though it could be 124
        numFullReads = numWords // 100
        extraReads = numWords - numFullReads * 100

        # do the full samples
        for i in range(0, numFullReads):
            startAddress = i * 100
            # the starting address, number of words to read and the read command (11)
            regValues = [startAddress, 100, SAMPLE_READ_COMMAND]

            # 10123 = COMMAND_REGISTER - 2.  The 2 bytes before it denote starting address and num words to read
            conn.writeMultReg(modbus_address=address, regnum=10123, valuelist=regValues)

            result = conn.readReg(modbus_address=address, regnum=10126)[0][1]  # results register
            if result == 0:
                data = conn.readReg(modbus_address=address, regnum=10001, numreg=104)  # 104 because 2 CRC words, 2 address words + 100 words data

                # get the CRC
                crcLow = data[0][0] * 256 + data[0][1]
                crcHigh = data[1][0] * 256 + data[1][1]

                # check address/count for matches
                readAddress = data[2][0] * 256 + data[2][1]
                readCount = data[3][0] * 256 + data[3][1]
                logger.debug("readAddress: " + str(readAddress))
                if readAddress != startAddress or readCount != 100:  # magic 100...
                    logger.error("mismatch in return address and/or size")
                    return

                # and the happy fun CRC
                registerBytes = bytearray(102 * 2)
                for j in range(0, 102):  # 2 X Address + 100 words
                    registerBytes[j * 2] = data[j + 2][1]  # + 2 to skip CRC
                    registerBytes[j * 2 + 1] = data[j + 2][0]
                crc32 = zlib.crc32(registerBytes)
                if (crc32 >> 16) != crcHigh or (crc32 & 0xffff) != crcLow:
                    logger.error("crc error on read")
                    logger.error("low: " + str(crcLow) + " mcu:" + str(crc32 & 0xffff))
                    logger.error("high: " + str(crcHigh) + " mcu:" + str(crc32 >> 16))
                    return

                for j in range(0, 100):  # copy to results array
                    resultArray[startAddress + j] = data[4 + j][0] * 256 + data[4 + j][1]
            else:
                print("read failed: " + str(result))
                return

        # and the partial sample if there is one
        if extraReads > 0:
            startAddress = numFullReads * 100

            # the starting address, number of words to read and the read command (11)
            regValues = [startAddress, extraReads, SAMPLE_READ_COMMAND]

            # 10123 = COMMAND_REGISTER - 2.  The 2 bytes before it denote starting address and num words to read
            conn.writeMultReg(modbus_address=address, regnum=10123, valuelist=regValues)
            result = conn.readReg(modbus_address=address, regnum=10126)[0][1]  # results register
            if result == 0:
                logger.debug("Extra samples: " + str(extraReads))
                data = conn.readReg(modbus_address=address, regnum=10001, numreg=(4 + extraReads))  # 2 CRC words, 2 address words + extraReads words data

                # get the CRC
                crcLow = data[0][0] * 256 + data[0][1]
                crcHigh = data[1][0] * 256 + data[1][1]

                # check address/count for matches
                readAddress = data[2][0] * 256 + data[2][1]
                readCount = data[3][0] * 256 + data[3][1]
                if readAddress != startAddress or readCount != extraReads:
                    logger.error("mismatch in return address and/or size")
                    return

                # and the happy fun CRC
                registerBytes = bytearray((extraReads + 2) * 2)
                for j in range(0, (extraReads + 2)):  # 2 X Address + extraReads words
                    registerBytes[j * 2] = data[j + 2][1]  # + 2 to skip CRC
                    registerBytes[j * 2 + 1] = data[j + 2][0]
                crc32 = zlib.crc32(registerBytes)
                if (crc32 >> 16) != crcHigh or (crc32 & 0xffff) != crcLow:
                    logger.error("crc error on read")
                    logger.error("low: " + str(crcLow) + " mcu:" + str(crc32 & 0xffff))
                    logger.error("high: " + str(crcHigh) + " mcu:" + str(crc32 >> 16))
                    return

                for j in range(0, extraReads):  # copy to results array
                    resultArray[startAddress + j] = data[4 + j][0] * 256 + data[4 + j][1]
            else:
                logger.error("sample read failed: " + str(result))
                return

        # Turn the array with interleaved registers into a dictionary, with register number as key, and
        # lists of the readings just for each register as values.
        resultDict = {}
        for i in range(len(reglist)):
            resultDict[reglist[i]] = resultArray[i::len(reglist)]
        return resultDict
    else:
        logger.error("sample count command failed: " + str(result))
