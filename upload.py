#!/usr/bin/env python

import argparse
from configparser import ConfigParser as conparser
from datetime import datetime
import logging
import os
import socket
import sys

LOGFILE = 'upload-%s.log' % (datetime.now().strftime('%Y-%m-%dT%H-%M-%S'))
CPPATH = ['/usr/local/etc/pasd.conf', '/usr/local/etc/pasd-local.conf',
          './pasd.conf', './pasd-local.conf']

DEFAULT_FNDH = '10.128.30.1'     # pasd-fndh.mwa128t.org

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
    CP = conparser(defaults={})
    CPfile = CP.read(CPPATH)
    if not CPfile:
        print("None of the specified configuration files found by mwaconfig.py: %s" % (CPPATH,))

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
    parser.add_argument('--force', dest='force', default=False, action='store_true',
                        help='Ignore any filename/address/PCB-revision checks')
    parser.add_argument('--nowrite', dest='nowrite', default=False, action='store_true',
                        help="Don't actually upload the firmware, just do all the checks.")
    args = parser.parse_args()

    if (args.host is None) and (args.device is None) and CPfile:
        args.host = CP.get('default', 'fndh_host', fallback=DEFAULT_FNDH)

    if os.path.basename(args.filename).upper().startswith('FNPC'):
        if (int(args.address) not in [31, 101]):
            print('Trying to push FNPC image to a smartbox, weather station or FNCC? %s' % args.filename)
            print('Filename must start with "FNPC" (and go to address 31 or 101), or "SBox" (and go to address 1-24).')
            if not args.force:
                print('Exiting.')
                sys.exit(-1)
            else:
                print("Proceeding to risk bricking the hardware anyway, as --force specified. ")
    elif os.path.basename(args.filename).upper().startswith('SBOX'):
        if (int(args.address) not in list(range(1, 25))):
            print('Trying to push smartbox image to an FNPC, weather station or FNCC?? %s' % args.filename)
            print('Filename must start with "FNPC" (and go to address 31 or 101), or "SBox" (and go to address 1-24).')
            if not args.force:
                print('Exiting.')
                sys.exit(-1)
            else:
                print("Proceeding to risk bricking the hardware anyway, as --force specified. ")
    elif os.path.basename(args.filename).upper().startswith('FNCC'):
        if (int(args.address) != 100):
            print('Trying to push FNCC image to a smartbox, weather station or FNPC? %s' % args.filename)
            print('Filename must start with "FNPC" (and go to address 31 or 101), or ')
            print('    "SBox" (and go to address 1-24) or "FNCC" (and go to address 100).')
            if not args.force:
                print('Exiting.')
                sys.exit(-1)
            else:
                print("Proceeding to risk bricking the hardware anyway, as --force specified. ")
    elif os.path.basename(args.filename).upper().startswith('WEATH'):
        if (int(args.address) != 103):
            print('Trying to push Weather image to a smartbox, FNPC or FNCC? %s' % args.filename)
            print('Filename must start with "FNPC" (and go to address 31 or 101), or ')
            print('    "SBox" (and go to address 1-24) or "FNCC" (and go to address 100).')
            if not args.force:
                print('Exiting.')
                sys.exit(-1)
            else:
                print("Proceeding to risk bricking the hardware anyway, as --force specified. ")
    else:
        print('Filename must start with "FNPC" (to address 31 or 101), or "SBox" (to address 1-24),')
        print('or "FNCC" (to address 100), or "WEATH" (to address 103).')
        if not args.force:
            print('Exiting.')
            sys.exit(-1)
        else:
            print("Proceeding to risk bricking the hardware anyway, as --force specified. ")

    if args.address == 0:
        print('Must supply a modbus address to send the new firmware to')
        sys.exit(-1)

    tlogger = logging.getLogger('T')
    conn = transport.Connection(hostname=args.host, devicename=args.device, port=int(args.portnum), multidrop=False, logger=tlogger)

    ok = command_api.send_hex(conn=conn,
                              filename=args.filename,
                              modbus_address=int(args.address),
                              force=args.force,
                              nowrite=args.nowrite)
    if ok and not args.nowrite:
        print('Resetting microcontroller.')
        command_api.reset_microcontroller(conn, int(args.address), logger=logging)
