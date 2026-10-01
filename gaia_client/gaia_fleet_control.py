"""
GAIA Fleet Control -- play/stop/restart of EVERY Gaia device's services,
natively from inside TouchDesigner. Same role as Pi Manager in Gaia's own
web admin, same MQTT protocol, but here TD is the CONTROLLER: it listens to
every device's status (gaia/device/+/status) and can send enable/disable/
restart commands to any of them.

Complementary to gaia_device_agent (which instead makes THIS TD instance
show up as one controllable device) -- the two modules coexist in the same
component without conflict.

Uses TD's native mqttclientDAT (see gaia_device_agent.py's docstring for
why -- no paho, no thread-safety machinery, the mqttclientDAT operator IS
the client).

USING IT FROM YOUR OWN UI
    op('gaia_client/gaia_fleet_control').module.get_devices()
        -> dict device_id -> last status payload (+ "_last_seen")
    op('gaia_client/gaia_fleet_control').module.send_command(
        device_id, service_name, 'enable')   # or 'disable' / 'restart'
send_command() is safe to call directly from a UI callback (already on TD's
main thread). devices_table (a sibling Table DAT) holds one row per
device+service pair (device_id, name, stanza, role, service, state,
offline) -- bind a List COMP to it directly for a live device browser; no
UI is bundled here since that's a per-project visual choice.

MOCAP SENDER DISCOVERY (2026-09-30, GAIA_INTERFACE.md, confirmed option 1):
this file also maintains a SECOND, independent view of the same
gaia/device/+/status stream -- which devices currently report
osc_landmarks=true (get_mocap_senders(), also pushed live onto the Mocap
page's Opsdevice StrMenu suggestions and Mocapsenders read-only text).
Deliberately does NOT depend on Devicecontrol/_enabled() above: most
single-purpose mocap-receiving installs run Device Fleet Control off, and
sender discovery must keep working anyway.

STATES: "active" / "inactive" / "failed" -- the exact values published by
Pi/OPS/local agents, no translation. offline=True if a device hasn't sent
status in more than OFFLINE_AFTER_S seconds.

Services > Device Fleet Control (on this component) gates whether incoming
status is stored/tabulated and whether the staleness sweep runs -- the
mqttclientDAT itself always stays connected regardless (never toggle
mqttclientDAT.par.active after it's up).
"""
import json
import time

OFFLINE_AFTER_S = 90
STALENESS_CHECK_S = 10
MIN_REBUILD_INTERVAL_S = 1.0   # cap table rebuilds even under a status-message flood

_devices = {}   # device_id -> {status..., "_last_seen": float}
_last_staleness_check = 0.0
_last_rebuild = 0.0
_pending = False    # True when _devices changed but devices_table hasn't been rebuilt yet
_last_rows = None   # rows last written to devices_table -- skip identical rewrites
_dirty = False      # set True by _rebuild_table(), cleared+reported by tick()


def _enabled():
	try:
		return bool(me.parent().par.Devicecontrol.eval())
	except Exception:
		return True


def _mqtt():
	return me.parent().op('mqtt_control')


def get_devices():
	"""Snapshot of device_id -> last received status payload."""
	return {k: dict(v) for k, v in _devices.items()}


def send_command(device_id, service, action):
	"""Call from a Button/List COMP: play='enable', stop='disable',
	restart='restart'. Safe from a UI callback (main thread)."""
	dat = _mqtt()
	if dat is None or not dat.isConnected:
		print("[GAIA Fleet Control] not connected, command ignored")
		return
	dat.publish(
		f"gaia/device/{device_id}/command",
		json.dumps({"action": action, "service": service}).encode('utf-8'),
	)


def _svc_keys(d):
	keys = list((d.get("services") or {}).keys())
	for k in (d.get("config") or {}):
		if k not in keys:
			keys.append(k)
	return keys


