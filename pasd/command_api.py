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
    VERIFY_COMMAND = 3 - Verify the microcontroller code written to memory
    UPDATE_COMMAND = 4 - Update the microcontroller to boot from the newly written firmware on next reboot
    RESET_COMMAND = 5 - Reboot the micocontroller
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


------------------------------------------------------------
CPU load and warnings:

CPU_LOAD 10129
WARNINGS_LSW 10130
WARNINGS_MSW 10131
ALARMS_LSW 10132
ALARMS_MSW 10133

----------------------------------------------------------
SAMPLING:

Sampling happens asynchronously via a number of commands.  A SAMPLE_START_COMMAND is used to initiate a sampling sequence.
While this happens, SAMPLE_STATE_COMMAND can be polled for completion, or you can ask for the number of samples
taken so far (SAMPLE_COUNT_COMMAND).  When sampling is complete, data may be read using SAMPLE_READ_COMMAND,
although if you keep track of SAMPLE_COUNT_COMMAND you can read right up to the last sample completed.


Written by Teik Oh, modified by Andrew Williams
"""

import logging
import math
import zlib

try:
    from intelhex import IntelHex
except ImportError:
    IntelHex = None


logging.basicConfig()

ERASE_COMMAND = 1          # erase and prepare to update. Checks CRC.
WRITE_SEGMENT_COMMAND = 2  # write segment defined by ADDRESS and SEGMENT_DATA. Checks CRC.
VERIFY_COMMAND = 3         # Verify the microcontroller code written to memory. Checks CRC.
UPDATE_COMMAND = 4         # Update the microcontroller to boot from the newly written firmware on next reboot. Checks CRC.
RESET_COMMAND = 5          # Reset the microcontroller. Checks CRC.
PEEK_ROM_COMMAND = 6       # Return a block of microcontroller ROM. Sends CRC with data.
SAMPLE_START_COMMAND = 7   # start sampling.The sample parameters are in SEGMENT_DATA. Checks CRC.
SAMPLE_STOP_COMMAND = 8    # stop sampling( if running). Does not check CRC.
SAMPLE_STATE_COMMAND = 9   # get the sample state. Does not check CRC.
SAMPLE_SIZE_COMMAND = 10   # get the size of the sampling buffer, result in RESULT_DATA1. Does not check CRC.
SAMPLE_READ_COMMAND = 11   # read a chunk of sample data. Does not check CRC on command, but sends CRC with data.
SAMPLE_COUNT_COMMAND = 12  # read which sampleCount it is up to. Does not check CRC.


def filter_constant(freq=10.0):
    """
    Given a cutoff frequency in Hz, return the 16-bit value that should be written to a Smartbox or FNDH
    telemetry register to enable low-pass filtering with that cutoff frequency.

    :param freq: Low-pass cut off frequency, in Hz, or None to disable filtering
    :return: 16-bit register value to write to enable filtering
    """
    if freq is None:
        return 0

    dt = 0.001  # input: time step in seconds: 0.001 = 1ms

    alpha = dt / ((1 / (2 * math.pi * freq)) + dt)
    # print("Alpha: " + str(alpha))
    mantissaBits = 11  # 11 bits mantissa in current format
    base = math.log(alpha) / math.log(2)
    # print("Base: " + str(base))
    rightShift = -int(base)
    lowerRange = 2 ** (-rightShift)
    # print("Lower range: " + str(lowerRange))
    upperRange = 2 ** (-rightShift - 1)
    # print("Upper range: " + str(upperRange))
    mantissaStep = (lowerRange - upperRange) / (2 ** (mantissaBits - 1))
    # print("Mantissa step: " + str(mantissaStep))
    mantissa = int((alpha - upperRange) / mantissaStep)
    # print("Right shift: " + str(rightShift))
    # print("Mantissa: " + str(mantissa))
    # print("Filter hex code: " + hex(mantissa + rightShift * (2 ** 11)))
    return mantissa + rightShift * (2 ** 11)


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


def get_hex_info(filename, logger=logging):
    """
    Takes the name of a Hex firmware file, and reads the version numbers that the Hex file was defined for
    (modbus API revision, PCB revision) and the firmware version number, from a few bytes appended to the end
    of the firmware binary, in the form:

    ;PaSD mbrev=1 pcbrev=2 firmver=3

    :param filename: Name of the Intel Hex file
    :param logger: An optional logging.Logger instance
    :return: A dictionary with 'mbrev', pcbrev' and 'firmver' as keys, and integers as values, or an empty dictionary.
    """
    hexFile = open(filename, "r")
    header = ""
    for line in hexFile.readlines():
        if line.startswith(";PaSD"):
            header = line
    hexFile.close()

    if not header:
        logger.warning("command_api.get_hex_info - no version header found")
        return {}

    logger.debug("command_api.get_hex_info - header: " + header)

    result = {}
    params = header.split()
    for i in range(1, len(params)):
        param = params[i].split("=")
        if param[0] == "mbrev":
            result['mbrev'] = int(param[1])
        elif param[0] == "pcbrev":
            result['pcbrev'] = int(param[1])
        elif param[0] == "firmver":
            result['firmver'] = int(param[1])
        else:
            logger.warning("command_api.get_hex_info - Unexpected parameter: %s=%s" % (param[0], param[1]))

    logger.info("command_api.get_hex_info - parameters are: %s" % (result,))
    return result


def send_hex(conn, filename, modbus_address, logger=logging, force=False):
    """
    Takes the name of a file in Intel hex format, and sends it to the specified Modbus address, then commands the
    microcontroller to swap to the new ROM bank. The caller must issue a reset command using the reset_microcontroller()
    function after this function exits, to boot into the new firmware.

    Note that it's up to the caller to make sure that the firmware in the file matches the hardware on the specified
    modbus address - otherwise the device will be 'bricked', and need a manual firmware upload in the lab.

    :param conn: A pasd.transport.Connection() object
    :param filename: The name of a file containing and Intel Hex format firmware binary
    :param modbus_address: Modbus address
    :param logger: A logging.logger object, or defaults to the logging module with basicConfig() called
    :param force: If True, force firmware upload even if version number does not match that reported by hardware.
    :return:
    """
    params = get_hex_info(filename=filename, logger=logger)
    if not params:
        logger.warning("command_api.send_hex - No version information in hex file")
        if not force:
            logger.error("command_api.send_hex - aborting upload. Ese force=True to force firmware upload.")
            return False

    # Get a list of tuples, where each tuple is a two-byte register value, eg (0,255)
    try:
        valuelist = conn.readReg(modbus_address=modbus_address, regnum=1, numreg=13)
    except IOError:
        logger.info('No data returned by readReg in poll_data for SMARTbox %d' % modbus_address)
        return None
    except Exception:
        logger.exception('Exception in readReg in poll_data for SMARTbox %d' % modbus_address)
        return None

    if valuelist is None:
        logger.error('Error in readReg in poll_data for SMARTbox %d, no data' % modbus_address)
        return None

    if len(valuelist) != 13:
        logger.warning('Only %d registers returned from SMARTbox %d by readReg in poll_data, expected %d' % (len(valuelist),
                                                                                                             modbus_address,
                                                                                                             13))
        return None

    mbrv = valuelist[0][0] * 256 + valuelist[0][1]
    pcbrv = valuelist[1][0] * 256 + valuelist[1][1]
    firmver = valuelist[12][0] * 256 + valuelist[12][1]

    if mbrv != params.get('mbrv', None):   # Modbus API protocol revision is different
        logger.warning("command_api.send_hex - Modbus API revision is different to to firmware on device.")
        logger.warning("                       Existing=%d, New=%s" % (mbrv, params.get('mbrv', None)))
        if not force:
            logger.error("command_api.send_hex - aborting upload. Use force=True to force firmware upload.")
            return False

    if pcbrv != params.get('pcbrv', None):   # Hardware on board is different
        logger.warning("command_api.send_hex - Actual device hardware different to firmware target.")
        logger.warning("                       Hardware=%d, Firmware target=%s" % (pcbrv, params.get('pcbrv', None)))
        if not force:
            logger.error("command_api.send_hex - aborting upload. Use force=True to force firmware upload.")
            return False

    logger.info("command_api.send_hex - Existing firmware version %s, new firmware version %s" % (firmver,
                                                                                                  params.get('firmver', 'Unknown')))

    logger.info('Writing %s to modbus address %d' % (filename, modbus_address))
    if IntelHex is None:
        logger.critical('intelhex library no available, exiting.')
        return False

    # this is a pain.  In order to calculate CRC32 we need to give zlib.crc32() an array of bytes
    # The CRC is calculated for registers ADDRESS_LOW to COMMAND and these are stored in these
    # 246 bytes least significant byte first.
    registerBytes = bytearray(246)

    #######################################

    # start by erasing the EEPROM
    print("Issuing erase command...")
    registerBytes[244] = ERASE_COMMAND  # least sig byte of COMMAND register
    crc32 = zlib.crc32(registerBytes)
    for i in range(0, 246):  # clear for next calc
        registerBytes[i] = 0

    # write CRC separately to command
    conn.writeMultReg(modbus_address=modbus_address, regnum=10001, valuelist=[crc32 & 0xffff, crc32 >> 16])
    conn.writeReg(modbus_address=modbus_address, regnum=10125, value=ERASE_COMMAND)  # , timeout=10.0)
    logger.debug("Erase return code: " + str(conn.readReg(modbus_address=modbus_address, regnum=10126)[0][1]))  # least sig byte

    # a rom hex file consists of segments which are start/end marker of addresses of bytes to write
    # PIC24 has 24-bit instructions but addressing is compatible with 16-bit data presumably so increments of
    # 2 for addressed instructions.
    #
    # So, every 4th byte is zero in the hex file
    logger.info("Reading file %s" % filename)
    ih = IntelHex(filename)

    logger.info("Segments found:")
    logger.info(ih.segments())

    numWrites = 0  # number of write chunks.  This is used for verifying

    for segment in ih.segments():
        start = segment[0]
        end = segment[1]
        if start < 0x1003000:  # this is the magic dual partition boot config that should never be changed
            logger.info("Segment: " + str(start) + " - " + str(end))  # in bytes
            address = start
            addressWords = start >> 1  # addresses are in bytes = 4 bytes per instruction.  But as far as PIC24 addressing goes this has to be halved
            while address < end:
                length = end - address
                if length > 320:  # 320 = 80 "4 byte" instructions which is 240 bytes packed into SEGMENT_DATA
                    length = 320

                logger.info("Chunk: " + str(address) + " - " + str(length))

                i = 0
                j = 4  # there are 2 address registers below here
                while i < length:
                    registerBytes[j] = ih[address + i]
                    registerBytes[j + 1] = ih[address + i + 1]
                    registerBytes[j + 2] = ih[address + i + 2]
                    i = i + 4
                    j = j + 3

                # word count and set into highcount reg
                numWords = j // 2

                if j & 1 > 0:
                    numWords = numWords + 1

                addressLow = addressWords & 0xffff
                addressHighCount = (addressWords >> 16) | ((numWords - 2) << 8)  # the -2 is because we don't count address

                # mirror address registers in registerBytes
                registerBytes[0] = addressLow & 0xff
                registerBytes[1] = addressLow >> 8
                registerBytes[2] = addressHighCount & 0xff
                registerBytes[3] = addressHighCount >> 8

                # and the write command
                registerBytes[244] = WRITE_SEGMENT_COMMAND  # least sig byte of COMMAND register

                # now, calc crc
                crc32 = zlib.crc32(registerBytes)

                # and build a list for multiwrite
                regValues = [crc32 & 0xffff, crc32 >> 16]
                for i in range(0, numWords):
                    regValues.append(registerBytes[i * 2] + (registerBytes[i * 2 + 1] << 8))

                if length < 320:
                    # partial write
                    logger.info("writing partial chunk...")
                    conn.writeMultReg(modbus_address=modbus_address, regnum=10001, valuelist=regValues)
                    conn.writeReg(modbus_address=modbus_address, regnum=10125, value=WRITE_SEGMENT_COMMAND)  # write command
                else:
                    # full write, add on command
                    print("writing chunk... " + str(len(regValues)))
                    #                    regValues.append(2)
                    conn.writeMultReg(modbus_address=modbus_address, regnum=10001, valuelist=regValues)
                    # ideally, should just append 2 to regValues above but for some reason transport.py hangs with 125 registers
                    # so split into 2 writes - 124 registers and the separate command.
                    conn.writeReg(modbus_address=modbus_address, regnum=10125, value=WRITE_SEGMENT_COMMAND)  # write command

                logger.debug("write return code: " + str(conn.readReg(modbus_address=modbus_address, regnum=10126)))  # [0][1]))  # least sig byte

                # one more
                numWrites = numWrites + 1

                # clear for next lop
                for i in range(0, 246):  # clear for next calc
                    registerBytes[i] = 0

                # and do the next block
                address = address + 320
                addressWords = addressWords + 160

    logger.info(str(numWrites) + " chunks written.  Verifying...")

    # to verify, put numWrites as a 32-bit unsigned int into the first two SEGMENT_DATA registers
    registerBytes[4] = numWrites & 0xff
    registerBytes[5] = (numWrites >> 8) & 0xff
    registerBytes[6] = (numWrites >> 16) & 0xff
    registerBytes[7] = (numWrites >> 24) & 0xff

    # set address to zero
    registerBytes[0] = 0
    registerBytes[1] = 0
    registerBytes[2] = 0
    registerBytes[3] = 0

    # and the verify command
    registerBytes[244] = VERIFY_COMMAND  # least sig byte of COMMAND register

    # now, calc crc
    crc32 = zlib.crc32(registerBytes)
    for i in range(0, 246):  # clear for next calc
        registerBytes[i] = 0

    # and build a list for multiwrite
    regValues = [crc32 & 0xffff, crc32 >> 16]
    regValues.append(0)  # empty address x 2
    regValues.append(0)
    regValues.append(numWrites & 0xffff)
    regValues.append(numWrites >> 16)

    conn.writeMultReg(modbus_address=modbus_address, regnum=10001, valuelist=regValues)
    conn.writeReg(modbus_address=modbus_address, regnum=10125, value=VERIFY_COMMAND)  # trust but verify

    verifyResult = conn.readReg(modbus_address=modbus_address, regnum=10126)[0][1]
    if verifyResult == 0:
        logger.info("verify ok.  Updating.")

        # the update command
        registerBytes[244] = UPDATE_COMMAND  # least sig byte of COMMAND register
        # now, calc crc
        crc32 = zlib.crc32(registerBytes)
        for i in range(0, 246):  # clear for next calc
            registerBytes[i] = 0
        regValues = [crc32 & 0xffff, crc32 >> 16]
        conn.writeMultReg(modbus_address=modbus_address, regnum=10001, valuelist=regValues)
        conn.writeReg(modbus_address=modbus_address, regnum=10125, value=UPDATE_COMMAND)  # update
        updateResult = conn.readReg(modbus_address=modbus_address, regnum=10126)[0][1]
        if updateResult == 0:
            logger.info("Update finished. Old firmware version %s, new firmware version %s" % (firmver,
                                                                                               params.get('firmver',
                                                                                                          'Unknown')))
            logger.info("Call reset_microcontroller to boot into new firmware.")
            return True
        else:
            logger.info("Update FAILED, new firmware NOT swapped in!: " + str(updateResult))
            return False
    else:
        logger.info("Verify FAILED, new firmware NOT written!: " + str(verifyResult))
        return False
