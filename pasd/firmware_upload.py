
import logging
import zlib
from intelhex import IntelHex

logging.basicConfig()


def send_hex(conn, filename, modbus_address):
    """
    System registers

    CRC registers.  CRC32 is computed for all registers from ADDRESS to COMMAND, or 10003 - 10125.
    If a command does not write to all registers the CRC is still calculated as if all the registers are initialised with 0
    The CRC is calculated lower byte then upper byte

    CRC_LOW 10001
    CRC_HIGH 10002


    Address of program address to write to.  The count (in registers) is stored in the upper byte of ADDRESS_HIGH_COUNT

    ADDRESS_LOW 10003
    ADDRESS_HIGH_COUNT 10004


    Registers containing program data are store in SEGMENT_DATA.  As the PIC24 has 24-bit instructions these
    are packed - lower (L), middle (M), upper (U) - into the data registers as follows.  For example, 3
    instructions 0, 1, 2 would be stored in registers 10005-9 as follows:

    10005: M0L0  (L0 in lower byte of 10008, M0 in upper byte of 10008)
    10006: L1U0  (U0 in lower byte of 10006
    10007: U1M1
    10008: M2L2
    10009: U2  (upper byte of 10008 is wasted)

    SEGMENT_DATA 10005 - 10124,  120 words of data


    The COMMAND register must always be the last register written.  This is why it has the highest address
    of all the data comprising a command from CRC upwards.  This works well for bulk multi-register writes
    of program data as the entire 125 registers are sent in one write instruction.

    However, if a command doesn't use all of the SEGMENT_DATA or ADDRESS registers then it would save time
    by issuing a separate register write for COMMAND.  For example, doing an ERASE would only require writing
    CRC32 registers then writing the ERASE command.

    ERASE 1 - erase and prepare to update
    WRITE_SEGMENT 2 - write segment defined by ADDRESS and SEGMENT_DATA
    VERIFY 3
    UPDATE 4
    RESET 5

    COMMAND 10125


    The result register has to be separately read as it doesn't map onto MODBUS codes.  It contains
    the result of the last command executed.

    RESULT 10126

    Result codes:
    0 = OK
    1 = ERROR
    2 = CRC_ERROR
    3 = UNKNOWN_COMMAND
    """

    # this is a pain.  In order to calculate CRC32 we need to give zlib.crc32() an array of bytes
    # The CRC is calculated for registers ADDRESS_LOW to COMMAND and these are stored in these
    # 246 bytes least significant byte first.
    registerBytes = bytearray(246)

    #######################################

    # start by erasing the EEPROM
    print("Issuing erase command...")
    registerBytes[244] = 1  # least sig byte of COMMAND register
    crc32 = zlib.crc32(registerBytes)
    for i in range(0, 246):  # clear for next calc
        registerBytes[i] = 0

    # write CRC separately to command
    conn.writeMultReg(modbus_address=modbus_address, regnum=10001, valuelist=[crc32 & 0xffff, crc32 >> 16])
    conn.writeReg(modbus_address=modbus_address, regnum=10125, value=1)  # , timeout=10.0)
    print("return code: " + str(conn.readReg(modbus_address=modbus_address, regnum=10126)[0][1]))  # least sig byte

    # a rom hex file consists of segments which are start/end marker of addresses of bytes
    # to write
    # PIC24 has 24-bit instructions but addressing is compatible with 16-bit data presumably so increments of
    # 2 for addressed instructions.
    #
    # So, every 4th byte is zero in the hex file
    print("Reading file %s" % filename)
    ih = IntelHex(filename)

    print("Segments found:")
    print(ih.segments())

    numWrites = 0  # number of write chunks.  This is used for verifying

    for segment in ih.segments():
        start = segment[0]
        end = segment[1]
        if start < 0x1003000:  # this is the magic dual partition boot config that should never be changed
            print("Segment: " + str(start) + " - " + str(end))  # in bytes
            address = start
            addressWords = start >> 1  # addresses are in bytes = 4 bytes per instruction.  But as far as PIC24 addressing goes this has to be halved
            while address < end:
                length = end - address
                if length > 320:  # 320 = 80 "4 byte" instructions which is 240 bytes packed into SEGMENT_DATA
                    length = 320

                print("Chunk: " + str(address) + " - " + str(length))

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
                addressHighCount = (addressWords >> 16) | (
                            (numWords - 2) << 8)  # the -2 is because we don't count address

                # mirror address registers in registerBytes
                registerBytes[0] = addressLow & 0xff
                registerBytes[1] = addressLow >> 8
                registerBytes[2] = addressHighCount & 0xff
                registerBytes[3] = addressHighCount >> 8

                # and the write command
                registerBytes[244] = 2  # least sig byte of COMMAND register

                # now, calc crc
                crc32 = zlib.crc32(registerBytes)

                # and build a list for multiwrite
                regValues = [crc32 & 0xffff, crc32 >> 16]
                for i in range(0, numWords):
                    regValues.append(registerBytes[i * 2] + (registerBytes[i * 2 + 1] << 8))
                #                    print(hex(registerBytes[i * 2] + (registerBytes[i * 2 + 1] << 8)))

                if length < 320:
                    # partial write
                    print("writing partial chunk...")
                    conn.writeMultReg(modbus_address=modbus_address, regnum=10001, valuelist=regValues)
                    conn.writeReg(modbus_address=modbus_address, regnum=10125, value=2)  # write command
                else:
                    # full write, add on command
                    print("writing chunk... " + str(len(regValues)))
                    #                    regValues.append(2)
                    conn.writeMultReg(modbus_address=modbus_address, regnum=10001, valuelist=regValues)
                    # ideally, should just append 2 to regValues above but for some reason transport.py hangs with 125 registers
                    # so split into 2 writes - 124 registers and the separate command.
                    conn.writeReg(modbus_address=modbus_address, regnum=10125, value=2)  # write command

                print(
                    "return code: " + str(conn.readReg(modbus_address=modbus_address, regnum=10126)))  # [0][1]))  # least sig byte

                # one more
                numWrites = numWrites + 1

                # clear for next lop
                for i in range(0, 246):  # clear for next calc
                    registerBytes[i] = 0

                # and do the next block
                address = address + 320
                addressWords = addressWords + 160

    print(str(numWrites) + " chunks written.  Verifying...")

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
    registerBytes[244] = 3  # least sig byte of COMMAND register

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
    conn.writeReg(modbus_address=modbus_address, regnum=10125, value=3)  # trust but verify

    verifyResult = conn.readReg(modbus_address=modbus_address, regnum=10126)[0][1]
    if verifyResult == 0:
        print("verify ok.  Updating.")

        # the update command
        registerBytes[244] = 4  # least sig byte of COMMAND register
        # now, calc crc
        crc32 = zlib.crc32(registerBytes)
        for i in range(0, 246):  # clear for next calc
            registerBytes[i] = 0
        regValues = [crc32 & 0xffff, crc32 >> 16]
        conn.writeMultReg(modbus_address=modbus_address, regnum=10001, valuelist=regValues)
        conn.writeReg(modbus_address=modbus_address, regnum=10125, value=4)  # update
        updateResult = conn.readReg(modbus_address=modbus_address, regnum=10126)[0][1]
        if updateResult == 0:
            print("update ok.  Resetting.")

            # the reset command
            registerBytes[244] = 5  # least sig byte of COMMAND register
            # now, calc crc
            crc32 = zlib.crc32(registerBytes)
            for i in range(0, 246):  # clear for next calc
                registerBytes[i] = 0
            regValues = [crc32 & 0xffff, crc32 >> 16]
            conn.writeMultReg(modbus_address=modbus_address, regnum=10001, valuelist=regValues)
            conn.writeReg(modbus_address=modbus_address, regnum=10125, value=5)  # reset
        else:
            print("update failed: " + str(updateResult))

    else:
        print("verify failed: " + str(verifyResult))