# ---- Mocap sender discovery ---------------------------------------------
# GAIA_INTERFACE.md, mocap-sender-discovery proposal 2026-09-30, confirmed
# option 1 (Core, 1): gaia/device/{id}/status's osc_landmarks field is the
# reliable liveness signal (same 30s heartbeat already relied on for
# online/offline elsewhere in this file) -- NOT gaia/mocap-bridge/+/status
# (event-driven only, no self-heartbeat, can freeze "alive" on a crashed
# sender, see Core's reply). Deliberately INDEPENDENT of the Devicecontrol
# gate above: most single-purpose mocap-receiving installs run with
# Device Fleet Control OFF (that toggle is for the one control-room
# machine, not every install -- see annotate4/the operator tutorial), so
# sender discovery must not silently stop working just because fleet
# control is off. Reuses the SAME mqtt_control subscription
# (gaia/device/+/status, already subscribed in on_connect() below) --
# zero new MQTT connection or topic.
_MOCAP_SENDER_TTL_S = 90   # same staleness window as OFFLINE_AFTER_S
_mocap_senders = {}        # device_id -> {"name", "stanza", "_last_seen"}
_mocap_senders_dirty = False


def get_mocap_senders():
	"""Snapshot of device_id -> {name, stanza, _last_seen} for every
	device that last reported osc_landmarks==true within
	_MOCAP_SENDER_TTL_S."""
	return {k: dict(v) for k, v in _mocap_senders.items()}


def _handle_mocap_sender_status(d):
	"""Called from on_message() for EVERY gaia/device/+/status message,
	unconditionally -- see the module note above for why this must not
	depend on Devicecontrol/_enabled()."""
	global _mocap_senders_dirty
	device_id = d.get("device_id")
	if not device_id:
		return
	if d.get("osc_landmarks"):
		_mocap_senders[device_id] = {
			"name": d.get("name") or d.get("stanza") or device_id,
			"stanza": d.get("stanza", ""),
			"_last_seen": time.time(),
		}
		_mocap_senders_dirty = True
	elif device_id in _mocap_senders:
		# Explicit false -- sender turned mocap off, drop it immediately
		# instead of waiting for the TTL sweep below.
		del _mocap_senders[device_id]
		_mocap_senders_dirty = True


def _sweepMocapSenders():
	"""TTL fallback for a sender that vanished without publishing a
	final osc_landmarks:false (crash, power loss) -- same reasoning as
	OFFLINE_AFTER_S above, applied to this independent dict."""
	global _mocap_senders_dirty
	now = time.time()
	stale = [k for k, v in _mocap_senders.items()
			 if (now - v["_last_seen"]) > _MOCAP_SENDER_TTL_S]
	for k in stale:
		del _mocap_senders[k]
		_mocap_senders_dirty = True


def _refreshMocapUi():
	"""Push the current sender list onto Opsdevice's StrMenu suggestions
	and the read-only Mocapsenders status text. Only writes when the set
	actually changed (_mocap_senders_dirty) -- this runs on the same
	throttle as the staleness sweep, not every frame, but still avoid a
	no-op Par write."""
	global _mocap_senders_dirty
	if not _mocap_senders_dirty:
		return
	_mocap_senders_dirty = False
	cfg = me.parent()
	ids = sorted(_mocap_senders.keys())
	# Both pars arrived with portable build 1.1.0 -- a host still carrying
	# an older gaia_client parameter page must not raise every 10s here.
	menu_par = cfg.par['Opsdevice']
	if menu_par is not None and menu_par.style == 'StrMenu':
		menu_par.menuNames = ids
		menu_par.menuLabels = [
			('%s (%s)' % (i, _mocap_senders[i]['stanza'])) if _mocap_senders[i]['stanza'] else i
			for i in ids
		]
	senders_par = cfg.par['Mocapsenders']
	if senders_par is not None:
		senders_par.val = ', '.join(ids) if ids else 'none seen recently'


