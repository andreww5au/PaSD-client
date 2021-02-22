#!/usr/bin/env python

import fndh
import transport
import smartbox

SMARTBOX_ADDRESS_LIST = range(1, 25)   # List of all the modbus addresses for SMARTboxes in this station
FNDH_ADDRESS = 31   # Modbus address of the FNDH controller


class Station(object):
    def __init__(self, hostname, port):
        self.hostname = hostname
        self.port = port
        self.conn = transport.Connection(hostname=self.hostname, port=self.port)

        self.smartboxes = {}
        for sadd in SMARTBOX_ADDRESS_LIST:
            self.smartboxes[sadd] = smartbox.SMARTbox(conn=self.conn, modbus_address=sadd)
        self.fndh = fndh.FNDH(conn=self.conn, modbus_address=FNDH_ADDRESS)
