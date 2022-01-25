#!/usr/bin/env python3

"""
PaSD command tool to turn ports on/off on an FNDH or smartbox, by updating the relevant tables in the
database. The station_lmc.py code that runs continuously, communicating with the FNDH and smartboxes, then
issues the actual commands to the hardware.

The PaSD command tool can also be used to read current FNDH/smartbox/port status data from the database.
"""

from configparser import ConfigParser as conparser
import time

import click

import psycopg2

STATION_ID = 1
MAX_SMARTBOX = 2

CPPATH = ['/usr/local/etc/pasd.conf', '/usr/local/etc/pasd-local.conf',
          './pasd.conf', './pasd-local.conf']

FNDH_STRING = """\
FNDH at %(station_id)s, last contacted %1.1f seconds ago:
    Uptime: %(uptime)s seconds
    48V Out 1: %(psu48v1_voltage)s V
    48V Out 2: %(psu48v2_voltage)s V
    5V out: %(psu5v_voltage)s V
    48V Current: %(psu48v_current)s A 
    48V Temp: %(psu48v_temp)s deg C
    5V Temp: %(psu5v_temp)s deg C
    PCB Temp: %(pcb_temp)s deg C
    Outside Temp: %(outside_temp)s deg C
    Status: %(status)s
    Indicator: %(indicator_state)s
"""

PDOC_STRING = ""

DB = None   # Will be replaced by a psycopg2 database connection object on startup


def init():
    """
    Create the PostgreSQL database connection, and store it in the 'DB' global.

    :return: None
    """
    global DB
    CP = conparser(defaults={})
    CPfile = CP.read(CPPATH)
    if not CPfile:
        print("None of the specified configuration files found by mwaconfig.py: %s" % (CPPATH,))

    config = CP['station_%03d' % STATION_ID]
    dbuser = config['dbuser']
    dbhost = config['dbhost']
    dbpass = config['dbpass']
    dbname = config['dbname']
    DB = psycopg2.connect(user=dbuser, password=dbpass, host=dbhost, database=dbname)


def parse_values(valuelist, all_list=None):
    """
    Take a tuple of strings from the command line, each of which could be an integer, or 'all',
    and expand that into a list of values. If the value (or 'all') is preceded by a minus sign, it or
    they are excluded from the final list.

    The word 'all' is expanded into the list of values provided in the all_list parameter.

    :param valuelist: Tuple of strings, optionally preceded by a '-', each either representing a single port number, or the word 'all'
    :param all_list: List of values that should be taken to mean 'all' - eg [1,2,3,4,5,6,7,8,9,10,11,12]
    :return: List of values to act on, eg [1,3,5]
    """
    includevalues = []
    excludevalues = []

    for value in valuelist:
        subflag = False
        valuespec = value
        if value.startswith('-'):
            subflag = True
            valuespec = value[1:]

        if valuespec == 'all':
            thesevalues = all_list
        elif valuespec.isdigit():
            thesevalues = [int(valuespec)]
        else:
            thesevalues = []

        if subflag:
            excludevalues += thesevalues
        else:
            includevalues += thesevalues

    ovalues = [x for x in includevalues if x not in excludevalues]
    ovalues.sort()
    return ovalues


@click.group()
def cli():
    pass


@cli.command('fndh',
             short_help="Command or query the FNDH or a PDoC port",
             context_settings={"ignore_unknown_options": True})
