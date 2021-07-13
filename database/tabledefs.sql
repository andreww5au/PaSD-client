
/* This table contains 288 rows per station, for 24 smartboxes each with 12 ports. Up
   to 256 of these will have valid antenna numbers for the antenna connected to those ports,
   the rest will have antenna_number=NULL.

   This mapping table exists to allow antennae to be moved between ports on a single SMARTbox,
   or between SMARTboxes, to allow for redundancy in the case of hardware failures. Any antenna
   move like this will need to be accompanied by a matching fibre swap to the actual TPM inputs.

   Note that the antenna number is within the station, so always 1-256

   Note also that the station ID and smartbox address define which 12-fibre ribbon the data arrives
        on at the TPM, and the port number defines which fibre inside that ribbon it uses.
 */
CREATE TABLE antenna_portmap (
    antenna_number integer PRIMARY KEY,  -- number within station - 1-256
    station_id integer,                  -- arbitrary station ID
    smartbox_address integer,            -- Modbus address (1-24) of the SMARTbox in that station
    port_number integer                  -- Port number (1-12) of the FEM port in that SMARTbox
);

CREATE INDEX antenna_portmap_port on antenna_portmap (station_id, smartbox_address, port_number)

