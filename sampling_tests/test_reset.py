#!/usr/bin/env python

import logging
import sys
import zlib
import time
from intelhex import IntelHex

LOGFILE = 'test.log'


if __name__ == '__main__':
    print('Test Reset')
    
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
#
#
# The COMMAND register must always be the last register written.  This is why it has the highest address
# of all the data comprising a command from CRC upwards.  This works well for bulk multi-register writes
# of program data as the entire 125 registers are sent in one write instruction.
#
#
# COMMAND 10125
#
# RESET_COMMAND = 5
#
    print("Issuing reset...")
    registerBytes = bytearray(246)

    # all this crud is necessary to protect from inadvertent errors through
    # bit errors in comms.
    
    # the reset command
    registerBytes[244] = 5   # least sig byte of COMMAND register
    
    # now, calc crc
    crc32 = zlib.crc32(registerBytes)
    regValues=[crc32 & 0xffff, crc32 >> 16]
    s.conn.writeMultReg(modbus_address=1, regnum=10001, valuelist=regValues)
    s.conn.writeReg(modbus_address=1, regnum=10125, value=5)  # reset

    # earth shattering kaboom
