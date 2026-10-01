"""
Execute DAT

me - this DAT

Make sure the corresponding toggle is enabled in the Execute DAT.
"""

import socket
import time

_RESET_INTERVAL_S = 90.0
_last_reset = 0.0

_TERMINAL_CHOPS = ('chop_pose', 'chop_hand', 'chop_face', 'chop_meta')

_COOK_EVERY_N_FRAMES = 4  # ~15Hz at 60fps project rate -- see perf note below

# ---- Mocapport bind guard -------------------------------------------------
# GAIA_INTERFACE.md, Mocapport/oscin1 default-7000 question, 2026-09-29.
# oscin_mocap.par.active used to mirror Mocapingest directly (a bare
# expression). VERIFIED LIVE what that actually risks, correcting an
# earlier wrong claim in GAIA_INTERFACE.md: two TD OSC operators in the
# SAME TD process CAN share one port with zero bind error (tested two
# live oscinCHOPs on one port -- both received an identical packet, no
# error on either; TD shares the socket internally between its own
# operators). What a plain socket.bind() from OUTSIDE that sharing
# actually hits is a real OSError (WinError 10048, tested against a
# port a live oscinCHOP already held) -- so this guard catches a
# genuinely external squatter (a different process, a second TD.exe) or
# Mocapport pointed at a port nothing Gaia-related should be near, NOT
# another gaia_client-family operator in this same project (TD already
# shares those fine). The other real risk from same-process sharing --
# oscin1-style receiving every /gaia/mocap/* packet too and flooding ITS
# channel table if its own oscaddressscope is unscoped -- is outside
# gaia_client's reach to guard (lives on the other operator, in whatever
# project this gets dropped into); oscin_mocap's own oscaddressscope
# (/gaia/mocap/{Opsdevice}/*, set via expression) already protects this
# component's own side of that.
def _portAvailable(port):
	"""Bind a throwaway UDP socket to `port` and close it immediately --
	True if nothing OUTSIDE this TD process holds it right now (a TD
	operator sharing the port internally does not make this fail, see
	the guard note above). Only called on a TRANSITION (see _held_port
	below) -- never re-probed for a port we already believe oscin_mocap
	itself holds, or the test would see oscin_mocap's OWN bind as "busy"
	and flap it off every re-evaluation (hit live while building this:
	the guard reported its own successful bind as a conflict one cook
	later and deactivated itself)."""
	ok = True
	probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
	try:
		probe.bind(('', port))
	except OSError:
		ok = False
	finally:
		probe.close()
	return ok


_held_port = None   # port we believe oscin_mocap currently holds, or None


def resolveActive():
	"""oscin_mocap.par.active's expression -- see the guard note above.
	Returns 0/1, and writes Mocapstatus so a blocked port is visible on
	the COMP instead of a silently-empty mocap feed. Only bind-tests on
	a real transition (off->on, or Mocapport changed while on); once
	_held_port matches the target port, trusts it without re-probing."""
	global _held_port
	cfg = op('..')
	wanted = bool(cfg.par.Mocapingest.eval())
	status = cfg.par.Mocapstatus
	if not wanted:
		_held_port = None
		status.val = ''
		return 0
	port = int(cfg.par.Mocapport.eval())
	if _held_port == port:
		return 1   # already holding it ourselves -- do not re-probe
	if _portAvailable(port):
		_held_port = port
		status.val = 'listening on %d' % port
		return 1
	_held_port = None
	status.val = ('PORT %d BUSY -- held by something outside this TD '
		'process (a different process, or another TD instance) -- not '
		'another operator in this same project, TD shares those. '
		'oscin_mocap stays inactive; free the port or change '
		'Mocapport.' % port)
	return 0


