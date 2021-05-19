#!/usr/bin/env python

"""
Simulates a full PaSD station, including an FNDH and 24 SMARTboxes. Used for testing MCCS code.
"""

import logging
import threading
import time

logging.basicConfig()
logger = logging.getLogger()
logger.level = logging.DEBUG

import sim_smartbox
import sim_fndh
from pasd import transport


class Sim_FNDH(sim_fndh.SimFNDH):
    def __init__(self, conn=None, modbus_address=None):
        sim_fndh.SimFNDH.__init__(self, conn=conn, modbus_address=modbus_address)
        self.conn = conn
        self.smartboxes = {}
        self.threads = {}
        for port in self.ports.values():
            port.old_power_state = False   # Used to detect PDoC port state changes

    def loophook(self):
        for portnum, port in self.ports.items():
            if port.power_state != port.old_power_state:
                if port.power_state:
                    self.smartboxes[portnum] = sim_smartbox.SimSMARTbox(conn=self.conn, modbus_address=portnum)
                    self.threads[portnum] = threading.Thread(target=self.smartboxes[portnum].mainloop)
                    self.threads[portnum].start()
                else:
                    self.smartboxes[portnum].wants_exit = True   # Signal the comms thread on that SMARTbox to exit
                    del self.smartboxes[portnum]
                port.old_power_state = port.power_state


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Simulate an entire PASD station, listen forever for packets')
    parser.add_argument('--host', dest='host', default=None,
                        help='Hostname of an ethernet-serial gateway, eg 134.7.50.185')
    parser.add_argument('--device', dest='device', default=None,
                        help='Serial port device name, eg /dev/ttyS0 or COM6')
    args = parser.parse_args()
    if (args.host is None) and (args.device is None):
        args.host = '134.7.50.185'
    conn = transport.Connection(hostname=args.host, devicename=args.device, multidrop=True)

    s = Sim_FNDH(conn=conn, modbus_address=31)
    s.mainloop()
