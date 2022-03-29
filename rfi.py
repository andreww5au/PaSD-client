#!/usr/bin/env python

"""
Manage a single PaSD station - control and monitor the hardware via Modbus commands to the specified IP
address, and update the relevant tables in the PaSD database. Monitor the port state tables in that database, and
send updated information as needed to the hardware in the field.
"""

import argparse
from configparser import ConfigParser as conparser
import logging
import sys
import time

DEFAULT_STATION_NUMBER = 1
CPPATH = ['/usr/local/etc/pasd.conf', '/usr/local/etc/pasd-local.conf',
          './pasd.conf', './pasd-local.conf']


def main_loop(stn):
    """
    Run forever in a loop
      -Query the field hardware to get all the current sensor and port parameters and update the instance data
      -Use the instance data to update the database sensor and port parameters
      -Query the database to look for commanded changes in station or port state
      -Write the commanded state data to the field hardware if it's different
      -Query the stations table to see if we're meant to start up, or shut down

    :param stn: An instance of station.Station()
    :return: False if there was a communications error, None if an exit was requested by setting stn.wants_exit True
    """
    while not stn.wants_exit:
        last_loop_start_time = time.time()

        # Query the field hardware to get all the current sensor and port parameters and update the instance data
        stn.poll_data()  # If station is not active, only FNDH data can be polled

        if not stn.active:
            return False

        logging.info(stn.fndh)
        data = []    # A list of (path, (timestamp, value)) objects, where path is like 'pasd.fieldtest.sb02.port07.current'
        fdict = {}
        fdict['pasd.fieldtest.fndh.psu48v1_voltage'] = stn.fndh.psu48v1_voltage
        fdict['pasd.fieldtest.fndh.psu48v2_voltage'] = stn.fndh.psu48v2_voltage
        fdict['pasd.fieldtest.fndh.psu5v_voltage'] = stn.fndh.psu5v_voltage
        fdict['pasd.fieldtest.fndh.psu48v_current'] = stn.fndh.psu48v_current
        fdict['pasd.fieldtest.fndh.psu48v_temp'] = stn.fndh.psu48v_temp
        fdict['pasd.fieldtest.fndh.psu5v_temp'] = stn.fndh.psu5v_temp
        fdict['pasd.fieldtest.fndh.pcb_temp'] = stn.fndh.pcb_temp
        fdict['pasd.fieldtest.fndh.outside_temp'] = stn.fndh.outside_temp
        fdict['pasd.fieldtest.fndh.statuscode'] = stn.fndh.statuscode
        fdict['pasd.fieldtest.fndh.indicator_code'] = stn.fndh.indicator_code
        ftime = stn.fndh.readtime
        for pnum in range(1, 29):
            p = stn.fndh.ports[pnum]
            fdict['pasd.fieldtest.fndh.port%02d.power_state' % pnum] = int(p.power_state)
            fdict['pasd.fieldtest.fndh.port%02d.power_sense' % pnum] = int(p.power_sense)
        for path, value in fdict.items():
            data.append((path, (ftime, value)))

        for sbnum, sb in stn.smartboxes.items():
            fdict = {}
            # sb.poll_data()   # Done in the station poll_data() call
            logging.info(sb)
            fdict['pasd.fieldtest.sb%02d.incoming_voltage' % sbnum] = sb.incoming_voltage
            fdict['pasd.fieldtest.sb%02d.psu_voltage' % sbnum] = sb.psu_voltage
            fdict['pasd.fieldtest.sb%02d.psu_temp' % sbnum] = sb.psu_temp
            fdict['pasd.fieldtest.sb%02d.pcb_temp' % sbnum] = sb.pcb_temp
            fdict['pasd.fieldtest.sb%02d.outside_temp' % sbnum] = sb.outside_temp
            fdict['pasd.fieldtest.sb%02d.statuscode' % sbnum] = sb.statuscode
            fdict['pasd.fieldtest.sb%02d.indicator_code' % sbnum] = sb.indicator_code
            stime = sb.readtime
            for pnum, p in sb.ports.items():
                fdict['pasd.fieldtest.sb%02d.port%02d.current' % (sbnum, pnum)] = p.current
                fdict['pasd.fieldtest.sb%02d.port%02d.breaker_tripped' % (sbnum, pnum)] = int(p.breaker_tripped)
                fdict['pasd.fieldtest.sb%02d.port%02d.power_state' % (sbnum, pnum)] = int(p.power_state)
            for snum, stemp in sb.sensor_temps.items():
                fdict['pasd.fieldtest.sb%02d.sensor%02d.temp' % (sbnum, snum)] = stemp
            for path, value in fdict.items():
                data.append((path, (stime, value)))

        logging.debug(data)

        time.sleep(max(0.0, 15 - (time.time() - last_loop_start_time)))


if __name__ == '__main__':
    CP = conparser(defaults={})
    CPfile = CP.read(CPPATH)
    if not CPfile:
        print("None of the specified configuration files found by mwaconfig.py: %s" % (CPPATH,))

    parser = argparse.ArgumentParser(description='RFI test a PaSD station',
                                     epilog='Run this as "python -i %s" to drop into the Python prompt after starting up.' % sys.argv[0])
    parser.add_argument('--host', dest='host', default=None,
                        help='Hostname of an ethernet-serial gateway, eg 134.7.50.185')
    parser.add_argument('--debug', dest='debug', default=False, action='store_true',
                        help='If given, drop to the DEBUG log level, otherwise use INFO')
    args = parser.parse_args()
    if (args.host is None) and (args.device is None):
        args.host = '(10.128.30.2'

    if args.debug:
        loglevel = logging.DEBUG
    else:
        loglevel = logging.INFO

    config = CP['station_%03d' % args.station_id]
    dbuser = config['dbuser']
    dbhost = config['dbhost']
    dbpass = config['dbpass']
    dbname = config['dbname']

    sh = logging.StreamHandler()
    sh.setLevel(loglevel)  # Some or all log messages go to the console

    logging.basicConfig(handlers=[sh],
                        level=logging.DEBUG,
                        format='%(levelname)s:%(name)s %(created)14.3f - %(message)s')

    from pasd import transport
    from pasd import station

    tlogger = logging.getLogger('T')
    if loglevel == logging.DEBUG:
        print('Setting transport log level to info, DEBUG is very spammy. All other logging is at DEBUG level.')
        tlogger.setLevel(logging.INFO)

    while True:
        conn = transport.Connection(hostname=args.host, devicename=args.device, multidrop=False, logger=tlogger)

        slogger = logging.getLogger('ST')
        s = station.Station(conn=conn,
                            station_id=args.station_id,
                            logger=slogger)

        print('Starting up entire station as "s" - FNDH on address 101, SMARTboxes on addresses 1-24.')
        s.full_startup()
        s.poll_data()

        result = main_loop(s)
        if result is False:
            logging.error('Station unreachable, trying again in 10 seconds')
            time.sleep(10)
            continue
        else:
            break
