#!/usr/bin/env python

"""
Manage a single PaSD station - control and monitor the hardware via Modbus commands to the specified IP
address, and update the relevant tables in the PaSD database. Monitor the port state tables in that database, and
send updated information as needed to the hardware in the field.
"""

import argparse
from configparser import ConfigParser as conparser
import datetime
from datetime import timezone
import logging
import sys

import psycopg2
from psycopg2 import extras

LOGFILE = 'station_lmc.log'
CPPATH = ['/usr/local/etc/pasd.conf', '/usr/local/etc/pasd-local.conf',
          './pasd.conf', './pasd-local.conf']

DEFAULT_STATION_NUMBER = 1

FNDH_STATE_QUERY = """
UPDATE fndh_state
    SET mbrv = %(mbrv)s, pcbrv = %(pcbrv)s, cpuid = %(cpuid)s, chipid = %(chipid)s, 
        firmware_version = %(firmware_version)s, uptime = %(uptime)s, psu48v1_voltage = %(psu48v1_voltage)s, 
        psu48v2_voltage = %(psu48v2_voltage)s, psu5v_voltage = %(psu5v_voltage)s, psu48v_current = %(psu48v_current)s, 
        psu48v_temp = %(psu48v_temp)s, psu5v_temp = %(psu5v_temp)s, pcb_temp = %(pcb_temp)s, 
        outside_temp = %(outside_temp)s, status = %(status)s, indicator_state = %(indicator_state)s, 
        readtime = %(readtime)s
    WHERE (station_id = %(station_id)s)
"""

FNDH_PORT_QUERY = """
UPDATE fndh_port_status
    SET smartbox_number = %(smartbox_address)s, system_online = %(system_online)s, 
        locally_forced_on = %(locally_forced_on)s, locally_forced_off = %(locally_forced_off)s, 
        power_state = %(power_state)s, power_sense = %(power_sense)s, status_timestamp = %(status_timestamp)s
    WHERE (station_id = %(station_id)s) AND (pdoc_number = %(port_number)s)
"""

SMARTBOX_STATE_QUERY = """
UPDATE smartbox_state
    SET mbrv = %(mbrv)s, pcbrv = %(pcbrv)s, cpuid = %(cpuid)s, chipid = %(chipid)s, 
        firmware_version = %(firmware_version)s, uptime = %(uptime)s, incoming_voltage = %(incoming_voltage)s, 
        psu_voltage = %(psu_voltage)s, psu_temp = %(psu_temp)s, pcb_temp = %(pcb_temp)s, 
        outside_temp = %(outside_temp)s, status = %(status)s,
        indicator_state = %(indicator_state)s, readtime = %(readtime)s, pdoc_number = %(pdoc_number)s
    WHERE (station_id = %(station_id)s) AND (smartbox_number = %(modbus_address)s)
"""

SMARTBOX_PORT_QUERY = """
UPDATE smartbox_port_status
    SET system_online = %(system_online)s, current_draw = %(current)s, locally_forced_on = %(locally_forced_on)s, 
        locally_forced_off = %(locally_forced_off)s, breaker_tripped = %(breaker_tripped)s, 
        power_state = %(power_state)s, status_timestamp = %(status_timestamp)s, 
        current_timestamp = %(current_timestamp)s
    WHERE (station_id = %(station_id)s) AND (smartbox_number = %(modbus_address)s) AND (port_number = %(port_number)s)
"""


def initialise_db(db, stn):
    """
    Make sure that all state rows in the database tables exist (with empty contents), so that future writes can just
    use 'update' queries instead of checking to see if they need to do 'insert' instead'.

    If more than one row exists for any FNDH/smartbox/port, delete all of the duplicates and create a new empty row.

    :param db: Database connection object
    :param stn: An instance of station.Station(), used to get the station number.
    :return:
    """
    with db:
        with db.cursor() as curs:
            curs.execute('SELECT COUNT(*) FROM fndh_state WHERE (station_id = %s)', (stn.station_id,))
            if curs.fetchone[0] != 1:   # No rows match, or more than one row matches:
                curs.execute('DELETE FROM fndh_state WHERE (station_id = %s)', (stn.station_id,))
                curs.execute('INSERT INTO fndh_state (station_id) VALUES (%s)', (stn.station_id,))

            for pnum in range(1, 29):
                curs.execute('SELECT COUNT(*) FROM fndh_port_status WHERE (station_id = %s) AND (pdoc_number = %s)',
                             (stn.station_id, pnum))
                if curs.fetchone[0] != 1:   # No rows match, or more than one row matches:
                    curs.execute('DELETE FROM fndh_port_status WHERE (station_id = %s) AND (pdoc_number = %s)',
                                 (stn.station_id, pnum))
                    curs.execute('INSERT INTO fndh_port_status (station_id, pdoc_number) VALUES (%s, %s)',
                                 (stn.station_id, pnum))

            for sb_num in range(1, 25):
                curs.execute('SELECT COUNT(*) FROM smartbox_state WHERE (station_id = %s) AND (smartbox_number = %s)',
                             (stn.station_id, sb_num))
                if curs.fetchone[0] != 1:   # No rows match, or more than one row matches:
                    curs.execute('DELETE FROM smartbox_state WHERE (station_id = %s) AND (smartbox_number = %s)',
                                 (stn.station_id, sb_num))
                    curs.execute('INSERT INTO smartbox_state (station_id, smartbox_number) VALUES (%s, %s)',
                                 (stn.station_id, sb_num))

                for pnum in range(1, 13):
                    curs.execute('SELECT COUNT(*) FROM smartbox_port_status WHERE (station_id = %s) AND (smartbox_number = %s) AND (port_number = %s)',
                                 (stn.station_id, sb_num, pnum))
                    if curs.fetchone[0] != 1:   # No rows match, or more than one row matches:
                        curs.execute('DELETE FROM smartbox_port_status WHERE (station_id = %s) AND (smartbox_number = %s) AND (port_number = %s)',
                                     (stn.station_id, sb_num, pnum))
                        curs.execute('INSERT INTO smartbox_port_status (station_id, smartbox_number, port_number) VALUES (%s, %s, %s)',
                                     (stn.station_id, sb_num, pnum))


