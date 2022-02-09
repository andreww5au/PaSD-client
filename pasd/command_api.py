"""
Code to handle starting/stopping/reading fast-sampling sensor data from a smartbox or FNPC.

Written by Teik Oh, modified by Andrew Williams
"""

import logging
import zlib

logging.basicConfig()

RESET_SAMPLE = 5

START_SAMPLE = 7
STOP_SAMPLE = 8
STATE_SAMPLE = 9
SIZE_SAMPLE = 10
READ_SAMPLE = 11
COUNT_SAMPLE = 12


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
    registerBytes[244] = RESET_SAMPLE  # Reset command, in the least sig byte of COMMAND register

    crc32 = zlib.crc32(registerBytes)
    regValues = [crc32 & 0xffff, crc32 >> 16]
    conn.writeMultReg(modbus_address=address, regnum=10001, valuelist=regValues)
    conn.writeReg(modbus_address=address, regnum=10125, value=RESET_SAMPLE)  # reset


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
    registerBytes[244] = START_SAMPLE  # least sig byte of COMMAND register

    # now, calc crc
    crc32 = zlib.crc32(registerBytes)

    # and build a list for conn.writeMultReg
    regValues = [crc32 & 0xffff, crc32 >> 16]
    for i in range(0, numWords):
        regValues.append(registerBytes[i * 2] + (registerBytes[i * 2 + 1] << 8))

    logger.debug("writing command chunk")
    conn.writeMultReg(modbus_address=address, regnum=10001, valuelist=regValues)
    conn.writeReg(modbus_address=address, regnum=10125, value=START_SAMPLE)  # start sample command

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

    conn.writeReg(modbus_address=address, regnum=10125, value=STOP_SAMPLE)  # sample stop command

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

    conn.writeReg(modbus_address=address, regnum=10125, value=COUNT_SAMPLE)  # sample count command

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

    conn.writeReg(modbus_address=address, regnum=10125, value=SIZE_SAMPLE)  # sample size command

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

    conn.writeReg(modbus_address=address, regnum=10125, value=STATE_SAMPLE)  # sample state command

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
    conn.writeReg(modbus_address=address, regnum=10125, value=COUNT_SAMPLE)  # sample count command

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
            regValues = [startAddress, 100, READ_SAMPLE]

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
            regValues = [startAddress, extraReads, READ_SAMPLE]

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

                # Turn the array with interleaved registers into a dictionary, with register number as key, and
                # lists of the readings just for each register as values.
                resultDict = {}
                for i in range(len(reglist)):
                    resultDict[reglist[i]] = resultArray[i::len(reglist)]
                return resultDict
            else:
                logger.error("sample read failed: " + str(result))
                return
    else:
        logger.error("sample count command failed: " + str(result))
