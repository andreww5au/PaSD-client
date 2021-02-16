"""
Scaling functions that take PCB and modbus register version numbers, and convert raw
register values into real values, and units.
"""


def scale_5v(raw_value, pcb_version):
    """
    Given a raw register value and the PCB version number, find out what scale and offset are needed, convert the raw
    value to a voltage, and return a tuple of (output_value, 'Volts')

    :param raw_value: raw register contents as a value from 0-65535
    :param pcb_version: integer PCB version number, 0-65535
    :return: A tuple of (output_value, 'Volts')
    """
    return (10.0 * (raw_value / 4096.0), 'Volts')  # 0 to 10.0 V


def scale_48v(raw_value, pcb_version):
    """
    Given a raw register value and the PCB version number, find out what scale and offset are needed, convert the raw
    value to a voltage, and return a tuple of (output_value, 'Volts')

    :param raw_value: raw register contents as a value from 0-65535
    :param pcb_version: integer PCB version number, 0-65535
    :return: A tuple of (output_value, 'Volts')
    """
    return (100.0 * (raw_value / 4096.0), 'Volts')  # 0 to 100.0 V


def scale_temp(raw_value, pcb_version):
    """
    Given a raw register value and the PCB version number, find out what scale and offset are needed, convert the raw
    value to deg C, and return a tuple of (output_value, 'Deg C')

    :param raw_value: raw register contents as a value from 0-65535
    :param pcb_version: integer PCB version number, 0-65535
    :return: A tuple of (output_value, 'Deg C')
    """
    return (150.0 * (raw_value / 4096.0) - 10, 'deg C')  # -10 to +90 deg C


def scale_current(raw_value, pcb_version):
    """
    Given a raw register value and the PCB version number, find out what scale and offset are needed, convert the raw
    value to mA, and return a tuple of (output_value, 'mA')

    :param raw_value: raw register contents as a value from 0-65535
    :param pcb_version: integer PCB version number, 0-65535
    :return: A tuple of (output_value, 'mA')
    """
    return (100.0 * (raw_value / 4096.0), 'mA')  # 0 to 100 mA

