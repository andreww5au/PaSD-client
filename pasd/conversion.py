"""
Scaling functions that take PCB and modbus register version numbers, and convert raw
register values into real values.
"""


def scale_5v(value, reverse=False, pcb_version=0):
    """
    Given a raw register value and the PCB version number, find out what scale and offset are needed, convert the raw
    value to a voltage (if reverse=False), or convert a value in Volts to raw (if reverse=True).

    For now, raw values are hundredths of a volt, positive only.

    :param value: raw register contents as a value from 0-65535, or a voltage in Volts
    :param reverse: Boolean, True to perform physical->raw conversion instead of raw->physical
    :param pcb_version: integer PCB version number, 0-65535
    :return: output_value in Volts
    """
    if reverse:
        return int(value * 100) & 0xFFFF
    else:
        return value / 100.0


def scale_48v(value, reverse=False, pcb_version=0):
    """
    Given a raw register value and the PCB version number, find out what scale and offset are needed, convert the raw
    value to a voltage (if reverse=False), or convert a value in Volts to raw (if reverse=True).

    For now, raw values are hundredths of a volt, positive only.

    :param value: raw register contents as a value from 0-65535, or a voltage in Volts
    :param reverse: Boolean, True to perform physical->raw conversion instead of raw->physical
    :param pcb_version: integer PCB version number, 0-65535
    :return: output_value in Volts
    """
    if reverse:
        return int(value * 100) & 0xFFFF
    else:
        return value / 100.0


def scale_temp(value, reverse=False, pcb_version=0):
    """
    Given a raw register value and the PCB version number, find out what scale and offset are needed, convert the raw
    value to deg C (if reverse=False), or convert a value in deg C to raw (if reverse=True).

    For now, raw values are hundredths of a deg C, as a signed 16-bit integer value

    :param value: raw register contents as a value from 0-65535, or a floating point temperature in degrees
    :param reverse: Boolean, True to perform physical->raw conversion instead of raw->physical
    :param pcb_version: integer PCB version number, 0-65535
    :return: value in deg C (if reverse=False), or raw value as an unsigned 16 bit integer
    """
    if reverse:
        if value < 0:
            return (int(value * 100) + 65536) & 0xFFFF
        else:
            return int(value * 100) & 0xFFFF
    else:
        if value >= 32768:
            value -= 65536
        return value / 100.0     # raw_value is a signed 16-bit integer containing temp in 1/100th of a degree


def scale_humidity(value, reverse=False, pcb_version=0):
    """
    Given a raw register value and the PCB version number, find out what scale and offset are needed, convert the raw
    value to percent humidity.

    This returns the value unchanged, as an integer reading in percent humidity

    :param value: raw register contents as a value from 0-65535
    :param reverse: Boolean, True to perform physical->raw conversion instead of raw->physical
    :param pcb_version: integer PCB version number, 0-65535
    :return: output_value in humidity (unless reverse=True)
    """
    return value


def scale_FEMcurrent(value, reverse=False, pcb_version=0):
    """
    Given a raw register value and the PCB version number, find out what scale and offset are needed, convert the raw
    value to mA.

    This returns the value unchanged, as an integer reading in mA

    :param value: raw register contents as a value from 0-65535, or crude estimate of the current in Amps
    :param reverse: Boolean, True to perform physical->raw conversion instead of raw->physical
    :param pcb_version: integer PCB version number, 0-65535
    :return: output_value in mA
    """
    return value


def scale_48vcurrent(value, reverse=False, pcb_version=0):
    """
    Given a raw register value and the PCB version number, find out what scale and offset are needed, convert the raw
    value to Amps (if reverse=False), or convert a value in Amps to raw (if reverse=True).

    For now, raw values are hundredths of an Amp, positive only.

    :param value: raw register contents as a value from 0-65535, or current in Amps
    :param reverse: Boolean, True to perform physical->raw conversion instead of raw->physical
    :param pcb_version: integer PCB version number, 0-65535
    :return: output_value in Amps
    """
    if reverse:
        return int(value * 100) & 0xFFFF
    else:
        return value / 100.0
