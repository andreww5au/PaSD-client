#!/usr/bin/env python

import argparse
import logging
import sys

from pasd import transport
from pasd import fndh
from pasd import smartbox
from pasd import station
from sid import mccs


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Communicate with a remote SMARTbox, FNDH, an entire station, or the MCCS, by sending packets in "master" mode.',
                                     epilog='Run this as "python -i %s" to drop into the Python prompt after starting up.' % sys.argv[0])
    parser.add_argument('task', nargs='?', default='station', help='What to talk to - smartbox, fndh, station or mccs')
    parser.add_argument('--host', dest='host', default=None,
                        help='Hostname of an ethernet-serial gateway, eg 134.7.50.185')
    parser.add_argument('--device', dest='device', default=None,
                        help='Serial port device name, eg /dev/ttyS0 or COM6')
    parser.add_argument('--multidrop', dest='multidrop', action='store_true', default=False,
                        help='Open connection in multidrop mode, so you can attach extra devices in "python -i ..." mode')
    parser.add_argument('--address', dest='address', default=1,
                        help='Modbus address (ignored when talking to an entire station)')
    parser.add_argument('--debug', dest='debug', default=False, action='store_true',
                        help='If given, drop to the DEBUG log level, otherwise use INFO')
    args = parser.parse_args()
    if (args.host is None) and (args.device is None):
        args.host = '134.7.50.185'
    conn = transport.Connection(hostname=args.host, devicename=args.device, multidrop=args.multidrop)

    if args.debug:
        loglevel = logging.DEBUG
    else:
        loglevel = logging.INFO
    transport.logger.level = loglevel
    fndh.logger.level = loglevel
    smartbox.logger.level = loglevel
    station.logger.level = loglevel
    mccs.logger.level = loglevel

    if args.task.upper() == 'SMARTBOX':
        s = smartbox.SMARTbox(conn=conn, modbus_address=args.address)
        print('Polling SMARTbox as "s" on address %d.' % args.address)
        s.poll_data()
        print('Configuring SMARTbox as "s" on address %d.' % args.address)
        s.configure()
    elif args.task.upper() == 'FNDH':
        f = fndh.FNDH(conn=conn, modbus_address=args.address)
        print('Polling FNDH as "f" on address %d.' % args.address)
        f.poll_data()
        print('Configuring all-off on FNDH as "f" on address %d.' % args.address)
        f.configure_all_off()
        print('Final configuring FNDH as "f" on address %d.' % args.address)
        f.configure_final()
    elif args.task.upper() == 'STATION':
        s = station.Station(conn=conn, station_id=1)
        print('Starting up entire station as "s" - FNDH on address 31, SMARTboxes on addresses 1-24.')
        s.startup()
    elif args.task.upper() == 'MCCS':
        m = mccs.MCCS(conn=conn, modbus_address=args.address)
        print('Reading antenna configuration from MCCS as "m" on address %d.' % args.address)
        m.read_antennae()
    else:
        print('Task must be one of smartbox, fndh, station or mccs - not %s. Exiting.' % args.task)
        sys.exit(-1)
