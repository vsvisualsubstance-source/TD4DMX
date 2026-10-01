"""
GAIA Device Agent -- makes this TD instance appear as ONE controllable
device in Gaia's registry (gaia/device/{id}/status, heartbeat + remote
enable/disable/restart/set commands). Complementary to gaia_fleet_control
(which instead makes this instance a CONTROLLER of every OTHER Gaia
device) -- the two are independent modules that coexist without conflict.

Lives entirely INSIDE the TouchDesigner project (a Text DAT + Execute DAT +
a native mqttclientDAT), not an external system process: no filesystem
manifest, no path to TouchDesigner.exe, runs wherever the .toe runs,
configured via this component's own custom parameters, saved with the
project itself -- portable across machines with nothing to touch outside
the .toe.

Uses TD's NATIVE mqttclientDAT -- never paho.mqtt.client. TD's embedded
Python has no pip; a paho-based client only ever works by accident (via a
venv incidentally on sys.path) and fails silently the moment that's not
true. The native DAT dispatches onConnect/onMessage on TD's main thread
already, so there is no live Python client object, no thread-safety
machinery, and nothing to track/stop between one project.save() and the
next -- the "client" IS the mqttclientDAT operator, managed by TD like any
other externalized DAT.

EXPOSING A REAL SERVICE (per-project, optional)
Without doing anything else the agent already shows up in Gaia's Admin
(presence + heartbeat, "services" empty, commands are no-op logged). To
wire a real control, from a project-specific script (this file itself
should stay identical across projects -- don't edit it per-project):

    agent = op('gaia_client/gaia_device_agent').module
    agent.register_service('osc_in',
        start=lambda: setattr(op('oscin1').par, 'active', 1),
        stop=lambda: setattr(op('oscin1').par, 'active', 0),
        status=lambda: bool(op('oscin1').par.active.eval()))

    # Continuous (non-boolean) values -- gain/threshold/etc, not on/off:
    agent.register_param('ch0_gain',
        get=lambda: float(op('...').par.Gain.eval()),
        set=lambda value: setattr(op('...').par, 'Gain', float(value)))

start/stop/status/get/set are always invoked from on_message() (already on
TD's main thread, native Callbacks DAT dispatch), so it's safe to touch
op()/par inside them directly.

Same MQTT protocol as the Pi/OPS agents: gaia/device/{id}/status (retained,
every 30s) + enable/disable/restart/set commands on gaia/device/{id}/command
and gaia/device/all/command. Also announces to the Node-RED Device Registry
(gaia/devices/{id}/announce + subscribes gaia/devices/{id}/config) and
publishes a semantic profile (gaia/devices/{id}/profile, retained --
capabilities derived from services ACTUALLY registered, never assumed).

status payload includes "ip" (stdlib socket only, no external dependency) --
used by some Gaia OPS mediapipe nodes for direct mocap OSC redirect to
whichever machine is actually running this TD instance, instead of a fixed
IP that goes stale the moment TD moves machines. Also includes fps/
target_fps/dropped_frames (project.cookRate is only the CONFIGURED target,
not real fps -- true fps is measured in perf_tick() by comparing real
elapsed time between consecutive frames) and _last_error (last exception
from a registered service/param call, visible in Admin without opening
TD's Textport; cleared automatically on the next successful call).

Services > Device Status (on this component) gates whether tick() publishes
and whether incoming commands are actually applied -- the mqttclientDAT
itself always stays connected regardless (never toggle
mqttclientDAT.par.active after it's up; that alone has crashed TD before
with no code changes involved).
"""
import hashlib
import json
import os
import queue
import shutil
import socket
import subprocess
import threading
import time

# Version of THIS component (gaia_client), not of the host project -- bump
# on every portable release (GAIA_INTERFACE.md section 1c). Published as
# sw_version in profile AND status so Gaia can tell which instances still
# run an older build after a new portable .tox ships. 1.0 = every build
# up to 2026-09-29; 1.1.0 = tailscale_ip/internet, broadcast beacon,
# per-device MQTT client_id, mocap remote control + sender discovery;
# 1.2.0 = stable output connectors (soul, mocap, status, words, word, thought).
# 1.2.1 = _self_check ignores gaia_client's own built-in params (Mocapingest/
#         Opsdevice): with them registered the project registrar never ran
#         (PatchDeck showed 0 services after upgrading to 1.2.0).
SW_VERSION = "1.2.1"

_START_TS = time.time()
_services = {}   # name -> {"start": fn, "stop": fn, "status": fn}
_params = {}     # name -> {"get": fn, "set": fn(value)} -- continuous values
_builtin_params = set()  # _params keys owned by gaia_client itself, not the project

