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
import pickle
import socket
import struct
import sys
import time
import traceback

import psycopg2
from psycopg2 import extras

LOGFILE = 'station_lmc.log'
CPPATH = ['/usr/local/etc/pasd.conf', '/usr/local/etc/pasd-local.conf',
          './pasd.conf', './pasd-local.conf']

CARBON_HOST = 'icinga.mwa128t.org'
DEFAULT_FNDH = '10.128.30.1'     # pasd-fndh.mwa128t.org

DEFAULT_STATION_NUMBER = 1

FNDH_STATE_QUERY = """
UPDATE pasd_fndh_state
    SET mbrv = %(mbrv)s, pcbrv = %(pcbrv)s, cpuid = %(cpuid)s, chipid = %(chipid)s, 
        firmware_version = %(firmware_version)s, uptime = %(uptime)s, psu48v1_voltage = %(psu48v1_voltage)s, 
        psu48v2_voltage = %(psu48v2_voltage)s, psu48v_current = %(psu48v_current)s, 
        psu48v1_temp = %(psu48v1_temp)s, psu48v2_temp = %(psu48v2_temp)s, panel_temp = %(panel_temp)s, 
        fncb_temp = %(fncb_temp)s, fncb_humidity = %(fncb_humidity)s, status = %(status)s, indicator_state = %(indicator_state)s, 
        readtime = %(readtime)s, service_led = %(service_led)s
    WHERE (station_id = %(station_id)s)
"""

FNDH_PORT_QUERY = """
UPDATE pasd_fndh_port_status
    SET smartbox_number = %(smartbox_address)s, system_online = %(system_online)s, 
        locally_forced_on = %(locally_forced_on)s, locally_forced_off = %(locally_forced_off)s, 
        power_state = %(power_state)s, power_sense = %(power_sense)s, status_timestamp = %(status_datetime)s
    WHERE (station_id = %(station_id)s) AND (pdoc_number = %(port_number)s)
"""

SMARTBOX_STATE_QUERY = """
UPDATE pasd_smartbox_state
    SET mbrv = %(mbrv)s, pcbrv = %(pcbrv)s, cpuid = %(cpuid)s, chipid = %(chipid)s, 
        firmware_version = %(firmware_version)s, uptime = %(uptime)s, incoming_voltage = %(incoming_voltage)s, 
        psu_voltage = %(psu_voltage)s, psu_temp = %(psu_temp)s, pcb_temp = %(pcb_temp)s, 
        outside_temp = %(outside_temp)s, status = %(status)s, service_led = %(service_led)s,
        indicator_state = %(indicator_state)s, readtime = %(readtime)s, pdoc_number = %(pdoc_number)s
    WHERE (station_id = %(station_id)s) AND (smartbox_number = %(modbus_address)s)
"""

SMARTBOX_PORT_QUERY = """
UPDATE pasd_smartbox_port_status
    SET system_online = %(system_online)s, current_draw = %(current)s, locally_forced_on = %(locally_forced_on)s, 
        locally_forced_off = %(locally_forced_off)s, breaker_tripped = %(breaker_tripped)s, 
        power_state = %(power_state)s, status_timestamp = %(status_datetime)s, 
        current_draw_timestamp = %(current_datetime)s
    WHERE (station_id = %(station_id)s) AND (smartbox_number = %(modbus_address)s) AND (port_number = %(port_number)s)
"""


LAST_STARTUP_ATTEMPT_TIME = 0   # Timestamp for the last time we tried to start up the station
STARTUP_RETRY_INTERVAL = 600    # If the station isn't active, but is meant to be, wait this long before retrying startup
LAST_SHUTDOWN_ATTEMPT_TIME = 0   # Timestamp for the last time we tried to shut down the station
SHUTDOWN_RETRY_INTERVAL = 600    # If the station is active, but isnt meant to be, wait this long before retrying shutdown


