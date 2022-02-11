#!/usr/bin/env python

import argparse
import logging
import sys

from pasd import transport
from pasd import firmware_upload

LOGFILE = 'upload.log'


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
    parser.add_argument('--debug', dest='debug', default=False, action='store_true',
                        help='If given, drop to the DEBUG log level, otherwise use INFO')
    args = parser.parse_args()

    if args.debug:
        loglevel = logging.DEBUG
    else:
        loglevel = logging.INFO

    if (args.host is None) and (args.device is None):
        args.host = 'pasd-fndh.mwa128t.org'

    if ('FN' in args.filename) and (int(args.address) not in [31, 101]):
        print('Trying to push FNDH image to a smartbox? %s' % args.filename)
        sys.exit(-1)
    elif args.filename.upper().startswith('S') and (int(args.address) in [31, 101]):
        print('Trying to push smartbox image to an FNDH? %s' % args.filename)
        sys.exit(-1)

    fh = logging.FileHandler(filename=LOGFILE, mode='w')
    fh.setLevel(logging.DEBUG)   # All log messages go to the log file
    sh = logging.StreamHandler()
    sh.setLevel(loglevel)        # Some or all log messages go to the console

    logging.basicConfig(handlers=[fh, sh],
                        level=logging.DEBUG,
                        format='%(levelname)s:%(name)s %(created)14.3f - %(message)s')

    if args.address == 0:
        print('Must supply a modbus address to send the new firmware to')
        sys.exit(-1)

    tlogger = logging.getLogger('T')
    tlogger.setLevel(loglevel)
    conn = transport.Connection(hostname=args.host, devicename=args.device, port=int(args.portnum), multidrop=False, logger=tlogger)

    firmware_upload.send_hex(conn=conn, filename=args.filename, modbus_address=int(args.address))