_HEARTBEAT_S = 30
_last_heartbeat = 0.0

_last_error = None   # {"context","message","ts"} -- last error, visible in Admin

_registrar = None                 # project-specific idempotent registration retry hook
_REGISTRAR_CHECK_S = 10.0
_REGISTRAR_GRACE_S = 10.0         # startup grace before the empty-registry warning fires
_last_registrar_check = 0.0

_last_identity_state = None       # cache so _check_identity only writes on a real transition
_IDENTITY_OK_COLOR = (0.6700000166893005, 0.6700000166893005, 0.6700000166893005)
_IDENTITY_WARN_COLOR = (0.85, 0.22, 0.18)


def _record_error(context, exc):
	global _last_error
	_last_error = {"context": context, "message": str(exc), "ts": int(time.time() * 1000)}
	print(f"[GAIA Agent] Error in {context}: {exc}")


def _enabled():
	try:
		return bool(me.parent().par.Devicestatus.eval())
	except Exception:
		return True


# ---- Real fps (project.cookRate is only the configured target) ----------
_PERF_WINDOW = 90
_perf_intervals = []
_perf_last_time = None
_perf_dropped_window = 0


# ---- tailscale_ip / internet self-report ---------------------------------
# GAIA_INTERFACE.md sezione 3 + richiesta Core 2026-09-29: stesso nome
# campo/schema gia' in produzione su Pi/OPS/Core (net_resolve.py) cosi'
# Gaia puo' aprire un secondo client OSC/MQTT verso l'IP Tailscale quando
# quello LAN non e' raggiungibile (mocap/canvas multi-rete). Popolato
# leggendo l'interfaccia Tailscale locale se presente, altrimenti None
# (mai bloccante, mai un requisito online -- stesso principio "Gaia resta
# offline" del beacon discovery).
#
# Plain threading.Thread invece del Palette Thread Manager: questo resta
# un .tox senza dipendenze esterne (ExportPortableTox promette "funziona
# in qualunque progetto TD senza missing file"), ed e' lavoro one-shot per
# refresh, non un loop long-lived -- vedi /td-api-reference
# background-work.md rung 5 (il worker non tocca nessun oggetto TD, i
# risultati tornano via una queue.Queue drenata ogni frame da perf_tick(),
# stesso contratto richiesto dalla ladder).
_NET_TTL_S = 90.0
_ts_ip_cache = None
_internet_cache = False
_net_cache_ts = 0.0
_net_inflight = False
_net_queue = queue.Queue()


def _tailscale_binary():
	"""Trova il binario tailscale sul PATH, altrimenti il path di
	installazione standard Windows (stesso identico gotcha documentato in
	gaia's net_resolve.py -- pythonw.exe/LaunchAgent spesso hanno un PATH
	ridotto che lo omette anche se installato)."""
	exe = 'tailscale.exe' if os.name == 'nt' else 'tailscale'
	found = shutil.which(exe)
	if found:
		return found
	if os.name == 'nt':
		candidates = [r'C:\Program Files\Tailscale\tailscale.exe']
	else:
		# macOS: Tailscale.app (App Store / standalone) ships its CLI inside
		# the bundle and does NOT put it on PATH -- and TD launched from
		# Finder gets a minimal PATH anyway. Homebrew paths cover the
		# open-source tailscaled install.
		candidates = ['/Applications/Tailscale.app/Contents/MacOS/Tailscale',
			'/opt/homebrew/bin/tailscale', '/usr/local/bin/tailscale']
	for path in candidates:
		if os.path.exists(path):
			return path
	return None


def _probe_tcp(host, port, timeout=1.5):
	try:
		with socket.create_connection((host, port), timeout=timeout):
			return True
	except OSError:
		return False


def _refresh_net_worker(out):
	"""WORKER thread -- non tocca nessun oggetto TD. _tailscale_binary()
	(shutil.which, un giro sul filesystem PATH) va calcolato QUI e non sul
	main thread prima di lanciare il worker -- altrimenti e' esattamente
	l'I/O sincrono sul main thread che questa architettura serve a
	evitare. Stessi probe di net_resolve.py: 'tailscale ip -4' per l'IP
	tailscale locale, una TCP connect nuda verso due resolver DNS
	pubblici per la reachability internet."""
	exe = _tailscale_binary()
	ts_ip = None
	if exe is not None:
		try:
			result = subprocess.run([exe, 'ip', '-4'], capture_output=True, text=True, timeout=1.5)
			if result.returncode == 0 and result.stdout.strip():
				ts_ip = result.stdout.strip().splitlines()[0].strip()
		except Exception:
			ts_ip = None
	internet = _probe_tcp('1.1.1.1', 53) or _probe_tcp('8.8.8.8', 53)
	out.put((ts_ip, internet))


