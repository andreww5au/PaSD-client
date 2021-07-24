# **PaSD SMARTbox and FNDH software for the local MCCS**

# Overview

Each of the stations in SKA-Low will consist of 256 antennae distributed in a circle roughly 40m in diameter. Each of the 256 antennae is connected via coaxial cable to a nearby SMARTbox, located on the ground screen between the antennae. The SMARTbox delivers DC power over the coaxial cable to an LNA in the antenna, and converts the incoming RF from the antenna into an optical RF signal on an outgoing fibre.

Each station will typically have 24 SMARTboxes in the field, and each SMARTbox has 12 antenna ports, making a total of 288 available inputs for antennae. Since there are only 256 antennae in a station, not all of the ports on each SMARTbox will necessarily be in use at any given time. The remainder are available as spares in case of faults.

Each SMARTbox has an internal low-speed, low-power microcontroller to monitor temperatures, currents and voltages, and to switch antennae on and off as required. Power comes from a single &#39;Field Node Distribution Hub (FNDH) for the entire station. A low-speed (9600 bps) low-RFI communications link to the SMARTbox microcontroller is carried over the 48VDC power line. Each SMARTbox also has an infra-red port for local control and diagnostics, either in the lab for testing, or for a technician to use in the field.

Each station has a Field Node Distribution Hub to provide power and communications for the SMARTboxes, and to act as a fibre aggregation point for the fibres carrying RF signals from the SMARTboxes to go back to the control building. The FNDH is powered from 240 VAC mains power, and has two 48VDC power supplies for the SMARTboxes, and a 5V power supply for the local microcontroller.

The FNDH has 28 possible slots in which a &#39;Power and Data over Coax&#39; (PDoC) card can be installed, each providing a port to which a SMARTbox can be connected. Again, not all of the slots will have PDoC cards installed at any given time, and not all PDoC cards will be connected to a SMARTbox. The extra ports are provided for redundancy.

A single fibre pair from the control building to the FNDH is connected to an ethernet-serial bridge (via a media converter), allowing the MCCS in the control building to send and receive data over the network to a given FNDH (with a unique IP address). The serial data from the ethernet-serial bridge is passed to the local microcontroller in the FNDH, and shared with all of the SMARTboxes via a multi-drop serial bus. When the MCCS sends data, every device on the shared bus (the FNDH microcontroller and all of the SMARTboxes in the station) receives it.

The microcontroller in the FNDH monitors temperatures, voltages and currents in the FNDH, and allows the 28 possible output ports to be switched on and off. It does _NOT_ communicate with the SMARTboxes at all. Instead, the SMARTboxes are controlled by the MCCS in the main building, talking to them directly via serial traffic over the shared serial bus.

Like the SMARTboxes, the FNDH has an infra-red port, to allow a technician to do diagnostics in the field.

# Communications API

## Link layer

As seen at the microcontroller in a SMARTbox or FNDH, the protocol is Modbus ASCII, at 9600 bps, (8 bit, no parity), handshaking TBD. For the prototype, the FNDH will have a media converter from fibre to 100baseT, and a commercial ethernet (100baseT) to serial bridge, which accepts a TCP connection to port 5000 from any client (or UDP packets to port 5000), and translates traffic on the serial port to/from the network. For the final version, the media converter and ethernet-serial bridge could be merged into a single custom-designed board.

The local MCCS simply opens a TCP connection to the given IP address (depending on the station number, set via DIP switches in the FNDH) and sends and receives bytes in the Modbus ASCII packet format.

The microcontroller in the FNDH forwards these packets directly to a multidrop serial bus, to which all of the SMARTboxes are connected as Modbus slave devices, each with a unique station address. The FNDH microcontroller also sits (logically, if not physically) on the same multidrop serial bus, and acts as a Modbus slave device with a fixed station address, allowing 48VDC power to the each of the 28 SMARTbox ports to be turned on and off.

## Low-level API

The protocol is Modbus ASCII. The only registers being used are in the &#39;holding register&#39; area, from 40001-49999. All are formally read/write according to the Modbus standard, but the microcontroller ignores writes to most of them. This allows a single multi-register write command, instead of several individual commands.

In this documentation, &#39;register numbers&#39; refer to the location inside the set of Modbus holding registers, so register &#39;5&#39; means 40005 in the full Modbus address space. Note that the &#39;Regnum&#39; field inside the Modbus packet is 1 less than this, so a packet with a value of &#39;4&#39; in the Regnum field would refer to register 40005, or &#39;register 5&#39; in this document.

All Modbus ASCII packets start with a &#39;:&#39; character (ASCII 58, or 0x3A), contain a number of bytes, each expressed in hex as two ASCII characters (0-9 or A-F), and end with Carriage-Return (&#39;\r&#39; or 0x0D) and Line-Feed (&#39;\n&#39; or 0x0A) characters. For example, a packet might be &quot;:01030000003BC1\r\n&quot;.

### Single or multi-register read (function 0x03):

To read one or more registers from the microcontroller, the MCCS would send a packet consisting of:

| Station\_id | 0x03 | Regnum(hi) | Regnum(lo) | Numreg(hi) | Numreg(lo) | LRC |
| --- | --- | --- | --- | --- | --- | --- |

