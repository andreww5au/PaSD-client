"""
Scaling functions that take PCB and modbus register version numbers, and convert raw
register values into real values.
"""


def scale_5v(raw_value, pcb_version):
    """
    Given a raw register value and the PCB version number, find out what scale and offset are needed, convert the raw
    value to a voltage.

    :param raw_value: raw register contents as a value from 0-65535
    :param pcb_version: integer PCB version number, 0-65535
    :return: output_value in Volts
    """
    return 10.0 * (raw_value / 4096.0)  # 0 to 10.0 V


def scale_48v(raw_value, pcb_version):
    """
    Given a raw register value and the PCB version number, find out what scale and offset are needed, convert the raw
    value to a voltage.

    :param raw_value: raw register contents as a value from 0-65535
    :param pcb_version: integer PCB version number, 0-65535
    :return: output_value in Volts
    """
    return 100.0 * (raw_value / 4096.0)  # 0 to 100.0 V


def scale_temp(raw_value, pcb_version):
    """
    Given a raw register value and the PCB version number, find out what scale and offset are needed, convert the raw
    value to deg C.

    :param raw_value: raw register contents as a value from 0-65535
    :param pcb_version: integer PCB version number, 0-65535
    :return: output_value in deg C
    """
    return 150.0 * (raw_value / 4096.0) - 10  # -10 to +90 deg C


def scale_current(raw_value, pcb_version):
    """
    Given a raw register value and the PCB version number, find out what scale and offset are needed, convert the raw
    value to mA.

    :param raw_value: raw register contents as a value from 0-65535
    :param pcb_version: integer PCB version number, 0-65535
    :return: output_value in mA
    """
    return 100.0 * (raw_value / 4096.0)  # 0 to 100 mA


def scale_48vcurrent(raw_value, pcb_version):
    """
        Given a raw register value and the PCB version number, find out what scale and offset are needed, convert the raw
        value to Amps.

        :param raw_value: raw register contents as a value from 0-65535
        :param pcb_version: integer PCB version number, 0-65535
        :return: output_value in Amps
        """
    return 50.0 * (raw_value / 4096.0)  # 0 to 50 A