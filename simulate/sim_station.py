#!/usr/bin/env python

"""
Simulates a full PaSD station, including an FNDH and 24 SMARTboxes. Used for testing MCCS code.
"""

import logging
import threading

logging.basicConfig()

from simulate import sim_smartbox
from simulate import sim_fndh


class Sim_Station(sim_fndh.SimFNDH):
    def __init__(self, conn=None, modbus_address=None, logger=None):
        sim_fndh.SimFNDH.__init__(self, conn=conn, modbus_address=modbus_address, logger=logger)
        self.smartboxes = {}
        self.threads = {}
        for port in self.ports.values():
            port.old_power_state = False   # Used to detect PDoC port state changes

    def loophook(self):
        if self.wants_exit:   # Propagate this to all of the simulated smartboxes, so their threads end too
            for smb in self.smartboxes.values():
                smb.wants_exit = True
        for portnum, port in self.ports.items():
            if port.power_state != port.old_power_state:
                if port.power_state and portnum < 25:   # Only fire up 24 simulated smartboxes
                    self.smartboxes[portnum] = sim_smartbox.SimSMARTbox(conn=self.conn,
                                                                        modbus_address=portnum,
                                                                        logger=logging.getLogger('SB:%d' % portnum))
                    self.threads[portnum] = threading.Thread(target=self.smartboxes[portnum].sim_loop,
                                                             daemon=False,
                                                             name='SB:%d.thread' % portnum)
                    self.threads[portnum].start()
                    self.logger.info('Started a new comms thread for smartbox %d' % portnum)
                else:
                    if portnum in self.smartboxes:
                        self.smartboxes[portnum].wants_exit = True   # Signal the comms thread on that SMARTbox to exit
                        del self.smartboxes[portnum]
                        self.logger.info('Killed the comms thread for smartbox %d' % portnum)
                port.old_power_state = port.power_state


"""
Use as 'simulate.py station', or:

from pasd import transport
from simulate import sim_station
conn = transport.Connection(hostname='134.7.50.185')  # address of ethernet-serial bridge
# or
conn = transport.Connection(devicename='/dev/ttyS0')  # or 'COM5' for example, under Windows

s = sim_station.Sim_Station(conn=conn, modbus_address=101)
s.sim_loop()
"""