def _maybe_refresh_net():
	"""Chiamata ogni frame da perf_tick() -- throttled internamente a
	_NET_TTL_S. Drena prima un eventuale worker completato, poi ne lancia
	uno nuovo solo se la cache e' scaduta e nessun refresh e' gia' in
	corso."""
	global _net_inflight, _ts_ip_cache, _internet_cache, _net_cache_ts
	now = time.time()
	try:
		while True:
			_ts_ip_cache, _internet_cache = _net_queue.get_nowait()
			_net_cache_ts = now
			_net_inflight = False
	except queue.Empty:
		pass
	if _net_inflight or (now - _net_cache_ts) < _NET_TTL_S:
		return
	_net_inflight = True
	threading.Thread(target=_refresh_net_worker, args=(_net_queue,), daemon=True).start()


def perf_tick():
	"""Call EVERY frame from onFrameStart (agent_lifecycle.py), unthrottled
	unlike tick()."""
	global _perf_last_time, _perf_dropped_window
	_check_identity()
	_self_check()
	_maybe_refresh_net()
	now = time.time()
	if _perf_last_time is not None:
		dt = now - _perf_last_time
		_perf_intervals.append(dt)
		if len(_perf_intervals) > _PERF_WINDOW:
			_perf_intervals.pop(0)
		target = _target_fps()
		if target and dt > 0:
			expected = dt * target
			if expected > 1.5:
				_perf_dropped_window += int(round(expected)) - 1
	_perf_last_time = now


def _target_fps():
	try:
		return round(float(project.cookRate), 2)
	except Exception:
		return None


def _measured_fps():
	if len(_perf_intervals) < 2:
		return None
	avg_dt = sum(_perf_intervals) / len(_perf_intervals)
	return round(1.0 / avg_dt, 1) if avg_dt > 0 else None


def _get_ip():
	"""UDP 'connect' to a public address -- no packet actually sent, just
	reads the local IP the OS routing table would use."""
	try:
		with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
			s.connect(("8.8.8.8", 80))
			return s.getsockname()[0]
	except Exception:
		return "unknown"


def register_service(name, start=None, stop=None, status=None):
	"""Call from your project-specific script to expose a real on/off
	control. status() must return True/False (or None if unknown)."""
	_services[name] = {"start": start, "stop": stop, "status": status}


def register_param(name, get=None, set=None, builtin=False):
	"""Call from your project-specific script to expose a CONTINUOUS
	controllable value (gain, threshold, ...), not a simple on/off. get()
	returns the current value (any JSON-serializable type); set(value)
	applies a new one. builtin=True is for gaia_client's own params only
	(mocap_lifecycle): they don't count as "the project registered" in
	_self_check()."""
	_params[name] = {"get": get, "set": set}
	if builtin:
		_builtin_params.add(name)
	else:
		_builtin_params.discard(name)


def register_project_registrar(fn):
	"""Opt into the empty-registry self-check/Re-register safety net (see
	_self_check()/reregister(), GAIA_INTERFACE.md section 2). Call once from
	the project-specific startup script (its own onCreate/onStart -- e.g.
	PATCHDECK/gaia_services/lifecycle.py) with an IDEMPOTENT registration
	function (safe to call repeatedly; it must skip work already done, same
	contract as register_all() there). This module's state -- including
	this pointer -- is wiped on every hot-reload of THIS file, so the
	caller should also re-arm it periodically (a cheap poll, not a full
	self-heal reimplementation) rather than only from onCreate/onStart."""
	global _registrar
	_registrar = fn


def reregister():
	"""Manually retry project service registration -- wired to the
	Re-register pulse par (see mqtt_control_callbacks-style docked
	callback), also callable directly. No-op (logged) if no project
	registrar has been set."""
	if _registrar is None:
		print('[GAIA Agent] Re-register requested but no project registrar is set '
			'(register_project_registrar() never called)')
		return
	print('[GAIA Agent] Re-registering project services...')
	_registrar()


def _self_check():
	"""Called every frame from perf_tick() (independent of the Devicestatus
	toggle -- registration matters even when status publishing is off).
	Empty _services/_params is legitimate for a project that never calls
	register_project_registrar() (nothing declared, nothing expected) --
	this only fires for projects that DID declare intent, catching the
	documented silent-empty-registry failure mode (a hot-reloaded module
	whose onCreate/onStart never reran, GAIA_INTERFACE.md section 2)."""
	global _last_registrar_check
	if _registrar is None or _services or (_params.keys() - _builtin_params):
		return
	now = time.time()
	if (now - _START_TS) < _REGISTRAR_GRACE_S:
		return
	if (now - _last_registrar_check) < _REGISTRAR_CHECK_S:
		return
	_last_registrar_check = now
	print('[GAIA Agent] WARNING: project registrar set but no services/params '
		'registered -- retrying')
	_registrar()


