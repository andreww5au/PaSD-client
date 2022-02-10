#!/usr/bin/env python

import atexit
import argparse
import logging
import sys
import threading

LOGFILE = 'simulate.log'
SIM_OBJECT = None   # Set to the smartbox, fndh or station instance when it's started


def cleanup():
    """Called automatically on exit - sets .wants_exit=True on the simulated object, so that the transport
       and simulation threads shut down cleanly.
    """
    print('Cleanup called.')
    if SIM_OBJECT is not None:
        SIM_OBJECT.wants_ext = True


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

    fh = logging.FileHandler(filename=LOGFILE, mode='w')
    fh.setLevel(logging.DEBUG)   # All log messages go to the log file
    sh = logging.StreamHandler()
    sh.setLevel(loglevel)        # Some or all log messages go to the console
    logformat = '%(levelname)s:%(name)s %(created)14.3f - %(threadName)s: %(message)s'
    # noinspection PyArgumentList
    logging.basicConfig(handlers=[fh, sh],
                        level=logging.DEBUG,
                        format=logformat)

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
        s = SIM_OBJECT = sim_smartbox.SimSMARTbox(conn=conn, modbus_address=int(args.address), logger=slogger)
        simthread = threading.Thread(target=s.sim_loop, daemon=False, name='SB.thread')
        print('Simulating SMARTbox as "s" on address %d.' % int(args.address))
    elif args.task.upper() == 'FNDH':
        if args.address is None:
            args.address = 101
        flogger = logging.getLogger('FNDH:%d' % int(args.address))
        f = SIM_OBJECT = sim_fndh.SimFNDH(conn=conn, modbus_address=int(args.address), logger=flogger)
        simthread = threading.Thread(target=f.sim_loop, daemon=False, name='FNDH.thread')
        print('Simulating FNDH as "f" on address %d.' % args.address)
    elif args.task.upper() == 'STATION':
        flogger = logging.getLogger('FNDH:%d' % 31)
        s = SIM_OBJECT = sim_station.Sim_Station(conn=conn, modbus_address=101, logger=flogger)
        simthread = threading.Thread(target=s.sim_loop, daemon=False, name='FNDH.thread')
        print('Simulating entire station as "s" - FNDH on address 101, SMARTboxes on addresses 1-24.')
    elif args.task.upper() == 'MCCS':
        if args.address is None:
            args.address = 199
        mlogger = logging.getLogger('MCCS:%d' % int(args.address))
        s = SIM_OBJECT = station.Station(conn=conn, station_id=int(args.address), logger=mlogger)
        simthread = threading.Thread(target=s.listen, daemon=False, kwargs={'maxtime':999999}, name='MCCS.thread')
        print('Simulating the MCCS as "s" in slave mode, listening on address %d' % int(args.address))
    else:
        print('Task must be one of smartbox, fndh, station or mccs - not %s. Exiting.' % args.task)
        sys.exit(-1)

    atexit.register(cleanup)

    simthread.start()
    print('Started simulation thread')
