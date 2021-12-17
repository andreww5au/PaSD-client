
/* These mapping tables exist to allow antennae to be moved between ports on a single SMARTbox,
   or between SMARTboxes, to allow for redundancy in the case of hardware failures. This connectivity
   is reflected in the antenna_portmap table.

   Any antenna move like this will need to be accompanied by a matching fibre swap to the actual TPM
   inputs in the control building, at a different time, and probably by a different technician. This
   connectivity is reflected in the fibre_portmap table.

   Both tables have 'begintime' and 'endtime' columns, so they store the current state of the
   telescope ("... WHERE endtime > now() ..."), and the state at all previous times ("... WHERE
   %reftime > begintime AND %reftime < endtime ..."). When technician changes a cable, the 'endtime'
   timestamp for the current row is set to the current date, and a new row is created, with 'begintime'
   equal to the current date, and 'endtime' set to some arbitary far-future date (eg sys.maxint).

   Note that the antenna number is within the station, so always 1-256. Similarly, the 'TPM input
   number' is 1-256, so that it can easily be compared to the antenna number to make sure the connectivity
   is consistent at both ends (SMARTbox and TPM). Some other redirection will need to handle the mapping
   between 'station fibre number' and rack/TPM/port number.

   Note also that the station ID and smartbox address define which 12-fibre ribbon the data arrives
   on at the TPM, and the port number defines which fibre inside that ribbon it uses. These values are
   called 'smartbox_number' and 'port_number' in both tables, for consistency.
 */

-- Physical antenna to Smartbox/port mapping, in the field
CREATE TABLE pasd_antenna_portmap (
    station_id integer,                  -- Station ID
    antenna_number integer PRIMARY KEY,  -- Antenna number within station - 1-256
    smartbox_number integer,             -- Modbus address (1-24) of the SMARTbox in that station
    port_number integer,                 -- Port number (1-12) of the FEM port in that SMARTbox
    begintime timestamp with time zone,  -- Time at which this connection was established
    endtime timestamp with time zone,    -- Time at which this connection was undone
    comment text                         -- Technician's notes at connection time
);

CREATE INDEX pasd_antenna_portmap_port on pasd_antenna_portmap (station_id, smartbox_number, port_number);
CREATE INDEX pasd_antenna_portmap_begintime on pasd_antenna_portmap (begintime);
CREATE INDEX pasd_antenna_portmap_endtime on pasd_antenna_portmap (endtime);


-- Ribbon and fibre number to TPM input number mapping, in the control building
CREATE TABLE pasd_fibre_portmap (
    station_id integer,                   -- Station ID
    tpm_input_number integer PRIMARY KEY, -- TPM input number within station - 1-256
    smartbox_number integer,              -- Equal to the fibre ribbon number (1-24) for the SMARTbox in that station
    port_number integer,                  -- Equal to the fibre number (1-12) for the RFoF signal from that SMARTbox
    begintime timestamp with time zone,   -- Time at which this connection was established
    endtime timestamp with time zone,     -- Time at which this connection was undone
    comment text                          -- Technician's notes at connection time
);

CREATE INDEX pasd_fibre_portmap_port on pasd_fibre_portmap (station_id, smartbox_number, port_number);
CREATE INDEX pasd_fibre_portmap_begintime on pasd_fibre_portmap (begintime);
CREATE INDEX pasd_fibre_portmap_endtime on pasd_fibre_portmap (endtime);



/* Table to store the current state of all of the SMARTboxes, in every station

*/
CREATE TABLE pasd_smartbox_state (
    -- Values read from the device, via Modbus register reads:
    station_id integer,          -- Station ID
    smartbox_number integer,     -- Equal to the fibre ribbon number (1-24) for the SMARTbox in that station
    mbrv integer,                -- Modbus register-map revision number for this physical SMARTbox
    pcbrv integer,               -- PCB revision number for this physical SMARTbox
    cpuid text,                  -- CPU identifier (integer)
    chipid integer[],            -- Unique ID number (16 bytes), different for every physical SMARTbox
    firmware_version integer,    -- Firmware revision mumber for this physical SMARTbox
    uptime integer,              -- Time in seconds since this SMARTbox was powered up
    incoming_voltage float,      -- Measured voltage for the (nominal) 48VDC input power (Volts)
    psu_voltage float,           -- Measured output voltage for the internal (nominal) 5V power supply
    psu_temp float,              -- Temperature of the internal 5V power supply (deg C)
    pcb_temp float,              -- Temperature on the internal PCB (deg C)
    outside_temp float,          -- Outside temperature (deg C)
    status text,                 -- Status string, obtained from self.codes['status'] (eg 'OK')
    indicator_state text,        -- LED status flash/colour pattern name
    readtime integer,            -- Unix timestamp for the last successful polled data from this SMARTbox
    pdoc_number integer,          -- Physical PDoC port on the FNDH that this SMARTbox is plugged into. Populated by the station initialisation code on powerup

    -- Values to be written to the device, via Modbus register writes:
    service_led boolean,         -- Set to True to turn on the blue service indicator LED

    PRIMARY KEY(station_id, smartbox_number)
);