def _check_identity():
	"""Called every frame from perf_tick(). Deviceid/Family must never be
	silently inherited from a clone and forgotten (GAIA_INTERFACE.md
	sections 1/1b) -- when either is blank, the component tile turns red
	in the network editor and Identitystatus names what's missing. Cached
	against _last_identity_state so this only writes color/par on an
	actual transition, not every frame."""
	global _last_identity_state
	host = me.parent()
	missing = []
	if not host.par.Deviceid.eval():
		missing.append('Deviceid')
	if not host.par.Family.eval():
		missing.append('Family')
	state = tuple(missing)
	if state == _last_identity_state:
		return
	_last_identity_state = state
	if missing:
		host.par.Identitystatus = 'MISSING: %s -- set explicitly before cloning/deploying' % ', '.join(missing)
		host.color = _IDENTITY_WARN_COLOR
		print('[GAIA Agent] WARNING: %s not set on %s' % (', '.join(missing), host.path))
	else:
		host.par.Identitystatus = 'ok'
		host.color = _IDENTITY_OK_COLOR


def _mqtt():
	return me.parent().op('mqtt_device')


def _project_key():
	"""Short stable hash of this project's absolute folder.

	Keyed on project.folder rather than just project.name so two
	different projects that happen to share a .toe filename (or two
	copies of one project run from separate machines/folders) never
	collide on the auto-generated device_id -- same keying choice
	Convoy's node identity (convoy_identity.py) makes for the same
	reason. Stable across restarts (important: device_id feeds a
	retained MQTT topic). Does NOT disambiguate two live processes
	launched from the literal same project folder at once -- that
	degenerate case still needs an explicit Deviceid per instance.
	"""
	try:
		folder = str(project.folder)
	except Exception:
		folder = ""
	return hashlib.sha1(folder.encode('utf-8')).hexdigest()[:6]


def _read_config():
	host = me.parent()

	def par(name, default):
		try:
			v = host.par[name].eval()
			return v if v not in (None, "") else default
		except Exception:
			return default

	default_id = f"td-{project.name.removesuffix('.toe')}-{_project_key()}"
	return {
		"device_id": par("Deviceid", default_id),
		"stanza":    par("Stanza", "unknown"),
		"name":      par("Name", project.name),
		"family":    par("Family", "").strip().lower(),
	}


def _service_status(name):
	fn = _services.get(name, {}).get("status")
	if not fn:
		return "unknown"
	try:
		return "active" if fn() else "inactive"
	except Exception as e:
		_record_error(f"status({name})", e)
		return "unknown"


def _param_value(name):
	fn = _params.get(name, {}).get("get")
	if not fn:
		return None
	try:
		return fn()
	except Exception as e:
		_record_error(f"get({name})", e)
		return None


def _capabilities():
	"""Derived from what is ACTUALLY registered (register_service), never
	assumed -- a project without dmx_out must not claim dmx."""
	return {
		"display": True,   # always true: a TD instance is by definition a visual layer
		"dmx":     "dmx_out" in _services,
		"mocap":   "mocap_bridge" in _services,
	}


def _publish_status():
	global _perf_dropped_window
	dat = _mqtt()
	if dat is None or not dat.isConnected:
		return
	cfg = _read_config()
	payload = {
		"device_id":      cfg["device_id"],
		"name":           cfg["name"],
		"stanza":         cfg["stanza"],
		"family":         cfg["family"],
		"role":           "touchdesigner",
		"ip":             _get_ip(),
		"tailscale_ip":   _ts_ip_cache,
		"internet":       _internet_cache,
		"sw_version":     SW_VERSION,
		"services":       {n: _service_status(n) for n in _services},
		"params":         {n: _param_value(n) for n in _params},
		"uptime":         int(time.time() - _START_TS),
		"last_error":     _last_error,
		"fps":            _measured_fps(),
		"target_fps":     _target_fps(),
		"dropped_frames": _perf_dropped_window,
		"ts":             int(time.time() * 1000),
	}
	dat.publish(f"gaia/device/{cfg['device_id']}/status", json.dumps(payload).encode('utf-8'), retain=True)
	_publish_profile(dat, cfg)
	_perf_dropped_window = 0


