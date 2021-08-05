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

import psycopg2


LOGFILE = 'station_lmc.log'
CPPATH = ['/usr/local/etc/pasd.conf', '/usr/local/etc/pasd-local.conf',
          './pasd.conf', './pasd-local.conf']

DEFAULT_STATION_NUMBER = 1


def get_antenna_map(db, station_number=DEFAULT_STATION_NUMBER):
    """
    Query the database to find the antenna->smartbox/port mapping, and return it as a dict of dicts.

    The returned dict has smartbox address (1-24) as key. The values are dicts with port number (1-12) as key,
    and antenna number (1-256) as value (or None). All 288 possible smartbox ports must be in the antenna map.

    :params db: Database connection object
    :return: Antenna map (dict of dicts)
    """
    curs = db.cursor()
    query = """SELECT antenna_number, smartbox_number, port_number
               FROM antenna_portmap
               WHERE (station_id=%s) and begintime < now() and endtime > now()
    """
    curs.execute(query, (station_number,))

    # Create antenna map structure with all 288 ports set to None, to make sure none are missing
    ant_map = {}
    for sid in range(1, 25):
        ant_map[sid] = {pid:None for pid in range(1, 13)}

    # Fill in mapping data from the query
    rows = curs.fetchall()
    for row in rows:
        antenna_number, smartbox_number, port_number = row
        ant_map[smartbox_number][port_number] = antenna_number

    return ant_map


def get_all_port_configs(db, station_number=DEFAULT_STATION_NUMBER):
    """
    Query the database to get the smartbox port state dictionary, for all smartboxes.

    Result is a tuple of two dictionaries - the first contains all 28 FNDH port configs, the second all 288 smartbox
    port configs.

    The FNDH port config dictionary is a dict with port number (1-28) as key, and a list of two booleans of 0/1
    integers as value, where the first item is the 'desire_enabled_online', and the second is the
    'desire_enabled_offline'.

    The smartbox port dictionary has smartbox number as the key. Each value is a dict with port number (1-12) as key, and a
    list of two booleans of 0/1 integers as value, where the first item is the 'desire_enabled_online', and the second
    is the 'desire_enabled_offline'.

    :param db:
    :param station_number:
    :return: port configuration for that smartbox (dict of dicts)
    """
    curs = db.cursor()

    # Read FNDH port config for this station:
    query = """SELECT pdoc_number, desire_enabled_online, desire_enabled_offline
               FROM fndh_port_status
               WHERE station_id=%s"""
    curs.execute(query, (station_number,))

    fndhpc = {i:[False, False] for i in range(1, 29)}
    rows = curs.fetchall()
    for row in rows:
        pdoc_number, desire_enabled_online, desire_enabled_offline = row
        fndhpc[pdoc_number] = bool(desire_enabled_online), bool(desire_enabled_offline)

    # Read all smartbox port configs for this station:
    query = """SELECT smartbox_number, port_number, desire_enabled_online, desire_enabled_offline
               FROM smartbox_port_status
               WHERE station_id=%s"""
    curs.execute(query, (station_number,))

    sbpc = {}
    for sid in range(1, 25):
        sbpc[sid] = {i:[False, False] for i in range(1, 13)}
    rows = curs.fetchall()
    for row in rows:
        smartbox_number, port_number, desire_enabled_online, desire_enabled_offline = row
        sbpc[smartbox_number][port_number] = bool(desire_enabled_online), bool(desire_enabled_offline)

    return fndhpc, sbpc


def main_loop(stn=None):
    """
    Run forever in a loop
      -query the field hardware to get all the current sensor and port parameters and update the instance data
      -use the instance data to update the database sensor and port parameters
      -query the database to look for commanded changes in station or port state
      -write the commanded state data to the field hardware

    :param stn: An instance of station.Station()
    :return:
    """


if __name__ == '__main__':
    CP = conparser(defaults={})
    CPfile = CP.read(CPPATH)
    if not CPfile:
        print("None of the specified configuration files found by mwaconfig.py: %s" % (CPPATH,))

    parser = argparse.ArgumentParser(description='Run a PaSD station',
                                     epilog='Run this as "python -i %s" to drop into the Python prompt after starting up.' % sys.argv[0])
    parser.add_argument('--host', dest='host', default=None,
                        help='Hostname of an ethernet-serial gateway, eg 134.7.50.185')
    parser.add_argument('--device', dest='device', default=None,
                        help='Serial port device name, eg /dev/ttyS0 or COM6')
    parser.add_argument('--id', '--station_id', dest='station_id', default=DEFAULT_STATION_NUMBER,
                        help='Station number (1-9999)')
    args = parser.parse_args()
    if (args.host is None) and (args.device is None):
        args.host = '134.7.50.185'

    if args.debug:
        loglevel = logging.DEBUG
    else:
        loglevel = logging.INFO

    config = CP['station_%03d' % args.station_id]
    dbuser = config['dbuser']
    dbhost = config['dbhost']
    dbpass = config['dbpass']
    dbname = config['dbname']

    db = psycopg2.connect(user=dbuser, password=dbpass, host=dbhost, database=dbname)

    fh = logging.FileHandler(filename=LOGFILE, mode='w')
    fh.setLevel(logging.DEBUG)  # All log messages go to the log file
    sh = logging.StreamHandler()
    sh.setLevel(loglevel)  # Some or all log messages go to the console

    logging.basicConfig(handlers=[fh, sh],
                        level=logging.DEBUG,
                        format='%(levelname)s:%(name)s %(created)14.3f - %(message)s')

    from pasd import transport
    from pasd import station

    tlogger = logging.getLogger('T')
    if loglevel == logging.DEBUG:
        print('Setting transport log level to info, DEBUG is very spammy. All other logging is at DEBUG level.')
        tlogger.setLevel(logging.INFO)

    conn = transport.Connection(hostname=args.host, devicename=args.device, multidrop=False, logger=tlogger)

    fndhpc, sbpc = get_all_port_configs(db, station_number=args.station_id)

    slogger = logging.getLogger('ST')
    s = station.Station(conn=conn,
                        station_id=args.station_id,
                        antenna_map=get_antenna_map(db, args.station_id),
                        portconfig_fndh=fndhpc,
                        portconfig_smartboxes=sbpc,
                        logger=slogger)
    print('Starting up entire station as "s" - FNDH on address 31, SMARTboxes on addresses 1-24.')