def _rebuild_table():
	"""Rewrite devices_table from _devices -- but only when the rows
	actually differ from what is already there. Most status messages are
	30s heartbeats that change nothing visible; skipping those avoids
	recooking every List COMP / DAT bound to the table (and, if Sync to
	File is ever turned on, a disk write) for no reason."""
	global _dirty, _last_rows
	table = me.parent().op("devices_table")
	if table is None:
		return
	now = time.time()
	rows = [["device_id", "name", "stanza", "role", "service", "state", "offline"]]
	for device_id, d in sorted(_devices.items()):
		offline = (now - d.get("_last_seen", 0)) > OFFLINE_AFTER_S
		keys = _svc_keys(d) or [""]
		for svc in keys:
			state = (d.get("services") or {}).get(svc, "unknown")
			rows.append([
				device_id, str(d.get("name") or d.get("stanza") or device_id),
				str(d.get("stanza", "")), str(d.get("role", "")), svc, str(state), str(offline),
			])
	if rows == _last_rows and table.numRows == len(rows):
		return
	_last_rows = rows
	_dirty = True
	table.clear()
	table.appendRows(rows)


def _maybe_rebuild(force=False):
	"""Rebuild devices_table, but never more often than
	MIN_REBUILD_INTERVAL_S -- a burst of status messages must not turn
	into one table (and, when Sync to File is on, disk) write per
	message. Root cause of the recurring "disk-write storm" fixed in
	TD-Gaia on 2026-09-16 (commit 7a15e6b) and merged back into the
	portable here. Called from on_message() (per-message, debounced) and
	from tick() (every frame, to flush a pending rebuild once its debounce
	window elapses, and for the periodic staleness sweep)."""
	global _last_rebuild, _pending
	now = time.time()
	if not force and (now - _last_rebuild) < MIN_REBUILD_INTERVAL_S:
		_pending = True
		return
	_last_rebuild = now
	_pending = False
	_rebuild_table()


def tick():
	"""Call from Execute DAT onFrameStart, EVERY FRAME -- recomputes the
	'offline' flag every STALENESS_CHECK_S seconds (devices don't publish
	every frame, but a vanished device must still show offline within
	OFFLINE_AFTER_S), flushes a rebuild left pending by _maybe_rebuild()'s
	debounce, and returns True if devices_table changed this frame.
	Mocap-sender sweep/UI refresh run on the SAME throttle regardless of
	Devicecontrol -- see the mocap sender discovery module note above."""
	global _last_staleness_check, _dirty
	now = time.time()
	if (now - _last_staleness_check) >= STALENESS_CHECK_S:
		_last_staleness_check = now
		_sweepMocapSenders()
		_refreshMocapUi()
		if _enabled():
			_maybe_rebuild(force=True)
	elif _pending and _enabled() and (now - _last_rebuild) >= MIN_REBUILD_INTERVAL_S:
		_maybe_rebuild()
	changed, _dirty = _dirty, False
	return changed


# ---- Called from mqtt_control_callbacks -- already on the main thread
# (native Callbacks DAT dispatch). -----------------------------------------

def on_connect(dat):
	dat.subscribe("gaia/device/+/status")
	print("[GAIA Fleet Control] Connected, listening on gaia/device/+/status")


def on_connect_failure(msg):
	print(f"[GAIA Fleet Control] MQTT connection failed: {msg}")


def on_connection_lost(msg):
	print(f"[GAIA Fleet Control] Disconnected: {msg}")


def on_message(topic, payload):
	if isinstance(payload, bytes):
		payload = payload.decode('utf-8', errors='replace')
	try:
		d = json.loads(payload)
	except Exception as e:
		print(f"[GAIA Fleet Control] Invalid status: {e}")
		return
	_handle_mocap_sender_status(d)   # unconditional -- see module note above
	if not _enabled():
		return
	device_id = d.get("device_id")
	if not device_id:
		return
	d["_last_seen"] = time.time()
	_devices[device_id] = d
	_maybe_rebuild()
