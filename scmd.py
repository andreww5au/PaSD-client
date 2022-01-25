#!/usr/bin/env python3

"""
PaSD command tool to turn ports on/off on an FNDH or smartbox, by updating the relevant tables in the
database. The station_lmc.py code that runs continuously, communicating with the FNDH and smartboxes, then
issues the actual commands to the hardware.

The PaSD command tool can also be used to read current FNDH/smartbox/port status data from the database.
"""

from configparser import ConfigParser as conparser

import click

import psycopg2

STATION_ID = 1
MAX_SMARTBOX = 2

CPPATH = ['/usr/local/etc/pasd.conf', '/usr/local/etc/pasd-local.conf',
          './pasd.conf', './pasd-local.conf']

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
    if not portlist:
        print('No matching ports, exiting.')
        return -1

    with DB:
        if action.upper() == 'ON':
            newstate = True
        elif action.upper() == 'OFF':
            newstate = False
        else:
            print('Action must be "on" or "off", not "%s"' % action)
            return -1

        with DB.cursor() as curs:
            query = """UPDATE pasd_fndh_port_status 
                       SET desire_enabled_online = %s,
                           desire_enabled_offline = %s
                       WHERE station_id = %s AND pdoc_number = ANY(%s)"""
            curs.execute(query, (newstate, newstate, STATION_ID, portlist))


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