def update_db(db, stn):
    """
    Write current instance data to the database (FNDH state, all 28 FNDH port states, all 24 smartbox states,
    and all 288 smartbox ports states.

    :param db: Database connection object
    :param stn: An instance of station.Station(), with contents to write the database.
    :return:
    """
    # FNDH state table:
    with db:   # Commit transaction when block exits
        with db.cursor() as curs:
            stn.fndh.station_id = stn.station_id
            curs.execute(FNDH_STATE_QUERY, stn.fndh.__dict__)

    fpdata_list = []
    for pnum, port in stn.fndh.ports.items():
        tmpdict = port.__dict__.copy()
        tmpdict['smartbox_number'] = stn.station_id
        fpdata_list.append(tmpdict)

    # FNDH port table:
    with db:  # Commit transaction when block exits
        with db.cursor() as curs:
            psycopg2.extras.execute_batch(curs, FNDH_PORT_QUERY, fpdata_list)

    # Smartbox port table
    sb_data_list = []          # Will end up with 24 dicts, one for each smartbox state
    sb_ports_data_list = []    # Will end up with 288 dicts, one for each port state
    if stn.active:   # If the station is active, we have real smartbox data to send
        for sb_num, sb in stn.smartboxes.items():
            sb.station_id = stn.station_id
            sb_data_list.append(sb.__dict__)
            for pnum, port in sb.ports:
                port.station_id = stn.station_id
                sb_ports_data_list.append(port.__dict__)
    else:    # If the station is not active (smartboxes are all off), fill in empty smartbox data
        for sb_num in range(1, 25):
            for portnum in range(1, 13):
                spdata = {'station_id':stn.station_id, 'modbus_address':sb_num, 'port_number':portnum,
                          'system_online':None, 'current_draw':None, 'locally_forced_on':None,
                          'locally_forced_off':None, 'breaker_tripped':None,
                          'power_state':None, 'status_timestamp':datetime.datetime.now(timezone.utc),
                          'current_timestamp':None}
                sb_ports_data_list.append(spdata)

    with db:  # Commit transaction when block exits
        with db.cursor() as curs:
            psycopg2.extras.execute_batch(curs, SMARTBOX_STATE_QUERY, sb_data_list)
            psycopg2.extras.execute_values(curs, SMARTBOX_PORT_QUERY, sb_ports_data_list)


def get_antenna_map(db, station_number=DEFAULT_STATION_NUMBER):
    """
    Query the database to find the antenna->smartbox/port mapping, and return it as a dict of dicts.

    The returned dict has smartbox address (1-24) as key. The values are dicts with port number (1-12) as key,
    and antenna number (1-256) as value (or None). All 288 possible smartbox ports must be in the antenna map.

    :params db: Database connection object
    :param station_number: Station ID (1-9999)
    :return: Antenna map (dict of dicts)
    """
    # Create antenna map structure with all 288 ports set to None, to make sure none are missing
    ant_map = {}
    for sid in range(1, 25):
        ant_map[sid] = {pid:None for pid in range(1, 13)}

    with db:   # Commit transaction when block exits
        with db.cursor() as curs:
            query = """SELECT antenna_number, smartbox_number, port_number
                       FROM antenna_portmap
                       WHERE (station_id=%s) and begintime < now() and endtime > now()
            """
            curs.execute(query, (station_number,))

            # Fill in mapping data from the query
            for row in curs:
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

    :param db: Database connection object
    :param station_number: Station ID (1-9999)
    :return: port configuration for that smartbox (dict of dicts)
    """
    with db:   # Commit transaction when block exits
        with db.cursor() as curs:
            # Read FNDH port config for this station:
            query = """SELECT pdoc_number, desire_enabled_online, desire_enabled_offline
                       FROM fndh_port_status
                       WHERE station_id=%s"""
            curs.execute(query, (station_number,))

            fndhpc = {i:[False, False] for i in range(1, 29)}
            for row in curs:
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
            for row in curs:
                smartbox_number, port_number, desire_enabled_online, desire_enabled_offline = row
                sbpc[smartbox_number][port_number] = bool(desire_enabled_online), bool(desire_enabled_offline)

    return fndhpc, sbpc


def main_loop(db, stn):
    """
    Run forever in a loop
      -Query the field hardware to get all the current sensor and port parameters and update the instance data
      -Use the instance data to update the database sensor and port parameters
      -Query the database to look for commanded changes in station or port state
      -Write the commanded state data to the field hardware

    :param db: Database connection object
    :param stn: An instance of station.Station()
    :return:
    """
    while not stn.wants_exit:
        # Query the field hardware to get all the current sensor and port parameters and update the instance data
        stn.poll_data()  # If station is not active, only FNDH data can be polled

        # Use the instance data to update the database sensor and port parameters
        query = ""


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
