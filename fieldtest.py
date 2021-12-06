#!/usr/bin/env python

"""
Temporary daemon to monitor the equipment being tested in the field. Test equipment is
missing firmware features, and doesn't have the final hardware setup as far as sensor wiring
and positioning are concerned.
"""

import logging
import pickle
import socket
import struct
import time
import traceback

LOGFILE = 'fieldtest.log'
HOSTNAME = 'pasd-fndh.mwa128t.org'
FNDH_ADDRESS = 31
SMARTBOX_ADDRESSES = [1, 2]

SBOXES = {}

loglevel = logging.DEBUG   # For console - logfile level is hardwired to DEBUG below

fh = logging.FileHandler(filename=LOGFILE, mode='w')
fh.setLevel(logging.DEBUG)   # All log messages go to the log file
sh = logging.StreamHandler()
sh.setLevel(loglevel)        # Some or all log messages go to the console

logging.basicConfig(handlers=[fh, sh],
                    level=logging.DEBUG,
                    format='%(levelname)s:%(name)s %(created)14.3f - %(message)s')


from pasd import fndh
from pasd import smartbox
from pasd import transport


def send_carbon(data):
    """
    Send a list of tuples to carbon_cache on the icinga VM
    :param data:  A list of (path, (timestamp, value)) objects, where path is like 'pasd.fieldtest.sb2.port7.current'
    :return: None
    """
    payload = pickle.dumps(data, protocol=2)  # dumps() returns a bytes object
    header = struct.pack("!L", len(payload))  # pack() returns a bytes object
    try:
        sock = socket.create_connection(('icinga.mwa128t.org', 2004))
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


if __name__ == '__main__':
    tlogger = logging.getLogger('T')
    conn = transport.Connection(hostname=HOSTNAME, port=5000, logger=tlogger)

    flogger = logging.getLogger('FNDH:%d' % FNDH_ADDRESS)
    f = fndh.FNDH(conn=conn, modbus_address=FNDH_ADDRESS, logger=flogger)
    print('Polling FNDH as "f" on address %d.' % FNDH_ADDRESS)
    f.poll_data()
    print('Configuring all-off on FNDH as "f" on address %d.' % FNDH_ADDRESS)
    f.configure_all_off()
    print('Final configuring FNDH as "f" on address %d.' % FNDH_ADDRESS)
    f.configure_final()
    f.poll_data()

    for sadd in SMARTBOX_ADDRESSES:
        slogger = logging.getLogger('SB:%d' % sadd)
        s = smartbox.SMARTbox(conn=conn, modbus_address=sadd, logger=slogger)
        print('Polling SMARTbox as "s" on address %d.' % sadd)
        s.poll_data()
        print('Configuring SMARTbox as "s" on address %d.' % sadd)
        s.configure()
        s.poll_data()
        SBOXES[sadd] = s

    while True:
        data = {}    # A list of (path, (timestamp, value)) objects, where path is like 'pasd.fieldtest.sb2.port7.current'
        f.poll_data()

        fdict = {}
        fdict['pasd.fndh.psu48v1_voltage'] = f.psu48v1_voltage
        fdict['pasd.fndh.psu48v2_voltage'] = f.psu48v2_voltage
        fdict['pasd.fndh.psu5v_voltage'] = f.psu5v_voltage
        fdict['pasd.fndh.psu48v_current'] = f.psu48v_current
        fdict['pasd.fndh.psu48v_temp'] = f.psu48v_temp
        fdict['pasd.fndh.psu5v_temp'] = f.psu5v_temp
        fdict['pasd.fndh.pcb_temp'] = f.pcb_temp
        fdict['pasd.fndh.outside_temp'] = f.outside_temp
        fdict['pasd.fndh.statuscode'] = f.statuscode
        fdict['pasd.fndh.indicator_code'] = f.indicator_code
        for pnum in range(1, 3):   # Only two pdocs for now
            p = f.ports[pnum]
            fdict['pasd.fndh.port%02d.power_state' % pnum] = int(p.power_state)
            fdict['pasd.fndh.port%02d.power_sense' % pnum] = int(p.power_sense)

        for sb in SBOXES.values():
            sb.poll_data()

        # TODO - populate this data list with telemetry from the hardware
        data = {}   # A list of (path, (timestamp, value)) objects, where path is like 'pasd.fieldtest.sb2.port7.current'

        send_carbon(data)

        time.sleep(10)

