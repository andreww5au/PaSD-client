"""
Code to handle power and signal distribution for an SKA-Low station.

Files are:

transport.py - low level Modbus-RTU serial API, abstracted into a Connection class.

conversion.py - functions to convert from raw ADU values to scaled temperatures, voltages, currents, etc.

smartbox.py - handles a single SMARTbox, one of ~24 in a station, abstracted into a SMARTbox class.

fndh.py - handles the Field Node Distribution Hub for a station, providing 48V power and comms to the SMARTboxes.
          Abstracted into an FNDH class.

station.py - handles an entire SKA-Low station, with one FNDH and up to 28 SMARTboxes. Abstracted into a Station class.

"""