#!/usr/bin/env python

import argparse
import logging
import os
import socket
import sys

LOGFILE = 'upload.log'

fh = logging.FileHandler(filename=LOGFILE, mode='w')
fh.setLevel(logging.DEBUG)  # All log messages go to the log file
sh = logging.StreamHandler()
sh.setLevel(logging.INFO)  # Some or all log messages go to the console
# noinspection PyArgumentList
logging.basicConfig(handlers=[fh, sh],
                    level=logging.DEBUG,
                    format='%(levelname)s:%(name)s %(created)14.3f - %(message)s')

from pasd import transport
from pasd import command_api


if socket.gethostname().startswith('orthrus'):
    DEFHOST = 'pasd-fndh2.mwa128t.org'
else:
    DEFHOST = 'pasd-fndh.mwa128t.org'

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Upload new firmware to an FNDH or smartbox')
    parser.add_argument('--filename', help='Intel HEX filename to upload')
    parser.add_argument('--host', dest='host', default=None,
                        help='Hostname of an ethernet-serial gateway, eg 134.7.50.185')
    parser.add_argument('--device', dest='device', default=None,
                        help='Serial port device name, eg /dev/ttyS0 or COM6')
    parser.add_argument('--portnum', dest='portnum', default=5000,
                        help='TCP port number to use')
    parser.add_argument('--address', dest='address', default=0,
                        help='Modbus address')
    args = parser.parse_args()

    if (args.host is None) and (args.device is None):
        args.host = DEFHOST

    if os.path.basename(args.filename).upper().startswith('FNPC'):
        if (int(args.address) not in [31, 101]):
            print('Trying to push FNDH image to a smartbox? %s' % args.filename)
            print('Filename must start with "FNPC" (and go to address 31 or 101), or "SBox" (and go to address 1-24).')
            sys.exit(-1)
    elif os.path.basename(args.filename).upper().startswith('SBOX'):
        if (int(args.address) not in list(range(1, 25))):
            print('Trying to push smartbox image to an FNDH? %s' % args.filename)
            print('Filename must start with "FNPC" (and go to address 31 or 101), or "SBox" (and go to address 1-24).')
            sys.exit(-1)
    else:
        print('Filename must start with "FNPC" (and go to address 31 or 101), or "SBox" (and go to address 1-24).')
        sys.exit(-1)

    if args.address == 0:
        print('Must supply a modbus address to send the new firmware to')
        sys.exit(-1)

    tlogger = logging.getLogger('T')
    conn = transport.Connection(hostname=args.host, devicename=args.device, port=int(args.portnum), multidrop=False, logger=tlogger)

    ok = command_api.send_hex(conn=conn, filename=args.filename, address=int(args.address))
    if ok:
        command_api.reset_microcontroller(conn, int(args.address), logger=logging)
