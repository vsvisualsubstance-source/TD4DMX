"""pre_release hook for op.Embody.ExportPortableTox (see /externalize-operator).

Runs via DAT.run() -- top-level script, NOT a function Embody calls by
name -- on a STAGED COPY of /gaia_client in /sys/quiet -- the live
component is never touched, so this can freely blank instance/project
identity without any risk to the running MQTT connections. Deleted from
the copy before the .tox is written, so this code never ships in the
artifact. me = this hook DAT (on the copy); parent() = the copy of
/gaia_client; args[0] = resolved save path (unused here).

Blanks every identity par that must never leak a specific
deployment/project into the portable template (see gaia-client-portable-
component and gaia-client-family-parameter memory): Deviceid, Stanza,
opshortcut (global-shortcut collision across instances), and Family
(GAIA_INTERFACE.md section 1b, added 2026-08-29). Name resets to its
built-in default ('GaiaClient') rather than blank -- same treatment
already used for the previous portable export (verified live before this
hook existed: Name='GaiaClient' in gaia_client_portable.tox, not '').
Deliberately leaves Brokerhost/Brokerport/Tailscalehost/Opsdevice/Mocapport
and every Services toggle untouched -- those are deployment-wide LAN/
Tailscale defaults, not per-instance identity, and changing them here would
fight the deliberate opt-in defaults already baked into the component (see
gaia-client-portable-component memory).
"""

comp = parent()
comp.par.Deviceid = ''
comp.par.Stanza = ''
comp.par.opshortcut = ''
comp.par.Family = ''
comp.par.Name = comp.par.Name.default
