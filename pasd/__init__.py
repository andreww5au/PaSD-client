"""
Base module, including Modbus transport library, and code used by the MCCS in the control room

The contents are:

        transport.py - low-level Modbus-ASCII code.

        smartbox.py - class to control a SMARTbox.

        fndh.py - class to control an FNDH.

        station.py - class to control an entire station (an FNDH and multiple SMARTboxes). Also acts as a Modbus 'slave' to act on commands from a Technician's SID.

        conversion.py - helper functions to convert sensor data between the values in the Modbus packets and real physical values.

        \*.json - default configuration data to send to the hardware on startup.

"""