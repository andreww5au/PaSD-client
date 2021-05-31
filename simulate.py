#!/usr/bin/env python

import argparse
import logging
import sys
import threading

LOGFILE = 'simulate.log'


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

    if args.debug:
        loglevel = logging.DEBUG
    else:
        loglevel = logging.INFO

    logging.basicConfig(filename=LOGFILE,
                        filemode='w',
                        level=loglevel,
                        format='%(levelname)s:%(name)s %(created)14.3f - %(message)s')

    from pasd import transport
    from pasd import station
    from simulate import sim_fndh
    from simulate import sim_smartbox
    from simulate import sim_station

    tlogger = logging.getLogger('T')
    conn = transport.Connection(hostname=args.host, devicename=args.device, multidrop=args.multidrop, logger=tlogger)

    if args.task.upper() == 'SMARTBOX':
        if args.address is None:
            args.address = 1
        slogger = logging.getLogger('SB:%d' % int(args.address))
        s = sim_smartbox.SimSMARTbox(conn=conn, modbus_address=int(args.address), logger=slogger)
        simthread = threading.Thread(target=s.sim_loop, daemon=False)
        print('Simulating SMARTbox as "s" on address %d.' % int(args.address))
    elif args.task.upper() == 'FNDH':
        if args.address is None:
            args.address = 31
        flogger = logging.getLogger('FNDH:%d' % int(args.address))
        f = sim_fndh.SimFNDH(conn=conn, modbus_address=int(args.address), logger=flogger)
        simthread = threading.Thread(target=f.sim_loop, daemon=False)
        print('Simulating FNDH as "f" on address %d.' % args.address)
    elif args.task.upper() == 'STATION':
        flogger = logging.getLogger('FNDH:%d' % 31)
        s = sim_station.Sim_Station(conn=conn, modbus_address=31, logger=flogger)
        simthread = threading.Thread(target=s.sim_loop, daemon=False)
        print('Simulating entire station as "s" - FNDH on address 31, SMARTboxes on addresses 1-24.')
    elif args.task.upper() == 'MCCS':
        if args.address is None:
            args.address = 99
        mlogger = logging.getLogger('MCCS:%d' % int(args.address))
        s = station.Station(conn=conn, station_id=int(args.address), logger=mlogger)
        simthread = threading.Thread(target=s.listen, kwargs={'maxtime':999999})
        print('Simulating the MCCS as "s" in slave mode, listening on address %d' % int(args.address))
    else:
        print('Task must be one of smartbox, fndh, station or mccs - not %s. Exiting.' % args.task)
        sys.exit(-1)

    simthread.start()
    print('Started simulation thread')