/* Table to store the current state of all of the FNHD's - one per station

*/

CREATE TABLE pasd_fndh_state (
    -- Values read from the device, via Modbus register reads:
    station_id integer,          -- Station ID
    mbrv integer,                -- Modbus register-map revision number for this physical SMARTbox
    pcbrv integer,               -- PCB revision number for this physical SMARTbox
    cpuid text,                  -- CPU identifier (integer)
    chipid integer[],            -- Unique ID number (16 bytes), different for every physical SMARTbox
    firmware_version integer,    -- Firmware revision mumber for this physical SMARTbox
    uptime integer,              -- Time in seconds since this SMARTbox was powered up
    psu48v1_voltage float,       -- Voltage measured on the output of the first 48VDC power supply (Volts)
    psu48v2_voltage float,       -- Voltage measured on the output of the second 48VDC power supply (Volts)
    psu5v_voltage float,         -- Voltage measured on the output of the 5VDC power supply (Volts)
    psu48v_current float,        -- Total current on the 48VDC bus (Amps)
    psu48v_temp float,           -- Common temperature for both 48VDC power supplies (deg C)
    psu5v_temp float,            -- Temperature of the 5VDC power supply (Volts)
    pcb_temp float,              -- Temperature on the internal PCB (deg C)
    outside_temp float,          -- Outside temperature (deg C)
    status text,                 -- Status string, obtained from self.codes['status'] (eg 'OK')
    indicator_state text,        -- LED status flash/colour pattern name
    readtime integer,            -- Unix timestamp for the last successful polled data from this SMARTbox

    -- Values to be written to the device, via Modbus register writes:
    service_led boolean,         -- Set to True to turn on the blue service indicator LED

    PRIMARY KEY(station_id)
);



/* Table to store the current state of each of the 288 SMARTbox input ports per station

   One row per SMARTbox port in all of the stations. Most of the data is read (polled once a minute or so)
   from the SMARTboxes, with the 'status_timetamp' and 'current_draw_timestamp' containing the time at which the
   status data and current measurement, respectively, were read from the SMARTbox. Old values in those columns
   mean that the SMARTbox is unreachable, or the MCCS polling loop is not running.

   Only two columns ('desire_enabled_online' and 'desire_enabled_offline') contain data to be sent TO
   the SMARTbox. Whether changes in these columns will be written to the device immediately, or at the
   next polling time, is yet to be decided.

   When a SMARTbox is first powered on, it boots into an uninitialised 'offline' state, with very conservative
   temperature, current, etc thresholds. It stays in that state until the MCCS has established communications
   and sent the working configuration, when it transitions to the 'online' state. If the microcontroller sees
   that more than a few (exact number TBD) minutes has elapsed since the last Modbus packet from the MCCS, then
   the SMARTbox transitions back to the 'offline' state.

   The standard method for turning ports on and off is to set the 'desired_state_online' value to True or False.
   It's also possible to set the 'desired_state_offline' value to True, in which case the port will stay on
   even without an active MCCS, but this feature will probably only be used for engineering tests, or in the
   laboratory.

   If the output current is too high on a port, the microcontroller will turn the power off to that port to
   prevent damage, and set the 'breaker_tripped' to True, which will be read by the MCCS the next time the
   SMARTbox is polled, and saved to this table. Writing 'True' to the 'reset_breaker' column in this table
   will result in the MCCS sending a command to reset the breaker (whether that's immediately or at the next
   polling time is still TBD).

   Note that the 'circuit breaker' is purely in firmware in the micrcontroller, as it can operate faster than
   a physical breaker, and with a threshold that doesn't change with ambient temperature.
*/

CREATE TABLE pasd_smartbox_port_status (
    -- Values read from the device, via Modbus register reads:
    station_id integer,                         -- Station ID
    smartbox_number integer,                    -- Equal to the fibre ribbon number (1-24) for the SMARTbox in that station
    port_number integer,                        -- Equal to the fibre number (1-12) for the RFoF signal from that SMARTbox
    system_online boolean,                      -- Is the SMARTbox in the 'online' state now?
    current_draw float,                         -- Current being delivered to the FEM and antenna, in milliAmps
    locally_forced_on boolean,                  -- Has this port been locally forced ON by a technician override?
    locally_forced_off boolean,                 -- Has this port been locally forced OFF by a technician override?
    breaker_tripped boolean,                    -- Has the over-current breaker tripped on this port?
    power_state boolean,                        -- Is this port actually turned on and providing power?
    status_timestamp timestamp with time zone,  -- When the status data (locally_forced_on, etc) was read from the device
    current_draw_timestamp timestamp with time zone, -- When the current draw value was read from the device

    -- Values to be written to the device, via Modbus register writes:
    desire_enabled_online boolean,              -- Does the MCCS want this port enabled when the device is online
    desire_enabled_offline boolean,             -- Does the MCCS want this port enabled when the device is offline
    reset_breaker boolean,                      -- Set to True to force a circuit breaker reset on this port

    PRIMARY KEY(station_id, smartbox_number, port_number)
);



