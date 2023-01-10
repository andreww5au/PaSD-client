#!/usr/bin/env python

import argparse
from configparser import ConfigParser as conparser
import logging
import sys

LOGFILE = 'communicate.log'
CPPATH = ['/usr/local/etc/pasd.conf', '/usr/local/etc/pasd-local.conf',
          './pasd.conf', './pasd-local.conf']

DEFAULT_FNDH = '10.128.30.1'     # pasd-fndh.mwa128t.org


if __name__ == '__main__':
    CP = conparser(defaults={})
    CPfile = CP.read(CPPATH)
    if not CPfile:
        print("None of the specified configuration files found by mwaconfig.py: %s" % (CPPATH,))

    parser = argparse.ArgumentParser(description='Communicate with a remote SMARTbox, FNDH, FNCC, an entire station, or the MCCS, by sending packets in "master" mode.',
                                     epilog='Run this as "python -i %s" to drop into the Python prompt after starting up.' % sys.argv[0])
    parser.add_argument('task', nargs='?', default='station', help='What to talk to - smartbox, fndh, station or mccs')
    parser.add_argument('--host', dest='host', default=None,
                        help='Hostname of an ethernet-serial gateway, eg 134.7.50.185')
    parser.add_argument('--device', dest='device', default=None,
                        help='Serial port device name, eg /dev/ttyS0 or COM6')
    parser.add_argument('--portnum', dest='portnum', default=5000,
                        help='TCP port number to use')
    parser.add_argument('--address', dest='address', default=None,
                        help='Modbus address (ignored when talking to an entire station)')
    parser.add_argument('--debug', dest='debug', default=False, action='store_true',
                        help='If given, drop to the DEBUG log level, otherwise use INFO')
    args = parser.parse_args()

    if (args.host is None) and (args.device is None):
        args.host = CP.get('default', 'fndh_host', fallback=DEFAULT_FNDH)

    if args.debug:
        loglevel = logging.DEBUG
    else:
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
    from pasd import fndh
    from pasd import fncc
    from pasd import smartbox
    from pasd import weather
    from pasd import station
    from sid import mccs

    tlogger = logging.getLogger('T')
    conn = transport.Connection(hostname=args.host, devicename=args.device, port=int(args.portnum), baudrate=19200, multidrop=False, logger=tlogger)

    if args.task.upper() == 'SMARTBOX':
        if args.address is None:
            args.address = 1
        slogger = logging.getLogger('SB:%d' % int(args.address))
        s = smartbox.SMARTbox(conn=conn, modbus_address=int(args.address), logger=slogger)
        print('Polling SMARTbox as "s" on address %d.' % int(args.address))
        s.poll_data()
        print('Configuring SMARTbox as "s" on address %d.' % int(args.address))
        s.configure()
        s.poll_data()
        print(s)
    elif args.task.upper() == 'FNDH':
        if args.address is None:
            args.address = 101
        flogger = logging.getLogger('FNDH:%d' % int(args.address))
        f = fndh.FNDH(conn=conn, modbus_address=int(args.address), logger=flogger)
        print('Polling FNDH as "f" on address %d.' % int(args.address))
        f.poll_data()
        print('Configuring all-off on FNDH as "f" on address %d.' % int(args.address))
        f.configure_all_off()
        print('Final configuring FNDH as "f" on address %d.' % int(args.address))
        f.configure_final()
        f.poll_data()
        print(f)
    elif args.task.upper() == 'FNCC':
        if args.address is None:
            args.address = 100
        flogger = logging.getLogger('FNCC:%d' % int(args.address))
        fc = fncc.FNCC(conn=conn, modbus_address=int(args.address), logger=flogger)
        print('Polling FNCC as "fc" on address %d.' % int(args.address))
        fc.poll_data()
        print(fc)
    elif args.task.upper() == 'WEATHER':
        if args.address is None:
            args.address = 103
        flogger = logging.getLogger('FNCC:%d' % int(args.address))
        w = weather.Weather(conn=conn, modbus_address=int(args.address), logger=flogger)
        print('Polling weather station as "w" on address %d.' % int(args.address))
        w.poll_data()
        print(w)
    elif args.task.upper() == 'STATION':
        slogger = logging.getLogger('ST')
        s = station.Station(conn=conn, station_id=1, logger=slogger)
        print('Starting up entire station as "s" - FNDH on address 101, SMARTboxes on addresses 1-24.')
        s.fieldtest_startup()
    elif args.task.upper() == 'MCCS':
        if args.address is None:
            args.address = 199
        mlogger = logging.getLogger('MCCS:%d' % int(args.address))
        m = mccs.MCCS(conn=conn, modbus_address=int(args.address), logger=mlogger)
        print('Reading antenna configuration from MCCS as "m" on address %d.' % int(args.address))
        m.read_antennae()
    else:
        print('Task must be one of smartbox, fndh, station or mccs - not %s. Exiting.' % args.task)
        sys.exit(-1)