def send_carbon(data):
    """
    Send a list of tuples to carbon_cache on the icinga VM
    :param data:  A list of (path, (timestamp, value)) objects, where path is like 'pasd.fieldtest.sb2.port7.current'
    :return: None
    """
    if not CARBON_HOST:
        return
    payload = pickle.dumps(data, protocol=2)  # dumps() returns a bytes object
    header = struct.pack("!L", len(payload))  # pack() returns a bytes object
    try:
        sock = socket.create_connection((CARBON_HOST, 2004))
        message = header + payload
        msize = len(message)
        sentbytes = 0
        tries = 0
        while (sentbytes < msize) and (tries < 10):
            sentbytes += sock.send(message[sentbytes:])
            time.sleep(0.05)
            tries += 1
        sock.close()
        if sentbytes < msize:
            print("Tried %d times, but sent only %d bytes out of %d to Carbon" % (tries, sentbytes, msize))
    except:
        print("Exception in socket transfer to Carbon on port 2004")
        traceback.print_exc()


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
            curs.execute('SELECT COUNT(*) FROM pasd_stations WHERE (station_id = %s)', (stn.station_id,))
            if curs.fetchone()[0] != 1:  # No rows match, or more than one row matches:
                logging.info('Creating station %d in pasd_stations' % stn.station_id)
                curs.execute('DELETE FROM pasd_stations WHERE (station_id = %s)', (stn.station_id,))
                curs.execute('INSERT INTO pasd_stations (station_id) VALUES (%s)', (stn.station_id,))

            curs.execute('SELECT COUNT(*) FROM pasd_fndh_state WHERE (station_id = %s)', (stn.station_id,))
            if curs.fetchone()[0] != 1:   # No rows match, or more than one row matches:
                logging.info('Creating FNDH state for station %d' % stn.station_id)
                curs.execute('DELETE FROM pasd_fndh_state WHERE (station_id = %s)', (stn.station_id,))
                curs.execute('INSERT INTO pasd_fndh_state (station_id) VALUES (%s)', (stn.station_id,))

            for pnum in range(1, 29):
                curs.execute('SELECT COUNT(*) FROM pasd_fndh_port_status WHERE (station_id = %s) AND (pdoc_number = %s)',
                             (stn.station_id, pnum))
                if curs.fetchone()[0] != 1:   # No rows match, or more than one row matches:
                    logging.info('Creating FNDH port state for station %d, port %d' % (stn.station_id, pnum))
                    curs.execute('DELETE FROM pasd_fndh_port_status WHERE (station_id = %s) AND (pdoc_number = %s)',
                                 (stn.station_id, pnum))
                    curs.execute('INSERT INTO pasd_fndh_port_status (station_id, pdoc_number) VALUES (%s, %s)',
                                 (stn.station_id, pnum))

            for sb_num in range(1, 25):
                curs.execute('SELECT COUNT(*) FROM pasd_smartbox_state WHERE (station_id = %s) AND (smartbox_number = %s)',
                             (stn.station_id, sb_num))
                if curs.fetchone()[0] != 1:   # No rows match, or more than one row matches:
                    logging.info('Creating Smartbox state for station %d, SB %d' % (stn.station_id, sb_num))
                    curs.execute('DELETE FROM pasd_smartbox_state WHERE (station_id = %s) AND (smartbox_number = %s)',
                                 (stn.station_id, sb_num))
                    curs.execute('INSERT INTO pasd_smartbox_state (station_id, smartbox_number) VALUES (%s, %s)',
                                 (stn.station_id, sb_num))

                for pnum in range(1, 13):
                    curs.execute('SELECT COUNT(*) FROM pasd_smartbox_port_status WHERE (station_id = %s) AND (smartbox_number = %s) AND (port_number = %s)',
                                 (stn.station_id, sb_num, pnum))
                    if curs.fetchone()[0] != 1:   # No rows match, or more than one row matches:
                        logging.info('Creating Smartbox port state for station %d, SB %d, port %d' % (stn.station_id, sb_num, pnum))
                        curs.execute('DELETE FROM pasd_smartbox_port_status WHERE (station_id = %s) AND (smartbox_number = %s) AND (port_number = %s)',
                                     (stn.station_id, sb_num, pnum))
                        curs.execute('INSERT INTO pasd_smartbox_port_status (station_id, smartbox_number, port_number) VALUES (%s, %s, %s)',
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
        tmpdict['station_id'] = stn.station_id
        if port.status_timestamp:
            tmpdict['status_datetime'] = datetime.datetime.fromtimestamp(port.status_timestamp, timezone.utc)
        else:
            tmpdict['status_datetime'] = None
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
            for pnum, port in sb.ports.items():
                port.station_id = stn.station_id
                tmpdict = port.__dict__.copy()
                if port.status_timestamp:
                    tmpdict['status_datetime'] = datetime.datetime.fromtimestamp(port.status_timestamp, timezone.utc)
                else:
                    tmpdict['status_datetime'] = None
                if port.current_timestamp:
                    tmpdict['current_datetime'] = datetime.datetime.fromtimestamp(port.current_timestamp, timezone.utc)
                else:
                    tmpdict['current_datetime'] = None
                sb_ports_data_list.append(tmpdict)
    else:    # If the station is not active (smartboxes are all off), fill in empty smartbox data
        for sb_num in range(1, 25):
            for portnum in range(1, 13):
                spdata = {'station_id':stn.station_id, 'modbus_address':sb_num, 'port_number':portnum,
                          'system_online':None, 'current':None, 'locally_forced_on':None,
                          'locally_forced_off':None, 'breaker_tripped':None,
                          'power_state':None, 'status_timestamp':datetime.datetime.now(timezone.utc),
                          'current_timestamp':None, 'status_datetime':None, 'current_datetime':None}
                sb_ports_data_list.append(spdata)

    with db:  # Commit transaction when block exits
        with db.cursor() as curs:
            psycopg2.extras.execute_batch(curs, SMARTBOX_STATE_QUERY, sb_data_list)
            psycopg2.extras.execute_batch(curs, SMARTBOX_PORT_QUERY, sb_ports_data_list)


def get_antenna_map(db, station_number=DEFAULT_STATION_NUMBER):
    """
    Query the database to find the antenna->smartbox/port mapping, and return it as a dict of dicts.

    The returned dict has smartbox address (1-24) as key. The values are dicts with port number (1-12) as key,
    and antenna number (1-256) as value (or None). All 288 possible smartbox ports must be in the antenna map.

    :param db: Database connection object
    :param station_number: Station ID (1-9999)
    :return: Antenna map (dict of dicts)
    """
    # Create antenna map structure with all 288 ports set to None, to make sure none are missing
    ant_map = {}
    for sid in range(1, station.MAX_SMARTBOX + 1):
        ant_map[sid] = {pid:None for pid in range(1, 13)}

    with db:   # Commit transaction when block exits
        with db.cursor() as curs:
            query = """SELECT antenna_number, smartbox_number, port_number
                       FROM pasd_antenna_portmap
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
                       FROM pasd_fndh_port_status
                       WHERE station_id=%s"""
            curs.execute(query, (station_number,))

            fndhpc = {i:[False, False] for i in range(1, 29)}
            for row in curs:
                pdoc_number, desire_enabled_online, desire_enabled_offline = row
                fndhpc[pdoc_number] = bool(desire_enabled_online), bool(desire_enabled_offline)

            # Read all smartbox port configs for this station:
            query = """SELECT smartbox_number, port_number, desire_enabled_online, desire_enabled_offline, reset_breaker
                       FROM pasd_smartbox_port_status
                       WHERE station_id=%s"""
            curs.execute(query, (station_number,))

            sbpc = {}
            for sid in range(1, 25):
                sbpc[sid] = {i:[False, False, False] for i in range(1, 13)}
            for row in curs:
                smartbox_number, port_number, desire_enabled_online, desire_enabled_offline, reset_breaker = row
                sbpc[smartbox_number][port_number] = (bool(desire_enabled_online),
                                                      bool(desire_enabled_offline),
                                                      bool(reset_breaker))

    return fndhpc, sbpc


def update_station_state(db, stn):
    """
    Write the current station state (stn.active, stn.status, etc) to the 'stations' table in the database.

    :param db:  Database connection object
    :param stn: An instance of station.Station()
    :return: The current value of the desired_active row in the stations table entry for this station.
    """
    query = "UPDATE pasd_stations SET active = %s, status = %s, status_timestamp = %s WHERE station_id = %s"
    with db:
        with db.cursor() as curs:
            curs.execute(query, (stn.active, stn.status, datetime.datetime.now(timezone.utc), stn.station_id))
            curs.execute("SELECT desired_active FROM pasd_stations WHERE station_id = %s", (stn.station_id,))
            rows = curs.fetchall()
            if len(rows) > 1:
                stn.logger.critical('Multiple records in stations table for station ID=%d' % (stn.station_id))
                sys.exit()
            else:
                desired_active = rows[0][0]

    return desired_active


def main_loop(db, stn):
    """
    Run forever in a loop
      -Query the field hardware to get all the current sensor and port parameters and update the instance data
      -Use the instance data to update the database sensor and port parameters
      -Query the database to look for commanded changes in station or port state
      -Write the commanded state data to the field hardware if it's different
      -Query the stations table to see if we're meant to start up, or shut down

    :param db: Database connection object
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
        fdict['pasd.fieldtest.fndh.psu48v_current'] = stn.fndh.psu48v_current
        fdict['pasd.fieldtest.fndh.psu48v1_temp'] = stn.fndh.psu48v1_temp
        fdict['pasd.fieldtest.fndh.psu48v2_temp'] = stn.fndh.psu48v2_temp
        fdict['pasd.fieldtest.fndh.panel_temp'] = stn.fndh.panel_temp
        fdict['pasd.fieldtest.fndh.fncb_temp'] = stn.fndh.fncb_temp
        fdict['pasd.fieldtest.fndh.fncb_humidity'] = stn.fndh.fncb_humidity
        for snum, stemp in stn.fndh.sensor_temps.items():
            fdict['pasd.fieldtest.fndh.sensor%02d.temp' % snum] = stemp
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
        send_carbon(data)

        # Use the instance data to update the database sensor and port parameters
        update_db(db, stn=stn)

        # Query the database to see if the desired port config is different to the polled port config
        fndhpc, sbpc = get_all_port_configs(db, station_number=stn.station_id)

        needs_write = False
        for pid in stn.fndh.ports.keys():
            p = stn.fndh.ports[pid]
            desire_enabled_online, desire_enabled_offline = fndhpc[pid]
            if (p.desire_enabled_online != desire_enabled_online):
                p.desire_enabled_online = desire_enabled_online
                needs_write = True
            if (p.desire_enabled_offline != desire_enabled_offline):
                p.desire_enabled_offline = desire_enabled_offline
                needs_write = True
        if needs_write:
            stn.fndh.write_portconfig()
            time.sleep(1.0)   # Allow time for a smartbox to boot, if it's being turned on here.

        for sid in stn.smartboxes.keys():
            needs_write = False
            for pid in stn.smartboxes[sid].ports.keys():
                p = stn.smartboxes[sid].ports[pid]
                desire_enabled_online, desire_enabled_offline, reset_breaker = sbpc[sid][pid]
                if (p.desire_enabled_online != desire_enabled_online):
                    p.desire_enabled_online = desire_enabled_online
                    needs_write = True
                if (p.desire_enabled_offline != desire_enabled_offline):
                    p.desire_enabled_offline = desire_enabled_offline
                    needs_write = True
            if needs_write:
                stn.smartboxes[sid].write_portconfig(write_breaker=True)

        desired_active = update_station_state(db, stn=stn)

        if ( (desired_active and
             (not stn.active) and
             ((time.time() - LAST_STARTUP_ATTEMPT_TIME) > STARTUP_RETRY_INTERVAL)) ):
            stn.startup()
        elif ( (not desired_active) and
               stn.active and
               ((time.time() - LAST_SHUTDOWN_ATTEMPT_TIME) > SHUTDOWN_RETRY_INTERVAL) ):
            stn.shutdown()

        time.sleep(max(0.0, 15 - (time.time() - last_loop_start_time)))


if __name__ == '__main__':
    CP = conparser(defaults={})
    CPfile = CP.read(CPPATH)
    if not CPfile:
        print("None of the specified configuration files found by mwaconfig.py: %s" % (CPPATH,))

    parser = argparse.ArgumentParser(description='Run a PaSD station',
                                     epilog='Run this as "python -i %s" to drop into the Python prompt after starting up.' % sys.argv[0])
    parser.add_argument('--host', dest='host', default=None,
                        help='Hostname of an ethernet-serial gateway, eg 10.128.30.1')
    parser.add_argument('--device', dest='device', default=None,
                        help='Serial port device name, eg /dev/ttyS0 or COM6')
    parser.add_argument('--id', '--station_id', dest='station_id', default=DEFAULT_STATION_NUMBER,
                        help='Station number (1-9999)')
    parser.add_argument('--debug', dest='debug', default=False, action='store_true',
                        help='If given, drop to the DEBUG log level, otherwise use INFO')
    args = parser.parse_args()

    if args.debug:
        loglevel = logging.DEBUG
    else:
        loglevel = logging.INFO

    config = CP['station_%03d' % args.station_id]
    dbuser = config['dbuser']
    dbhost = config['dbhost']
    dbpass = config['dbpass']
    dbname = config['dbname']

    if (args.host is None) and (args.device is None):
        args.host = config.get('fndh_host', DEFAULT_FNDH)

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

    while True:
        conn = transport.Connection(hostname=args.host, devicename=args.device, multidrop=False, logger=tlogger)

        fndhpc, sbpc = get_all_port_configs(db, station_number=args.station_id)

        slogger = logging.getLogger('ST')
        s = station.Station(conn=conn,
                            station_id=args.station_id,
                            do_full_startup=True,
                            antenna_map=get_antenna_map(db, args.station_id),
                            portconfig_fndh=fndhpc,
                            portconfig_smartboxes=sbpc,
                            logger=slogger)
        initialise_db(db=db, stn=s)

        print('Starting up entire station as "s" - FNDH on address 101, SMARTboxes on addresses 1-24.')
        s.full_startup()
        # s.poll_data()

        result = main_loop(db, s)
        if result is False:
            logging.error('Station unreachable, trying again in 10 seconds')
            time.sleep(10)
            continue
        else:
            break