@click.argument('action', nargs=1)
@click.argument('portnums', nargs=-1)
def fndh(portnums, action):
    """
    Turn PDoC ports on or off on the FNDH

    ACTION is what to do - one of 'on', 'off', or 'status'

    PORTNUMS is One or more items, each a port number or the word 'all'. Items are optionally preceded by a '-' to exclude them

    \b
    E.g.
    $ scmd fndh off 3 4 5         # turns off ports 3,4 and 5
    $ scmd fndh on all -3 -5      # turns on all ports EXCEPT 3 and 5
    $ scmd fndh status            # displays the FNDH status
    $ scmd fndh status 1 2 3      # displays the status of ports 1, 2 and 3
    """
    portlist = parse_values(valuelist=portnums, all_list=list(range(1, 29)))

    with DB:
        with DB.cursor() as curs:
            if action.upper() == 'STATUS':
                if not portlist:
                    query = """SELECT uptime, readtime, psu48v1_voltage, psu48v2_voltage, psu5v_voltage, psu48v_current, 
                                      psu48v_temp, psu5v_temp, pcb_temp, outside_temp, status, indicator_state
                               FROM pasd_fndh_state
                               WHERE station_id = %s"""
                    curs.execute(query, (STATION_ID,))
                    rows = curs.fetchall()
                    if rows:
                        (uptime, readtime, psu48v1_voltage, psu48v2_voltage, psu5v_voltage, psu48v_current, psu48v_temp,
                         psu5v_temp, pcb_temp, outside_temp, status, indicator_state) = rows[0]
                        paramdict = {'station_id':STATION_ID,
                                     'uptime':uptime,
                                     'age':time.time() - readtime,
                                     'psu48v1_voltage':psu48v1_voltage,
                                     'psu48v2_voltage':psu48v2_voltage,
                                     'psu5v_voltage':psu5v_voltage,
                                     'psu48v_current':psu48v_current,
                                     'psu48v_temp':psu48v_temp,
                                     'psu5v_temp':psu5v_temp,
                                     'pcb_temp':pcb_temp,
                                     'outside_temp':outside_temp,
                                     'status':status,
                                     'indicator_state':indicator_state}
                        print(FNDH_STRING % paramdict)
                else:  # portlist suppled
                    query = """SELECT pdoc_number, status_timestamp, system_online, locally_forced_on, locally_forced_off, 
                                      power_state, power_sense, desire_enabled_online, desire_enabled_offline
                               FROM pasd_fndh_port_status
                               WHERE (station_id = %(station_id)s) AND (pdoc_number = ANY(%(port_number)s))
                               ORDER BY pdoc_number"""
                    curs.execute(query, {'station_id':STATION_ID, 'port_number':portlist})
                    rows = curs.fetchall()
                    for row in rows:
                        (pdoc_number, status_timestamp, system_online, locally_forced_on, locally_forced_off, power_state,
                         power_sense, desire_enabled_online, desire_enabled_offline) = row
                        if locally_forced_on:
                            lfstring = 'Forced:ON'
                        elif locally_forced_off:
                            lfstring = 'Forced:OFF'
                        else:
                            lfstring = 'NotForced'
                        enstring = '(DesireEnabled:%s)' % ','.join([{False:'', True:'Online', None:'?'}[desire_enabled_online],
                                                                    {False:'', True:'Offline', None:'?'}[desire_enabled_offline]])
                        sysstring = '(System:%s)' % ({False:'Offline', True:'Online', None:'??line?'}[system_online])
                        status_items = ['Status(%1.1f s):' % (time.time() - status_timestamp),
                                        {False:'Power:OFF', True:'Power:ON', None:'Power:?'}[power_state],
                                        sysstring,
                                        enstring,
                                        lfstring,
                                        {False:'PowerSense:OFF', True:'PowerSense:ON', None:'PowerSense:?'}[power_sense]
                                        ]
                        status_string = ' '.join(status_items)
                        print("P%02d: %s" % (pdoc_number, status_string))

            elif action.upper() in ['ON', 'OFF']:
                if not portlist:
                    print('No matching ports, exiting.')
                    return -1

                newstate = action.upper() == 'ON'
                query = """UPDATE pasd_fndh_port_status 
                           SET desire_enabled_online = %s,
                               desire_enabled_offline = %s
                           WHERE station_id = %s AND pdoc_number = ANY(%s)"""
                curs.execute(query, (newstate, newstate, STATION_ID, portlist))

            else:
                print('Action must be "on" or "off", not "%s"' % action)
                return -1


@cli.command('sb',
             short_help="Command or query a smartbox or an FEM port",
             context_settings={"ignore_unknown_options": True})
@click.argument('sbnum', nargs=1)
@click.argument('action', nargs=1)
@click.argument('portnums', nargs=-1)
def sb(portnums, action, sbnum):
    """
    Turn FEM ports on or off on the given smartbox

    SBNUM is a single smartbox address (eg '1'), or 'all' to command all smartboxes

    ACTION is what to do - one of 'on', 'off', or 'status'

    PORTNUMS is one or more items, each a port number or the word 'all'. Items are optionally preceded by a '-' to exclude them

    \b
    E.g.
    $ scmd sb 1 off 3 4 5        # turns off ports 3,4 and 5
    $ scmd sb 2 on all -3 -5     # turns on all ports EXCEPT 3 and 5
    $ scmd sb 1 status           # displays the status smartbox 1
    $ scmd sb 2 status 1 2 3     # displays the status of ports 1, 2 and 3 on smartbox 1
    """
    portlist = parse_values(valuelist=portnums, all_list=list(range(1, 13)))
    if not portlist:
        print('No matching ports, exiting.')
        return -1

    if (not sbnum.isdigit()) and (sbnum.upper() != 'ALL'):
        print("Second argument must be a single smartbox number (1-24), or 'all', not '%s'" % sbnum)
        return -1

    if sbnum.upper() == 'ALL':
        sboxes = list(range(1, MAX_SMARTBOX + 1))
    else:
        sboxes = [int(sbnum)]

    with DB:
        if action.upper() == 'ON':
            newstate = True
        elif action.upper() == 'OFF':
            newstate = False
        else:
            print('Action must be "on" or "off", not "%s"' % action)
            return -1

        with DB.cursor() as curs:
            query = """UPDATE pasd_smartbox_port_status 
                       SET desire_enabled_online = %s,
                           desire_enabled_offline = %s
                       WHERE station_id = %s AND 
                             smartbox_number = ANY(%s) AND
                             port_number = ANY(%s)"""
            curs.execute(query, (newstate, newstate, STATION_ID, sboxes, portlist))


if __name__ == '__main__':
    init()
    cli()