/* Table to store the current state of each of the 28 FNDH power/data-over-coax (PDoC) ports per station

   One row per FNDH PDoC port in all of the stations. Each FNDH has 28 PDoC ports that can provide power
   and data to a SMARTbox, and each can be switched on and off. Only 24 SMARTboxes can ever be connected at
   one time, because there are only 24 ribbons for the RFoF data. The SMARTbox with a modbus address of N
   will always be connected to fibre ribbon number N at the FNDH, but it could be connected to any one of
   the PDoC ports (to allow redundancy for port failures).

   Because the SMARTboxes are connected using a multi-drop serial bus, the Modbus address number is entirely
   unrelated to the physical PDoC port on the FNDH. The MCCS must work out the mapping between Modbus
   address and physical PDoC port on startup, by turning all 28 PDoC ports on one at time, with a delay
   between ports, then querying the 'time since poweron' value for all possible modbus addresses.

   Most of the data is read (polled once a minute or so) from the FNDH, with the 'status_timetamp' and
   containing the time at which the status data was read from the FNDH. An old value in this column
   means that the FNDH is unreachable, or the MCCS polling loop is not running.

   Only two columns ('desire_enabled_online' and 'desire_enabled_offline') contain data to be sent TO
   the FNDH. Whether changes in these columns will be written to the device immediately, or at the
   next polling time, is yet to be decided.

   When an FNDH is first powered on, it boots into an uninitialised 'offline' state, with very conservative
   temperature, current, etc thresholds. It stays in that state until the MCCS has established communications
   and sent the working configuration, when it transitions to the 'online' state. If the microcontroller sees
   that more than a few (exact number TBD) minutes has elapsed since the last Modbus packet from the MCCS, then
   the FNDH transitions back to the 'offline' state.

   The standard method for turning PDoC ports on and off is to set the 'desired_state_online' value to True or False.
   It's also possible to set the 'desired_state_offline' value to True, in which case the port will stay on
   even without an active MCCS, but this feature will probably only be used for engineering tests, or in the
   laboratory.

   If the output current is too high on a PDoC port, the hardware current limit circuit will trip, turning off
   the 48V power to that port. This will result in a 0/False value for the 'power sense bit for that port,
   which will be read by the MCCS the next time the FNDH is polled, and saved to this table. The only way
   to reset this hardware current limit to to turn the port off, then on again, using the
   desired_state_online column.

*/

CREATE TABLE pasd_fndh_port_status (
    -- Values read from the device, via Modbus register reads:
    station_id integer,                         -- Station ID
    pdoc_number integer,                        -- Physical power/data-over-coax port number (1-28), unrelated to SMARTbox address
    smartbox_number integer,                    -- NULL if not yet populated by the station startup code in the MCCS
    system_online boolean,                      -- Is the FNDH in the 'online' state now?
    locally_forced_on boolean,                  -- Has this port been locally forced ON by a technician override?
    locally_forced_off boolean,                 -- Has this port been locally forced OFF by a technician override?
    power_state boolean,                        -- Is this port turned on by the microcontroller?
    power_sense boolean,                        -- Is there 48V power present on the port output?
    status_timestamp timestamp with time zone,  -- When the status data (locally_forced_on, etc) was read from the device

    -- Values to be written to the device, via Modbus register writes:
    desire_enabled_online boolean,              -- Does the MCCS want this port enabled when the device is online
    desire_enabled_offline boolean,             -- Does the MCCS want this port enabled when the device is offline

    PRIMARY KEY(station_id, pdoc_number)
);

CREATE INDEX pasd_fndh_port_status_smartbox_number on pasd_fndh_port_status (smartbox_number);


/* Station management - reflects the state of the daemons managing each station, rather than the hardware that
   they control.
*/

CREATE TABLE pasd_stations (
    -- Status values pushed by the station daemon
    station_id integer,                         -- Station ID
    active boolean,                             -- True if the station is 'ON', with PDoC's powered up
    status text,                                -- 'OK', 'STARTUP', 'SHUTDOWN' or 'OFF'
    status_timestamp timestamp with time zone,  -- When the status data was read from the station daemon

    -- Values to be written, and acted on by the station daemon
    desired_active boolean                      -- True if the MCCS wants this station powered up
);
