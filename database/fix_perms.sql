alter table pasd_antenna_portmap owner to pasd;
alter table pasd_fibre_portmap owner to pasd;
alter table pasd_smartbox_state owner to pasd;
alter table pasd_fndh_state owner to pasd;
alter table pasd_smartbox_port_status owner to pasd;
alter table pasd_fndh_port_status owner to pasd;
alter table pasd_stations owner to pasd;

grant select on pasd_antenna_portmap to mwaschedule, mwa_ro, mwa, tapuser, mwacode, PUBLIC;
grant select on pasd_fibre_portmap to mwaschedule, mwa_ro, mwa, tapuser, mwacode, PUBLIC;
grant select on pasd_smartbox_state to mwaschedule, mwa_ro, mwa, tapuser, mwacode, PUBLIC;
grant select on pasd_fndh_state to mwaschedule, mwa_ro, mwa, tapuser, mwacode, PUBLIC;
grant select on pasd_smartbox_port_status to mwaschedule, mwa_ro, mwa, tapuser, mwacode, PUBLIC;
grant select on pasd_fndh_port_status to mwaschedule, mwa_ro, mwa, tapuser, mwacode, PUBLIC;
grant select on pasd_stations to mwaschedule, mwa_ro, mwa, tapuser, mwacode, PUBLIC;