def _publish_profile(dat, cfg):
	"""Retained semantic profile."""
	profile = {
		"device_id":    cfg["device_id"],
		"role":         "touchdesigner",
		"family":       cfg["family"],
		"room":         cfg["stanza"],
		"ip":           _get_ip(),
		"tailscale_ip": _ts_ip_cache,
		"internet":     _internet_cache,
		"capabilities": _capabilities(),
		"services":     {n: _service_status(n) for n in _services},
		"sw_version":   SW_VERSION,
		"ts":           int(time.time() * 1000),
	}
	dat.publish(f"gaia/devices/{cfg['device_id']}/profile", json.dumps(profile).encode('utf-8'), retain=True)


def _apply_command(cmd):
	if not _enabled():
		print(f"[GAIA Agent] Device Status disabled, command ignored: {cmd}")
		return

	action  = cmd.get("action", "")
	service = cmd.get("service", "")
	param   = cmd.get("param", "")
	svc = _services.get(service)
	prm = _params.get(param)
	print(f"[GAIA Agent] Command: {cmd}")

	def _run(fn, label):
		global _last_error
		try:
			fn()
			_last_error = None
		except Exception as e:
			_record_error(f"{label}({service or param})", e)

	if action == "reregister":
		# Remote recovery (GAIA_INTERFACE.md, Core 12 point 2, 2026-09-30):
		# same as the Re-register pulse inside TD, reachable from Admin with
		# {"action":"reregister"} -- no service/param field needed.
		_run(reregister, "reregister")
	elif action == "set":
		if not prm or not prm.get("set"):
			print(f"[GAIA Agent] Param '{param}' not registered or not writable")
		else:
			_run(lambda: prm["set"](cmd.get("value")), "set")
	elif action in ("enable", "disable", "restart") and not svc:
		print(f"[GAIA Agent] Service '{service}' not registered (register_service never called)")
	elif action == "enable" and svc.get("start"):
		_run(svc["start"], "start")
	elif action == "disable" and svc.get("stop"):
		_run(svc["stop"], "stop")
	elif action == "restart" and svc:
		if svc.get("stop"):
			_run(svc["stop"], "stop")
		if svc.get("start"):
			_run(svc["start"], "start")
	elif action == "status":
		pass
	else:
		print(f"[GAIA Agent] Action ignored: {action}")

	_publish_status()


def tick():
	"""Call from Execute DAT onFrameStart, EVERY FRAME -- heartbeat
	throttled internally to _HEARTBEAT_S, no separate thread needed."""
	global _last_heartbeat
	if not _enabled():
		return
	now = time.time()
	if (now - _last_heartbeat) < _HEARTBEAT_S:
		return
	_last_heartbeat = now
	_publish_status()


# ---- Called from mqtt_device_callbacks -- already on the main thread
# (native Callbacks DAT dispatch). -----------------------------------------

def _publish_announce(dat, cfg):
	"""Handshake with the Node-RED Device Registry."""
	announce = {
		"device_id":  cfg["device_id"],
		"type":       "touchdesigner",
		"ip":         _get_ip(),
		"room_claim": cfg["stanza"],
		"ts":         int(time.time() * 1000),
	}
	dat.publish(f"gaia/devices/{cfg['device_id']}/announce", json.dumps(announce).encode('utf-8'))


def on_connect(dat):
	cfg = _read_config()
	dat.subscribe(f"gaia/device/{cfg['device_id']}/command")
	dat.subscribe("gaia/device/all/command")
	dat.subscribe(f"gaia/devices/{cfg['device_id']}/config")
	print(f"[GAIA Agent] Connected -- device_id: {cfg['device_id']}")
	me.parent().par.Deviceagentstatus = 'connected'
	_publish_status()
	_publish_announce(dat, cfg)


def on_connect_failure(msg):
	print(f"[GAIA Agent] MQTT connection failed: {msg}")
	me.parent().par.Deviceagentstatus = 'connect failed: %s' % msg


def on_connection_lost(msg):
	print(f"[GAIA Agent] Disconnected: {msg}")
	me.parent().par.Deviceagentstatus = 'connection lost: %s' % msg


def on_message(topic, payload):
	if isinstance(payload, bytes):
		payload = payload.decode('utf-8', errors='replace')
	try:
		d = json.loads(payload)
	except Exception as e:
		print(f"[GAIA Agent] Invalid message: {e}")
		return
	if topic.endswith('/config'):
		# Authoritative Device Registry response (retained) -- log only, does
		# NOT silently overwrite Stanza: that's an artist-chosen parameter on
		# this component, not something to change behind their back.
		print(f"[GAIA Agent] Config from Device Registry: {d}")
		return
	_apply_command(d)
