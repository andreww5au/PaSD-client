#!/usr/bin/env python

import argparse
import logging
import sys
import threading

from pasd import transport
from pasd import station
from simulate import sim_fndh
from simulate import sim_smartbox
from simulate import sim_station


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Simulate a SMARTbox, FNDH, an entire station, or the MCCS, and listen forever in "slave" mode for packets',
                                     epilog='Run this as "python -i %s" to drop into the Python prompt after starting up.' % sys.argv[0])
    parser.add_argument('task', nargs='?', default='station', help='What to simulate - smartbox, fndh, station or mccs')
    parser.add_argument('--host', dest='host', default=None,
                        help='Hostname of an ethernet-serial gateway, eg 134.7.50.185')
    parser.add_argument('--device', dest='device', default=None,
                        help='Serial port device name, eg /dev/ttyS0 or COM6')
    parser.add_argument('--multidrop', dest='multidrop', action='store_true', default=False,
                        help='Open connection in multidrop mode, so you can attach extra devices in "python -i ..." mode')
    parser.add_argument('--address', dest='address', default=None,
                        help='Modbus address (ignored when simulating a station)')
    parser.add_argument('--debug', dest='debug', default=False, action='store_true',
                        help='If given, drop to the DEBUG log level, otherwise use INFO')
    args = parser.parse_args()
    if (args.host is None) and (args.device is None):
        args.host = '134.7.50.185'
    if args.task.upper() == 'STATION':
        args.multidrop = True
    conn = transport.Connection(hostname=args.host, devicename=args.device, multidrop=args.multidrop)

    if args.debug:
        loglevel = logging.DEBUG
    else:
        loglevel = logging.INFO
    transport.logger.level = loglevel
    station.logger.level = loglevel
    sim_fndh.logger.level = loglevel
    sim_smartbox.logger.level = loglevel
    sim_station.logger.level = loglevel

    if args.task.upper() == 'SMARTBOX':
        if args.address is None:
            args.address = 1
        s = sim_smartbox.SimSMARTbox(conn=conn, modbus_address=args.address)
        simthread = threading.Thread(target=s.mainloop, daemon=False)
        print('Simulating SMARTbox as "s" on address %d.' % args.address)
    elif args.task.upper() == 'FNDH':
        if args.address is None:
            args.address = 31
        f = sim_fndh.SimFNDH(conn=conn, modbus_address=args.address)
        simthread = threading.Thread(target=f.mainloop, daemon=False)
        print('Simulating FNDH as "f" on address %d.' % args.address)
    elif args.task.upper() == 'STATION':
        s = sim_station.Sim_Station(conn=conn, modbus_address=31)
        simthread = threading.Thread(target=s.mainloop, daemon=False)
        print('Simulating entire station as "s" - FNDH on address 31, SMARTboxes on addresses 1-24.')
    elif args.task.upper() == 'MCCS':
        if args.address is None:
            args.address = 99
        s = station.Station(conn=conn, station_id=args.address)
        simthread = threading.Thread(target=s.listen, kwargs={'maxtime':999999})
        print('Simulating the MCCS as "s" in slave mode, listening on address %d' % args.address)
    else:
        print('Task must be one of smartbox, fndh, station or mccs - not %s. Exiting.' % args.task)
        sys.exit(-1)

    simthread.start()
    print('Started simulation thread')
