#!/usr/bin/env python

"""
EMC test a single PaSD station - control and monitor the hardware via Modbus commands to the specified IP
address, and optionally toggle either PDoC ports on the FNDH, or FEM ports on the smartboxes.

On startup, it will turn on all 28 PDoC ports, with a 5-second delay between each port. It will then try to
talk to smartboxes on address 1 through MAX_SMARTBOX, and for each one that responds, it will initialise that
smartbox, and use the time since powerup on that box to determine which PDoC port it is connected to.

It will then loop, polling the FNDH and each smartbox every CYCLE_TIME seconds.  If --togglepdocs or --togglefems
are given, it will cycle every odd-numbered PDoC (1,3,5,...27) every CYCLE_TIME seconds, or every
odd-numbered FEM port (1,2,5,7,9,11) on every connected smartbox, every CYCLE_TIME seconds.

Note that any smartboxes turned off, if --togglepdocs is passed, will be re-initialised, and their FEMs turned
back on, each time the PDoC port is turned back on.
"""

import argparse
import logging
import sys
import time

CYCLE_TIME = 10   # Loop cycle time for polling and toggling ports
MAX_SMARTBOX = 4  # Don't try to communicate with any smartbox addresses higher than this value.


def main_loop(stn, togglepdocs=False, togglefems=False):
    """
    Run forever in a loop
      -Query the field hardware to get all the current sensor and port parameters and update the instance data
      -Use the instance data to update the database sensor and port parameters

    :param stn: An instance of station.Station()
    :param togglepdocs: If True, turn some ports on and off to generate RFI
    :param togglefems: If True, turn some ports on and off to generate RFI
    :return: False if there was a communications error, None if an exit was requested by setting stn.wants_exit True
    """
    poweron = True
    while not stn.wants_exit:
        last_loop_start_time = time.time()

        if togglefems:
            for sid in stn.smartboxes.keys():
                logging.info('Turning %s ports 1,3,5,7,9,11 on smartbox %d' % ({False:'Off', True:'On'}[poweron], sid))
                for pid in stn.smartboxes[sid].ports.keys():
                    p = stn.smartboxes[sid].ports[pid]
                    if divmod(pid, 2)[1] == 1:   # Every odd numbered port
                        p.desire_enabled_online = poweron
                        p.desire_enabled_offline = poweron

                stn.smartboxes[sid].write_portconfig(write_breaker=True)

        if togglepdocs:
            logging.info('Turning %s ports 1,3, ... ,25,27 on FNDH' % ({False: 'Off', True: 'On'}[poweron],))
            for pid in range(1, 29, 2):
                p = stn.fndh.ports[pid]
                p.desire_enabled_online = poweron
                p.desire_enabled_offline = poweron
            stn.fndh.write_portconfig()

        poweron = not poweron

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

        time.sleep(max(0.0, CYCLE_TIME - (time.time() - last_loop_start_time)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='EMC test a PaSD station',
                                     epilog='Defaults to normal station startup, then regular polling of SB and FNDH data')
    parser.add_argument('--host', dest='host', default='10.128.30.1',
                        help='Hostname of an ethernet-serial gateway, eg 134.7.50.185')
    parser.add_argument('--debug', dest='debug', default=False, action='store_true',
                        help='If given, drop to the DEBUG log level, otherwise use INFO')
    parser.add_argument('--togglepdocs', dest='togglepdocs', default=False, action='store_true',
                        help='If given, toggle every odd numbered PDoC port in the FNDH on and off every 15 seconds.')
    parser.add_argument('--togglefems', dest='togglefems', default=False, action='store_true',
                        help='If given, toggle every odd numbered FEM on every smartbox on and off every 15 seconds.')
    args = parser.parse_args()

    if args.debug:
        loglevel = logging.DEBUG
    else:
        loglevel = logging.INFO

    sh = logging.StreamHandler()
    sh.setLevel(loglevel)  # Some or all log messages go to the console

    logging.basicConfig(handlers=[sh],
                        level=logging.DEBUG,
                        format='%(levelname)s:%(name)s %(created)14.3f - %(message)s')

    from pasd import transport
    from pasd import station

    station.MAX_SMARTBOX = MAX_SMARTBOX

    tlogger = logging.getLogger('T')
    if loglevel == logging.DEBUG:
        print('Setting transport log level to info, DEBUG is very spammy. All other logging is at DEBUG level.')
        tlogger.setLevel(logging.INFO)

    if args.togglepdocs and args.togglefems:
        logging.error("Can't specify both '--togglepdocs' and '--togglefems', only one at  a time.")
        sys.exit(-1)

    while True:
        conn = transport.Connection(hostname=args.host, multidrop=False, logger=tlogger)

        slogger = logging.getLogger('ST')
        s = station.Station(conn=conn,
                            antenna_map={},
                            station_id=1,
                            do_full_startup=False,
                            logger=slogger)

        print('Starting up entire station as "s" - FNDH on address 101, SMARTboxes on addresses 1-24.')
        s.full_startup()
        print('We have these smartboxes: %s' % s.smartboxes.keys())
        s.poll_data()

        result = main_loop(s, togglepdocs=args.togglepdocs, togglefems=args.togglefems)
        if result is False:
            logging.error('Station unreachable, trying again in 10 seconds')
            time.sleep(10)
            continue
        else:
            break