(with a leading &#39;:&#39;, and a trailing CR/LF pair)

Sample code to calculate the LRC (checksum) for a message is included in the appendix.

For example, to read 8 (two-byte) registers, starting with register 11, from the SMARTbox with a station address of 1, the packet contents (between the &#39;:&#39; and the CR/LF pair) would be:

| 0x01 | 0x03 | 0x00 | 0x0A | 0x00 | 0x08 | 0xF4 |
| --- | --- | --- | --- | --- | --- | --- |

That packet would be &#39;:010300000008F4\r\n&#39;

_Note that the &#39;Regnum&#39; values in the packet are the actual register number minus 1, so we send decimal &#39;10&#39; in the packet (0x0A) to read register 11._

In reply, the microcontroller would send a packet containing its own station ID, a 0x03, the number of registers read (in 1 byte), the desired register contents (MSB first), and ending with a checksum LRC.

If there was an error, the microcontroller would reply with a packet that looks like:

| Station id | 0x83 | Exc\_code | LRC |
| --- | --- | --- | --- |

The 0x83 function code is the original function code of 0x03 for &#39;read register&#39;, plus 0x80 to indicate an exception. The &#39;Exc\_code&#39; values are documented elsewhere (eg [Modbus - Wikipedia](https://en.wikipedia.org/wiki/Modbus))

**Note – the Modbus packet size limit means that a maximum of 125 registers can be read with a single function 0x03 call.**

### Single register write (function 0x06):

To write one register to the microcontroller, the MCCS would send a packet that looks like:

| Station id | 0x06 | Regnum(hi) | Regnum(lo) | Data(hi) | Data(lo) | LRC |
| --- | --- | --- | --- | --- | --- | --- |

If there was no error, the microcontroller should reply with a packet identical to the one it received, with register number, data and LRC. If there was an error, it should reply with a 4-byte exception packet, with a function code of 0x86, and an appropriate exception code and LRC.

### Multi-register write (function 0x10):

To write multiple registers to the microcontroller at the same time, the MCCS would send a packet with the station ID, a function code of 0x10, the starting register number &#39;Rn&#39; (two bytes, MSB first), the number of registers to write &#39;NR&#39; (two bytes), the number of bytes of data in the packet &#39;NB&#39; (one byte) and a list of register contents &#39;D1&#39; and &#39;D2&#39; (two bytes per register, MSB first), then a one-byte packet LRC. For example, to write 0x1234 to register 23 and 0x5678 to register 24, on station 1:

| ID | Fn | Rn(h) | Rn(l) | NR(h) | NR(l) | NB | D1(h) | D1(l) | D2(h) | D2(l) | LRC |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0x01 | 0x10 | 0x00 | 0x16 | 0x00 | 0x02 | 0x04 | 0x12 | 0x34 | 0x56 | 0x78 | 0xBF |

(or &#39;:0110001600020412345678BF\r\n&#39;)

For multiple register writes (function 0x10), the microcontroller would respond with a packet that contains the starting register number, and the number of registers written, not the complete list of register values. In the above example, the reply packet would be:

| 0x01 | 0x10 | 0x00 | 0x16 | 0x00 | 0x02 | 0xD7 |
| --- | --- | --- | --- | --- | --- | --- |

(or &#39;:011000160002D7\r\n&#39;)

Errors resulting from a multi-register write would have a function code of 0x90, and the relevant exception code. **Note – the Modbus packet size limit means that a maximum of 125 registers can be written with a single function 0x10 call.**

## SMARTbox register map

SMARTboxes have a pair of digital rotary switches on the fixed (non field-replaceable) chassis to set the Modbus address, allowing a range from 00-00. Values from 1-24 will be used as Modbus addresses for the 24 physical SMARTboxes in a station, the rest of the range is reserved for use in development and maintenance/testing. The SMARTbox registers are divided into two blocks of contiguous addresses. The first block (starting at register 1) contains all of the values that need to be polled at regular intervals (mostly read-only registers). The second block (starting at register 1001) contains configuration data written by the MCCS after power-up, and does not need to be read after that.

### Polled registers:

The polled register block has 59 two-byte registers, starting at register 1. Two of these registers make up the CPU ID, two make the &#39;uptime&#39; value in seconds, and 8 make up the unique chip ID number (guaranteed to be different for every physical device). Of the 59 registers, 35 are &#39;system&#39; registers, and there an additional two 2-byte &#39;port registers&#39; for each of the 12 FEM ports in the SMARTbox.

| **#** | **Name** | **Size** | **Description** |
| --- | --- | --- | --- |
| 1 | SYS\_MBRV | 1 | Modbus register map revision number. RO. |
| 2 | SYS\_PCBREV | 1 | PCB Revision number. RO. |
| 3 | SYS\_CPUID | 2 | Microcontroller device ID (two registers, four bytes). RO. |
| 5 | SYS\_CHIPID | 8 | Chip unique device ID (8 registers, 16 bytes). RO. |
| 13 | SYS\_FIRMVER | 1 | Firmware revision number. RO. |
| 14 | SYS\_UPTIME | 2 | System uptime, in seconds (2 registers, four bytes). RO. |
| 16 | SYS\_ADDRESS | 1 | Modbus station address. RO. |
| 17 | SYS\_48V\_V | 1 | Incoming 48VDC voltage (Volts/100). RO. |
| 18 | SYS\_PSU\_V | 1 | PSU output voltage (Volts/100). RO. |
| 19 | SYS\_PSUTEMP | 1 | PSU temperature (deg C / 100). RO. |
| 20 | SYS\_PCBTEMP | 1 | PCB temperature (deg C / 100). RO. |
| 21 | SYS\_OUTTEMP | 1 | Outside temperature (deg C / 100). RO. |
| 22 | SYS\_STATUS | 1 | System status (see text). R/W. |
| 23 | SYS\_LIGHTS | 1 | LED status (see text). R/W. |
| 24 | SYS\_SENSE01 | 1 | Sensor 1 - usage TBD. RO. |
| 25 | SYS\_SENSE02 | 1 | Sensor 2 - usage TBD. RO. |
| 26 | SYS\_SENSE03 | 1 | Sensor 3 - usage TBD. RO. |
| 27 | SYS\_SENSE04 | 1 | Sensor 4 - usage TBD. RO. |
| 28 | SYS\_SENSE05 | 1 | Sensor 5 - usage TBD. RO. |
| 29 | SYS\_SENSE06 | 1 | Sensor 6 - usage TBD. RO. |
| 30 | SYS\_SENSE07 | 1 | Sensor 7 - usage TBD. RO. |
| 31 | SYS\_SENSE08 | 1 | Sensor 8 - usage TBD. RO. |
| 32 | SYS\_SENSE09 | 1 | Sensor 9 - usage TBD. RO. |
| 33 | SYS\_SENSE10 | 1 | Sensor 10 - usage TBD. RO. |
| 34 | SYS\_SENSE11 | 1 | Sensor 11 - usage TBD. RO. |
| 35 | SYS\_SENSE12 | 1 | Sensor 12 - usage TBD. RO. |

The SYS\_STATUS is one of the two status registers that are read/write. When read, it contains the current status code – 0=OK, 1=WARNING, 2=ALARM, 3=RECOVERY, 4=UNINITIALISED. The SMARTbox will boot into the UNINITIALISED state, and stay in that state until any value is written into the SYS\_STATUS register. That register write will result in a transition to one of the other states (OK if temperatures and currents are in-spec, WARNING, ALARM or RECOVERY if not). Two of the states (OK and WARNING) allow ports to be turned on, the rest result in the ports being forced off.

The microcontroller also keeps track of MCCS communications. If the microcontroller has received any serial data from the MCCS recently, it defines the system as &#39;online&#39; (for the purposes of the port state registers described below). If a significant time has elapsed since the last serial communications, the system is defined as &#39;offline&#39;.

The SYS\_LIGHTS register is also read/write. It controls the state of the two LEDs on the SMARTbox. The first (MSB) byte controls the state of the blue service indicator LED (0 is off, 255 is on). Intermediate values may control brightness, depending on the hardware. The second (LSB) byte controls the state of the tri-colour (red-yellow-green) status LED, including flash patterns. These are represented by codes (TBD) – for example, 0 might be off, 1 might represent flashing bright red for 0.2 seconds every 1 second, etc. The state of the tri-colour LED, and the value of that byte of the register, are controlled by the microcontroller, and writes to that byte of the register are ignored.

The hardware has an additional few (currently around 7) analogue inputs available for monitoring sensor readings. To allow room for expansion, 12 registers (and a matching set of 48 threshold registers) are allocated, as SYS_SENSE01 through SYS_SENSE12. Most of these will probably used to monitor temperatures at various points in the engineering prototypes.

The port registers are:

| # | **Name** | **Size** | **Description** |
| --- | --- | --- | --- |
| 36 | P01\_STATE | 1 | Port 1 state bitmap (see text). R/W. |
| 37 | P02\_STATE | 1 | Port 2 state bitmap (see text). R/W. |
| 38 | P03\_STATE | 1 | Port 3 state bitmap (see text). R/W. |
| 39 | P04\_STATE | 1 | Port 4 state bitmap (see text). R/W. |
| 40 | P05\_STATE | 1 | Port 5 state bitmap (see text). R/W. |
| 41 | P06\_STATE | 1 | Port 6 state bitmap (see text). R/W. |
| 42 | P07\_STATE | 1 | Port 7 state bitmap (see text). R/W. |
| 43 | P08\_STATE | 1 | Port 8 state bitmap (see text). R/W. |
| 44 | P09\_STATE | 1 | Port 9 state bitmap (see text). R/W. |
| 45 | P10\_STATE | 1 | Port 10 state bitmap (see text). R/W. |
| 46 | P11\_STATE | 1 | Port 11 state bitmap (see text). R/W. |
| 47 | P12\_STATE | 1 | Port 12 state bitmap (see text). R/W. |
| 48 | P01\_CURRENT | 1 | Port 1 current (1/100ths of a degree C, signed integer). RO. |
| 49 | P02\_CURRENT | 1 | Port 2 current (1/100ths of a degree C, signed integer). RO. |
| 50 | P03\_CURRENT | 1 | Port 3 current (1/100ths of a degree C, signed integer). RO. |
| 51 | P04\_CURRENT | 1 | Port 4 current (1/100ths of a degree C, signed integer). RO. |
| 52 | P05\_CURRENT | 1 | Port 5 current (1/100ths of a degree C, signed integer). RO. |
| 53 | P06\_CURRENT | 1 | Port 6 current (1/100ths of a degree C, signed integer). RO. |
| 54 | P07\_CURRENT | 1 | Port 7 current (1/100ths of a degree C, signed integer). RO. |
| 55 | P08\_CURRENT | 1 | Port 8 current (1/100ths of a degree C, signed integer). RO. |
| 56 | P09\_CURRENT | 1 | Port 9 current (1/100ths of a degree C, signed integer). RO. |
| 57 | P10\_CURRENT | 1 | Port 10 current (1/100ths of a degree C, signed integer). RO. |
| 58 | P11\_CURRENT | 1 | Port 11 current (1/100ths of a degree C, signed integer). RO. |
| 59 | P12\_CURRENT | 1 | Port 12 current (1/100ths of a degree C, signed integer). RO. |

Each of the 12 FEM ports has a state register (described below), which is Read/Write, and a current register containing reading for the current to that port, in a format TBD (read only).

The state register is a bitmap. The first (most significant) byte contains:

| **7** | 6 | 5 | 4 | 3 | 2 | 1 | 0 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ENABLE | ONLINE | DSON-H | DSON-L | DSOFF-H | DSOFF-L | TO-H | TO-L |

The second (least significant) byte contains:

| **7** | 6 | 5 | 4 | 3 | 2 | 1 | 0 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| BREAKER | POWER | - | - | - | - | - | - |

The fields are:

ENABLE: (read-only) Contains 1 if the system-wide health and settings allow this port to be active. All ports in a device will share the same ENABLE value.  It is included in every port&#39;s state register to simplify reading only a subset of ports in a single request.

ONLINE: (read-only) Contains a 1 if the system-wide state is &#39;online&#39;, meaning that it has heard from the MCCS recently. All ports in a device will share the same ONLINE value.  It is included in every port&#39;s state register to simplify reading only a subset of ports in a single request.

DSON-H and DSON-L: (read/write). These define a two-bit field that defines whether this port should be turned ON or OFF when the overall system state is &#39;online (the ONLINE bit field is 1). If this field is 10, then this port should be kept OFF when the system is online. If this field is 11, then this port should be turned ON when the system is online. If this field is 00 (the default on powerup), then the desired state is unknown, and is interpreted by the microcontroller as meaning the port should stay turned off. If a 00 is written to this field, then the current value of the desired state bits in the microcontroller is left unchanged.

DSOFF-H and DSOFF-L: (read/write). As for DSON-H and DSON-L, only this field defines whether the port should be turned on when the overall system state is &#39;offline.

TO-H and TO-L: (read/write). These define a two-bit field that defines whether this port should be forced to turn ON or OFF, overriding the DSON and DSOFF fields. The MCCS should never set this field, it should only be used by a technician in the field. Writing a 10 to this field forces the port to turn OFF, writing a 11 to this field forces the port to turn ON, and writing a 01 to this field turns off the override, so the DSON and DSOFF field values are used to determine the power state. Writing 00 to this field leaves the current field contents in the microcontroller unchanged.

BREAKER: (read/write). Contains a 1 if the over-current sense circuit breaker for this port has tripped. Writing a 1 to this field will reset the breaker if it has tripped. Resetting the trip without clearing the fault condition which caused it, may provide thermal stress on the device itself and the components it is attempting to power.  It is recommended that a few seconds minimum is allowed to pass before a retry and only two or three attempts are made before a proper investigation is made into the cause.

POWER: (read-only). Indicates whether the power is turned on for this port. This field represents the current state of this port&#39;s output &#39;enable&#39; from the device&#39;s processor to the power drive circuitry. It is unlikely but possible that device hardware failures or a simple cabling issue, may lead to the physical port being in a different powered state. It is also possible that the FEM or LNAs have failed or are not connected. Use this field plus the value of the CCR &#39;current reading register&#39; to check for nominal operation. For this value to be &#39;On&#39;, the device health must be &#39;OK&#39; or &#39;Warning&#39;, and the port circuit breaker must not be in the &#39;tripped&#39; state.

### Configuration Registers

The configuration register block, starting at register 1001 (all read/write), contains threshold values in ADU used by the microcontroller to act on the values of each of the analogue inputs. Most of the system-wide analogue inputs have four thresholds, each stored in a 2-byte register:

- ALARM-high (AH): If the new reading is above this value, then the state transitions to (or stays in) ALARM. If the current state is ALARM, and the new reading is _below_ this value, but still above WARNING-high, then transition to the RECOVERY state.
- WARNING-high (WH): If the current state is OK or WARNING, and the new reading is above this value (but still below ALARM-high), then the state transitions to (or stays in) WARNING. If the current state is ALARM, and the new reading is above this value and below ALARM-high, then transition to RECOVERY. From any state, if any reading is below this value (but still above WARNING-low), then transition to OK.

- WARNING-low (WL): If the current state is OK or WARNING, and the new reading is below this value (but still above ALARM-low), then the state transitions to (or stays in) WARNING. If the current state is ALARM, and the new reading is below this value and above ALARM-low, then transition to RECOVERY. From any state, if any reading is above this value (but still below WARNING-high), then transition to OK.
- ALARM-low (AL): If the new reading is below this value, then the state transitions to (or stays in) ALARM. If the current state is ALARM, and the new reading is _above_ this value, but still below WARNING-low, then transition to the RECOVERY state.

| 1001 | SYS\_48V\_V\_TH | 4 | Incoming 48VDC voltage (Volts/100). AH, WH, WL, AL. |
| --- | --- | --- | --- |
| 1005 | SYS\_PSU\_V\_TH | 4 | PSU output voltage (Volts/100). AH, WH, WL, AL. |
| 1009 | SYS\_PSUTEMP\_TH | 4 | PSU temperature (deg C / 100). AH, WH, WL, AL. |
| 1013 | SYS\_PCBTEMP\_TH | 4 | PCB temperature (deg C / 100). AH, WH, WL, AL. |
| 1017 | SYS\_OUTTEMP\_TH | 4 | Outside temperature (deg C / 100). AH, WH, WL, AL. |
| 1021 | SYS\_SENSE01\_TH | 4 | Sensor 1 - usage TBD. AH, WH, WL, AL. |
| 1025 | SYS\_SENSE02\_TH | 4 | Sensor 2 - usage TBD. AH, WH, WL, AL. |
| 1029 | SYS\_SENSE03\_TH | 4 | Sensor 3 - usage TBD. AH, WH, WL, AL. |
| 1033 | SYS\_SENSE04\_TH | 4 | Sensor 4 - usage TBD. AH, WH, WL, AL. |
| 1037 | SYS\_SENSE05\_TH | 4 | Sensor 5 - usage TBD. AH, WH, WL, AL. |
| 1041 | SYS\_SENSE06\_TH | 4 | Sensor 6 - usage TBD. AH, WH, WL, AL. |
| 1045 | SYS\_SENSE07\_TH | 4 | Sensor 7 - usage TBD. AH, WH, WL, AL. |
| 1049 | SYS\_SENSE08\_TH | 4 | Sensor 8 - usage TBD. AH, WH, WL, AL. |
| 1053 | SYS\_SENSE09\_TH | 4 | Sensor 9 - usage TBD. AH, WH, WL, AL. |
| 1057 | SYS\_SENSE10\_TH | 4 | Sensor 10 - usage TBD. AH, WH, WL, AL. |
| 1061 | SYS\_SENSE11\_TH | 4 | Sensor 11 - usage TBD. AH, WH, WL, AL. |
| 1065 | SYS\_SENSE12\_TH | 4 | Sensor 12 - usage TBD. AH, WH, WL, AL. |
| 1069 | P01\_CURRENT\_TH | 1 | Port 01 current trip threshold (format TBD). |
| 1070 | P02\_CURRENT\_TH | 1 | Port 02 current trip threshold (format TBD). |
| 1071 | P03\_CURRENT\_TH | 1 | Port 03 current trip threshold (format TBD). |
| 1072 | P04\_CURRENT\_TH | 1 | Port 04 current trip threshold (format TBD). |
| 1073 | P05\_CURRENT\_TH | 1 | Port 05 current trip threshold (format TBD). |
| 1074 | P06\_CURRENT\_TH | 1 | Port 06 current trip threshold (format TBD). |
| 1075 | P07\_CURRENT\_TH | 1 | Port 07 current trip threshold (format TBD). |
| 1076 | P08\_CURRENT\_TH | 1 | Port 08 current trip threshold (format TBD). |
| 1077 | P09\_CURRENT\_TH | 1 | Port 09 current trip threshold (format TBD). |
| 1078 | P10\_CURRENT\_TH | 1 | Port 10 current trip threshold (format TBD). |
| 1079 | P11\_CURRENT\_TH | 1 | Port 11 current trip threshold (format TBD). |
| 1080 | P12\_CURRENT\_TH | 1 | Port 12 current trip threshold (format TBD). |

The P\&lt;NN\&gt;\_CURRENT\_TH are the thresholds at which the microcontroller will turn off an FEM because the current is too high. The values represent the difference between two voltage readings.

## FNDH Register map

The FNDH always has a Modbus address of 31, and an IP address (for the ethernet-serial bridge) set by rotary DIP switches defining the station number. The FNDH registers are divided into two blocks of contiguous addresses. The first block (starting at register 1) contains all of the values that need to be polled at regular intervals (mostly read-only registers). The second block (starting at register 1001) contains configuration data written by the MCCS after power-up, and does not need to be read after that.

### Polled registers:

The polled register block has 54 two-byte registers, starting at register 1. Two of these registers make up the CPU ID, two make up the &#39;uptime&#39; value in seconds, and 8 make up the unique chip ID number (guaranteed to be different for every physical device). Of these 54 registers, 26 are &#39;system&#39; registers, and there is an additional 2-byte &#39;port state register&#39; for each of the 28 possible output PDoC ports in the FNDH.

| **#** | **Name** | **Size** | **Description** |
| --- | --- | --- | --- |
| 1 | SYS\_MBRV | 1 | Modbus register map revision number. RO. |
| 2 | SYS\_PCBREV | 1 | PCB Revision number. RO. |
| 3 | SYS\_CPUID | 2 | Microcontroller device ID (two registers, four bytes). RO. |
| 5 | SYS\_CHIPID | 8 | Chip unique device ID (8 registers, 16 bytes). RO. |
| 13 | SYS\_FIRMVER | 1 | Firmware revision number. RO. |
| 14 | SYS\_UPTIME | 2 | System uptime, in seconds (2 registers, four bytes). RO. |
| 16 | SYS\_ADDRESS | 1 | Modbus station address. RO. |
| 17 | SYS\_48V1\_V | 1 | 48VDC PSU 1 output voltage (Volts/100). RO. |
| 18 | SYS\_48V2\_V | 1 | 48VDC PSU 2 output voltage (Volts/100). RO. |
| 19 | SYS\_5V\_V | 1 | 5VDC PSU output voltage (Volts/100). RO. |
| 20 | SYS\_48V\_I | 1 | Total 48VDC output current (Volts/100). RO. |
| 21 | SYS\_48V\_TEMP | 1 | 48VDC PSU 1+2 temperature (deg C / 100). RO. |
| 22 | SYS\_5V\_TEMP | 1 | 5VDC PSU temperature (deg C / 100). RO. |
| 23 | SYS\_PCBTEMP | 1 | PCB temperature (deg C / 100). RO. |
| 24 | SYS\_OUTTEMP | 1 | Outside temperature (deg C / 100). RO. |
| 25 | SYS\_STATUS | 1 | System status (see text). R/W. |
| 26 | SYS\_LIGHTS | 1 | LED status (see text). R/W. |

The SYS\_STATUS is one of the two status registers that are read/write. When read, it contains the current status code – 0=OK, 1=WARNING, 2=ALARM, 3=RECOVERY, 4=UNINITIALISED. The FNDH will boot into the UNINITIALISED state, and stay in that state until any value is written into the SYS\_STATUS register. That register write will result in a transition to one of the other states (OK if temperatures and currents are in-spec, WARNING, ALARM or RECOVERY if not). Two of the states (OK and WARNING) allow ports to be turned on, the rest result in the outputs being forced off.

The microcontroller also keeps track of MCCS communications. If the microcontroller has received any serial data from the MCCS recently, it defines the system as &#39;online&#39; (for the purposes of the port state registers described below). If a significant time has elapsed since the last serial communications, the system is defined as &#39;offline&#39;.

The SYS\_LIGHTS register is also read/write. It controls the state of the two LEDs on the FNDH. The first (MSB) byte controls the state of the blue service indicator LED (0 is off, 255 is on). Intermediate values may control brightness, depending on the hardware. The second (LSB) byte controls the state of the tri-colour (red-yellow-green) status LED, including flash patterns. These are represented by codes (TBD) – for example, 0 might be off, 1 might represent flashing bright red for 0.2 seconds every 1 second, etc.The state of the tri-colour LED, and the value of that byte of the register, are controlled by the microcontroller, and writes to that byte of the register are ignored.

The port registers are:

| # | **Name** | **Size** | **Description** |
| --- | --- | --- | --- |
| 27 | P01\_STATE | 1 | Port 1 state bitmap (see text). R/W. |
| 28 | P02\_STATE | 1 | Port 2 state bitmap (see text). R/W. |
| 29 | P03\_STATE | 1 | Port 3 state bitmap (see text). R/W. |
| 30 | P04\_STATE | 1 | Port 4 state bitmap (see text). R/W. |
| 31 | P05\_STATE | 1 | Port 5 state bitmap (see text). R/W. |
| 32 | P06\_STATE | 1 | Port 6 state bitmap (see text). R/W. |
| 33 | P07\_STATE | 1 | Port 7 state bitmap (see text). R/W. |
| 34 | P08\_STATE | 1 | Port 8 state bitmap (see text). R/W. |
| 35 | P09\_STATE | 1 | Port 9 state bitmap (see text). R/W. |
| 36 | P10\_STATE | 1 | Port 10 state bitmap (see text). R/W. |
| 37 | P11\_STATE | 1 | Port 11 state bitmap (see text). R/W. |
| 38 | P12\_STATE | 1 | Port 12 state bitmap (see text). R/W. |
| 39 | P13\_STATE | 1 | Port 13 state bitmap (see text). R/W. |
| 40 | P14\_STATE | 1 | Port 14 state bitmap (see text). R/W. |
| 41 | P15\_STATE | 1 | Port 15 state bitmap (see text). R/W. |
| 42 | P16\_STATE | 1 | Port 16 state bitmap (see text). R/W. |
| 43 | P17\_STATE | 1 | Port 17 state bitmap (see text). R/W. |
| 44 | P18\_STATE | 1 | Port 18 state bitmap (see text). R/W. |
| 45 | P19\_STATE | 1 | Port 19 state bitmap (see text). R/W. |
| 46 | P20\_STATE | 1 | Port 20 state bitmap (see text). R/W. |
| 47 | P21\_STATE | 1 | Port 21 state bitmap (see text). R/W. |
| 48 | P22\_STATE | 1 | Port 22 state bitmap (see text). R/W. |
| 49 | P23\_STATE | 1 | Port 23 state bitmap (see text). R/W. |
| 50 | P24\_STATE | 1 | Port 24 state bitmap (see text). R/W. |
| 51 | P25\_STATE | 1 | Port 25 state bitmap (see text). R/W. |
| 52 | P26\_STATE | 1 | Port 26 state bitmap (see text). R/W. |
| 53 | P27\_STATE | 1 | Port 27 state bitmap (see text). R/W. |
| 54 | P28\_STATE | 1 | Port 28 state bitmap (see text). R/W. |

Each of the 12 PDoC ports has a state register (described below), which is Read/Write.

The state register is a bitmap. The first (most significant) byte contains:

| **7** | 6 | 5 | 4 | 3 | 2 | 1 | 0 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ENABLE | ONLINE | DSON-H | DSON-L | DSOFF-H | DSOFF-L | TO-H | TO-L |

The second (least significant) byte contains:

| **7** | 6 | 5 | 4 | 3 | 2 | 1 | 0 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| PWRSENSE | POWER | - | - | - | - | - | - |

The fields are:

ENABLE: (read-only) Contains 1 if the system-wide health and settings allow this port to be active. All ports in a device will share the same ENABLE value.  It is included in every port&#39;s state register to simplify reading only a subset of ports in a single request.

ONLINE: (read-only) Contains a 1 if the system-wide state is &#39;online&#39;, meaning that it has heard from the MCCS recently. All ports in a device will share the same ONLINE value.  It is included in every port&#39;s state register to simplify reading only a subset of ports in a single request.

DSON-H and DSON-L: (read/write). These define a two-bit field that defines whether this port should be turned ON or OFF when the overall system state is &#39;online (the ONLINE bit field is 1). If this field is 10, then this port should be kept OFF when the system is online. If this field is 11, then this port should be turned ON when the system is online. If this field is 00 (the default on powerup), then the desired state is unknown, and is interpreted by the microcontroller as meaning the port should stay turned off. If a 00 is written to this field, then the current value of the desired state bits in the microcontroller is left unchanged.

DSOFF-H and DSOFF-L: (read/write). As for DSON-H and DSON-L, only this field defines whether the port should be turned on when the overall system state is &#39;offline.

TO-H and TO-L: (read/write). These define a two-bit field that defines whether this port should be forced to turn ON or OFF, overriding the DSON and DSOFF fields. The MCCS should never set this field, it should only be used by a technician in the field. Writing a 10 to this field forces the port to turn OFF, writing a 11 to this field forces the port to turn ON, and writing a 01 to this field turns off the override, so the DSON and DSOFF field values are used to determine the power state. Writing 00 to this field leaves the current field contents in the microcontroller unchanged.

PWRSENSE: (read/write). Contains a 1 if there is an active 48V supply on the output to that port. It will be 0 if the port is turned off (POWER=0), or if the under/over current circuit has tripped, disabling 48V for that port. If the current limit has tripped, the port must be turned off and on again using the &#39;desired\_state\_xxxxxxx&#39; bits in the state register. Resetting the trip without clearing the fault condition which caused it, may provide thermal stress on the device itself and the components it is attempting to power.  It is recommended that a few seconds minimum is allowed to pass before a retry and only two or three attempts are made before a proper investigation is made into the cause.

POWER: (read-only). Indicates whether the power is turned on for this port. This field represents the current state of this port&#39;s output &#39;enable&#39; from the device&#39;s processor to the power drive circuitry. It is possible that current limiting logic or a part failure may still mean that the port is not powered (PWRSENSE=0). Use this field plus the value of the PWRSENSE field to check for nominal operation. For this field to be &#39;On&#39;, the device health must be &#39;OK&#39; or &#39;Warning&#39;, and the port circuit breaker must not be in the &#39;tripped&#39; state.

### Configuration Registers

The configuration register block, starting at register 1001 (all read/write), contains threshold values in ADU used by the microcontroller to act on the values of each of the analogue inputs. Each system-wide analogue input has four thresholds, each stored in a 2-byte register:

- ALARM-high (AH): If the new reading is above this value, then the state transitions to (or stays in) ALARM. If the current state is ALARM, and the new reading is _below_ this value, but still above WARNING-high, then transition to the RECOVERY state.
- WARNING-high (WH): If the current state is OK or WARNING, and the new reading is above this value (but still below ALARM-high), then the state transitions to (or stays in) WARNING. If the current state is ALARM, and the new reading is above this value and below ALARM-high, then transition to RECOVERY. From any state, if any reading is below this value (but still above WARNING-low), then transition to OK.

- WARNING-low (WL): If the current state is OK or WARNING, and the new reading is below this value (but still above ALARM-low), then the state transitions to (or stays in) WARNING. If the current state is ALARM, and the new reading is below this value and above ALARM-low, then transition to RECOVERY. From any state, if any reading is above this value (but still below WARNING-high), then transition to OK.
- ALARM-low (AL): If the new reading is below this value, then the state transitions to (or stays in) ALARM. If the current state is ALARM, and the new reading is _above_ this value, but still below WARNING-low, then transition to the RECOVERY state.

|  #  | Name | Size | Description |
| --- | --- | --- | --- |
| 1001 | SYS\_48V1\_V\_TH | 4 | 48VDC PSU 1 output voltage. AH, WH, WL, AL. |
| 1005 | SYS\_48V2\_V\_TH | 4 | 48VDC PSU 2 output voltage. AH, WH, WL, AL. |
| 1009 | SYS\_5V\_V\_TH | 4 | 5V DC PSU output voltage. AH, WH, WL, AL. |
| 1013 | SYS\_48V\_I\_TH | 4 | Total 48V current. AH, WH, WL, AL. |
| 1017 | SYS\_48V\_TEMP\_TH | 4 | Joint 48V power supply temperature. AH, WH, WL, AL. |
| 1021 | SYS\_5V\_TEMP\_TH | 4 | 5V power supply temperature. AH, WH, WL, AL. |
| 1025 | SYS\_PCBTEMP\_TH | 4 | PCB temperature. AH, WH, WL, AL. |
| 1029 | SYS\_OUTTEMP\_TH | 4 | Outside air temperature. AH, WH, WL, AL. |

## FNDH start-up – SMARTbox to PDoC mapping

On FNDH start-up, the PDoC ports will all be turned off. The MCCS will turn them on, one by one, at approximately 10 second intervals. It will then loop over all possibly SMARTbox addresses and read the &#39;uptime&#39; counter register from that address, and (if it gets a reply) use that value to work out which PDoC port that SMARTbox is connected to. That process must be repeated after any SMARTboxes are added to a station, or moved to a different PDoC port.

# Technician&#39;s &#39;Service Interface Device&#39;

Normally, the MCCS acts as the Modbus &#39;Master&#39; device, initiating communications with the SMARTboxes and the FNDH. During servicing, another device can act as a Modbus &#39;master&#39; - a technician&#39;s &#39;Service Interface Device&#39; (SID). This device allows a technician in the field at a given station to talk directly the SMARTboxes within that station, to the FNDH controller for that station, and to the MCCS (which can also act as a Modbus &#39;slave&#39;). Allowing the SID to act as a Modbus master does open up the possibility of conflict on the shared serial bus, however, since the MCCS will only spend a few seconds polling data from a station every minute or two (listening as a Modbus slave device for the rest of the time), the chance of any conflict should be minimal.

A technician uses a SID by approaching a SMARTbox or FNDH and using the short-range infra-red serial (IrDA) link to that device. While the FNDH and all SMARTboxes in a station share the same multi-drop Modbus serial bus, a SID connected to a SMARTbox or FNDH via IrDA can only communicate with that device itself, the FNDH microcontroller, or the MCCS via the serial-ethernet bridge in the FNDH. It will not be able to communicate with any other SMARTbox in that station.

A technician would use a SID to read and write registers in a SMARTbox to:

- Read and display currents, temperatures, system health, etc.
- Trigger a transition to the &#39;online&#39; and &#39;OK&#39; state by writing configuration data to the local microcontroller, even if the MCCS is offline or not polling that SMARTbox. Note that this will require the SID to have a valid set of configuration data for SMARTboxes, or safe default threshold and configuration data in the device firmware.
- Force FEM outputs on or off using the &#39;technicians override&#39; bits in the port state bitmap.

A technician would use a SID to read and write registers in the FNDH to:

- Read and display currents, temperatures, system health, etc.
- Force a transition to the &#39;online&#39; and &#39;OK&#39; state by writing configuration data to the controller, even if the MCCS is offline, or not polling that FNDH. Note that this will require the SID to have a valid set of configuration data for an FNDH, or safe default threshold and configuration data in the device firmware.
- Force PDoC outputs on or off using the &#39;technicians override&#39; bits in the port state bitmap.

A technician would use a SID to read and write registers in the MCCS to:

- Read and display the mapping from antenna cable number (1-256) to a SMARTbox address and port number inside that SMARTbox. For example, reading two bytes (13, 7) from register 42 might mean that physical antenna 42 is connected to port 7 on SMARTbox 13.
- Change the mapping from antenna cable number (1-256) to a SMARTbox address and port number inside that SMARTbox. The MCCS would discard any register write packet that would leave the mapping in an inconsistent state (multiple physical antennae connected to the same SMARTbox and port), and send a Modbus exception back to the SID.
- Read and display the mapping from physical PDoC port number to SMARTbox address in the FNDH.
- Read and display the service log entries for a given physical antenna, a SMARTbox or FNDH (using the machine-readable device serial number), or for the entire station.
- Append entries to the service log for a given physical antenna, a single SMARTbox/FNDH, or for the station.

# MCCS registers

When the MCCS is acting as a slave, it listens on Modbus address 63, and presents a set of virtual registers to be read and written by a technician&#39;s Service Interface Device (SID). These are:

## Physical antenna mapping:

Registers 1 through 256 inclusive contain the SMARTbox address (first/MSB) and port number inside that SMARTbox (second/LSB). A value of (0, 0) indicates that the given physical antenna is not connected to any input. The SID can write to one register, or many registers with a single packet, but any write packet will be rejected with an exception code if it would leave the mapping in an inconsistent state, by having the same SMARTbox and port number for two different physical antennae. Any number of physical antennae can be left in the &#39;disconnected&#39; state (0,0).

## Reading service log entries:

This takes place with one packet write (to set the physical antenna number, SMARTbox or FNDH id, and log entry number desired), and one or more packet reads (each reading 125 registers, containing a null-terminated string of up to 250 characters). The first 125-register read returns the requested log entry (where 0 is the most recent), and successive reads return subsequent (older) log entries.

## Writing service log entries:

This takes place with one multi-register write packet, containing the physical antenna number, SMARTbox or FNDH id, and a 125-register log entry containing a null-terminated string of up to 250 characters.

Service log registers:

| **#** | **# of reg** | **Name** | **Description** |
| --- | --- | --- | --- |
| 1001 | 1 | ANTNUM | Physical antenna number, or 0 if not used. |
| 1002 | 8 | CHIPID | Unique chip ID (16 bytes), or all zeros if not used. |
| 1010 | 1 | LOGNUM | Starting log entry to read (most recent first), or zero. |
| 1011 | 125 | MESSAGE | 250 byte null-terminated string containing a log entry. |

To read log entries, send a single multi-register (function 0x10) packet writing to registers 1001-1010. If ANTNUM is non-zero, filter only log messages referring to that physical antenna. If CHIPID is non-zero, filter only log messages referring to that physical device. If both are zero, filter only station-wide log messages (???should this be messages referring to any device in this station, or messages referring to the entire station and not a single device???). If both ANTNUM and CHIPID are non-zero, return an exception code.

The LOGNUM register in the write packet should be zero to start reading at the most recent log entry, or an integer to start at an older log entry.

After that register write packet, the SID sends register read request (function 0x03) for registers 1011-1126, to read a 250-byte null-terminated string. Subsequent reads from the same register range will return successive (older) log entries.

To write entries, send a single multi-register write (function 0x10) packet, setting one or neither of ANTNUM and CHIPID (as appropriate), and setting LOGNUM to zero, with registers 1011-1126 containing the log message to write.

## Reading SMARTbox address to PDoC port number mapping

There are 28 read-only registers (1201-1228), one for each of the PDoC ports, each containing either zero (if no SMARTbox is connected to that port), or a SMARTbox address (1-30) if there is one connected. This mapping is set on FNDH start-up, when the MCCS first configures an FNDH microcontroller, by powering up each of the 28 PDoC ports at 10-second intervals.

# Interface Library

The PaSD interface library is a set of Python libraries that communicates with the microcontrollers in SMARTboxes and FNDH&#39;s. In its current state, it&#39;s being used as a set of prototyping tools to configure and monitor prototypes in the lab, and later will be used for field testing. It could also form the core of the future PaSD local MCCS system, and is being written with this end-goal in mind.

The software is available here:

[https://github.com/andreww5au/PaSD-client](https://github.com/andreww5au/PaSD-client)

The contents are:

PaSD-client:

&nbsp;&nbsp;&nbsp; docs: Autogenerated function/class documentation – start with index.html

&nbsp;&nbsp;&nbsp; pasd: Code to monitor and control PaSD hardware:

&nbsp;&nbsp;&nbsp; &nbsp;&nbsp;&nbsp; transport.py – low-level Modbus-ASCII code.

&nbsp;&nbsp;&nbsp; &nbsp;&nbsp;&nbsp; smartbox.py – class to control a SMARTbox.

&nbsp;&nbsp;&nbsp; &nbsp;&nbsp;&nbsp; fndh.py – class to control an FNDH.

&nbsp;&nbsp;&nbsp; &nbsp;&nbsp;&nbsp; station.py – class to control an entire station (an FNDH and multiple SMARTboxes). Also acts as a Modbus &#39;slave&#39; to act on commands from a Technician&#39;s SID.

&nbsp;&nbsp;&nbsp; &nbsp;&nbsp;&nbsp; conversion.py – helper functions to convert sensor data between the values in the Modbus packets and real physical values.

&nbsp;&nbsp;&nbsp; &nbsp;&nbsp;&nbsp; \*.json – default configuration data to send to the hardware on startup.

&nbsp;&nbsp;&nbsp; simulate: Code to simulate real hardware, for testing:

&nbsp;&nbsp;&nbsp; &nbsp;&nbsp;&nbsp; sim\_smartbox.py – Simulates a single SMARTbox.

&nbsp;&nbsp;&nbsp; &nbsp;&nbsp;&nbsp; sim\_fndh.py – Simulates an FNDH.

&nbsp;&nbsp;&nbsp; &nbsp;&nbsp;&nbsp; sim\_station – Simulates an entire SKALOW station (one FNDH and 24 SMARTboxes).

&nbsp;&nbsp;&nbsp; sid: Code that acts as a Technician&#39;s Service Interface Device (SID):

&nbsp;&nbsp;&nbsp; &nbsp;&nbsp;&nbsp; mccs.py – allows the user to communicate with the MCCS (pasd/station.py) using the SID API described above.

&nbsp;&nbsp;&nbsp; communicate.py – wrapper script to start up and monitor a SMARTbox, FNDH, or a whole station.

&nbsp;&nbsp;&nbsp; simulate.py – wrapper script to start simulating a SMARTbox, FNDH, or a whole station.

# Appendix

## LRC code example:

<pre>
def getlrc(message=None):
    """
    Calculate and returns the LRC byte required for 'message' (a list of bytes).

   :param message: A list of bytes, each in the range 0-255
   :return: A list of one integer, in the range 0-255
    """
    if not message:
        return 0
    lrc = (0 - sum(message)) &amp; 0xFF _# Twos-complement of the sum of the message bytes, masked to 8 bits_
    return [lrc,]
</pre>