# ---- Admin -> TD remote mocap control ------------------------------------
# GAIA_INTERFACE.md, "collegare il pulsante Admin mocap" proposal
# 2026-09-30 (Core, 5), confirmed: Admin's Mocap Enable/Disable button
# (Pi Devices section) only ever told the SENDER to start/stop -- it never
# touched Mocapingest/Opsdevice on this side, so one click there did not
# guarantee anyone was actually listening. Fix is zero new protocol: this
# component's OWN Mocapingest/Opsdevice were simply never self-registered
# as remote-controllable params (register_param() already exists in
# gaia_device_agent.py for PROJECT scripts' services -- nothing stopped
# gaia_client registering its own built-in ones the same way). Registering
# them means Admin's existing channel-4 command
# ({"action":"set","param":"Mocapingest","value":true} /
#  {"action":"set","param":"Opsdevice","value":"<sender_id>"}) now lands
# on real setters, no new command shape needed on the Gaia side. Confirmed
# symmetric: Admin's Disable also flips Mocapingest off (Opsdevice is left
# alone -- it is just a filter value, harmless with ingest off).
#
# BUG FOUND LIVE 2026-09-30 (Core's real end-to-end test caught it, empty
# "params":{} in status): the first version of this guard used a LOCAL
# flag (_mocap_remote_control_registered) to decide whether to (re-)call
# register_param(). gaia_device_agent.py's _params dict is wiped on every
# reinit of THAT file (project save/restart, hot-reload) independently of
# whether mocap_lifecycle.py itself reinitializes -- so the local flag
# could stay True while the target dict was actually empty, and nothing
# ever re-registered. Fixed the same way gaia_device_agent.py's own
# _self_check() already handles this for project-registered services:
# check the TARGET's actual state every call, not a local belief about
# it.
def _ensureMocapRemoteControl():
	"""Call every frame from onFrameStart -- cheap dict-key check, so this
	self-heals the moment gaia_device_agent.py reinitializes independently
	of this file (see the bug note above)."""
	agent = op('gaia_device_agent')
	if agent is None:
		return
	mod = agent.module
	cfg = op('..')
	# Mocapremote (optional par, portable 1.1.0+): off = this host drives
	# mocap itself (e.g. TD-Gaia's own Visuals/mocap_bridge), so Admin's
	# Mocap button must NOT be able to switch on a second, parallel
	# pipeline here. Missing par = allowed (older parameter pages).
	remote = cfg.par['Mocapremote']
	if remote is not None and not remote.eval():
		mod._params.pop('Mocapingest', None)
		mod._params.pop('Opsdevice', None)
		return
	if 'Mocapingest' in mod._params:
		return
	mod.register_param('Mocapingest',
		get=lambda: bool(cfg.par.Mocapingest.eval()),
		set=lambda value: setattr(cfg.par, 'Mocapingest', bool(value)),
		builtin=True)
	mod.register_param('Opsdevice',
		get=lambda: cfg.par.Opsdevice.eval(),
		set=lambda value: setattr(cfg.par, 'Opsdevice', str(value)),
		builtin=True)


def onFrameStart(frame: int):
	"""
	Called at the start of each frame.

	Terminal Script CHOPs read oscin_mocap via a plain op() call (not a
	wired CHOP input), so TD's normal cook-dependency graph does not pick
	up new OSC data automatically -- force-cook them so they reflect
	latest mocap regardless of whether anything is currently demanding
	their output.

	PERF: force-cooking all 4 every frame measured ~12.5ms/frame CPU
	(childrenCPUCookTime), dropping project fps below performance.md's
	90%-of-target stop threshold. Throttled to every Nth frame instead:
	mocap-driven abstract visuals don't need 60Hz semantic updates, and
	this cuts the cost proportionally.
	"""
	global _last_reset

	_ensureMocapRemoteControl()

	# Nothing to read while ingest is off -- skip the force-cooks and the
	# periodic reset entirely instead of cooking 4 Script CHOPs on an
	# inactive OSC In for no output.
	mocap_in = op('oscin_mocap')
	if mocap_in is None or not mocap_in.par.active.eval():
		return

	if frame % _COOK_EVERY_N_FRAMES == 0:
		for name in _TERMINAL_CHOPS:
			chop = op(name)
			if chop is not None:
				chop.cook(force=True)

	# oscin_mocap has no automatic channel expiry (2000+ channels within
	# under a minute of live traffic, verified live) -- periodically wipe
	# and let it rebuild from live OSC only, bounding its own CPU memory.
	# The terminal CHOPs above are bounded regardless, so this only protects
	# oscin_mocap's own footprint, not correctness of what's read from it.
	now = time.time()
	if (now - _last_reset) >= _RESET_INTERVAL_S:
		_last_reset = now
		mocap = op('oscin_mocap')
		if mocap is not None:
			mocap.par.resetchannelspulse.pulse()
	return
