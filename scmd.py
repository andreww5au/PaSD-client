#!/usr/bin/env python3

"""
PaSD command tool - given an action on the command line

"""

from configparser import ConfigParser as conparser
import getpass
import logging
import sys
import time

import click

import psycopg2

STATION_ID = 1
MAX_SMARTBOX = 2

CPPATH = ['/usr/local/etc/pasd.conf', '/usr/local/etc/pasd-local.conf',
          './pasd.conf', './pasd-local.conf']

DB = None   # Will be replaced by a psycopg2 database connection object on startup


def init():
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

    :param valuelist: Tuple of numbers
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


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument('action', nargs=1)
@click.argument('portnums', nargs=-1)
def pdoc(portnums, action):
    """
    Turn PDoC ports on or off - eg "scmd pdoc off 3 4 5"

    :param portnums:
    :param action:
    :return:
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
            print(query % (newstate, newstate, STATION_ID, portlist))


@cli.command(context_settings={"ignore_unknown_options": True})
@click.argument('sbnum', nargs=1)
@click.argument('action', nargs=1)
@click.argument('portnums', nargs=-1)
def fem(portnums, sbnum, action):
    """
    Turn PDoC ports on or off - eg "scmd pdoc off 3 4 5"

    :param portnums:
    :param sbnum:
    :param action:
    :return:
    """
    portlist = parse_values(valuelist=portnums, all_list=list(range(1, 13)))
    if not portlist:
        print('No matching ports, exiting.')
        return -1

    if (not sbnum.isdigit()) and (sbnum.upper() != 'ALL'):
        print("Second argument must be a smartbox number (1-24), or 'all', not '%s'" % sbnum)
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
            print(query % (newstate, newstate, STATION_ID, sboxes, portlist))


if __name__ == '__main__':
    init()
    cli()

