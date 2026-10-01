"""Touch sender discovery -- which Gaia devices are publishing audio over a
Touch Out CHOP right now (GAIA_INTERFACE.md "TD/Mac-Ctrl, 2"):

  device D is a sender of service S (touch_audio = raw audio, family A;
  touch_bands = analyzed bands, family B) when its gaia/device/D/status has
  services[S] == "active" and params[S + "_port"]. Address = status ip
  (tailscale_ip only when ip is missing). A sender expires 90 s after its
  last status, or at once when services[S] stops being "active".

Fed by mqtt_discovery (own MQTT client, client_id <Deviceid>-discovery, so
gaia_client stays the unmodified portable .tox). Results go to the tables
touch_senders_touch_audio / touch_senders_touch_bands, read by the audio
engine sources (Sender menu + Touch In address/port). No IP or port is ever
typed by hand.
"""
import json
import time

SERVICES = ('touch_audio', 'touch_bands')
TTL_S = 90.0
COLUMNS = ['device_id', 'label', 'ip', 'tailscale_ip', 'port', 'name', 'stanza', 'family', 'last_seen']

_senders = {s: {} for s in SERVICES}   # service -> device_id -> info
_dirty = True
_last_sweep = 0.0


def get_service_providers(service):
	"""device_id -> {ip, tailscale_ip, port, name, stanza, family, last_seen}"""
	return {k: dict(v) for k, v in _senders.get(service, {}).items()}


def on_connect(dat):
	dat.subscribe('gaia/device/+/status')


def on_message(topic, payload):
	global _dirty
	if isinstance(payload, bytes):
		payload = payload.decode('utf-8', errors='replace')
	try:
		d = json.loads(payload)
	except Exception:
		return
	device_id = d.get('device_id')
	if not device_id or device_id == op.Gaia.par.Deviceid.eval():
		return
	services = d.get('services') or {}
	params = d.get('params') or {}
	now = time.time()
	for s in SERVICES:
		port = params.get(s + '_port')
		ip = d.get('ip') or d.get('tailscale_ip')
		if services.get(s) == 'active' and port and ip:
			info = {'ip': ip, 'tailscale_ip': d.get('tailscale_ip') or '', 'port': int(port),
				'name': d.get('name') or '', 'stanza': d.get('stanza') or '',
				'family': d.get('family') or '', 'last_seen': now}
			old = _senders[s].get(device_id)
			if old is None or any(old[k] != info[k] for k in ('ip', 'port', 'stanza', 'name')):
				_dirty = True
			_senders[s][device_id] = info
		elif device_id in _senders[s]:
			del _senders[s][device_id]
			_dirty = True


def tick():
	"""Every frame from gaia_services/lifecycle: TTL sweep (throttled) and
	table/menu refresh only when something changed."""
	global _dirty, _last_sweep
	now = time.time()
	if now - _last_sweep >= 5.0:
		_last_sweep = now
		for s in SERVICES:
			for k in [k for k, v in _senders[s].items() if now - v['last_seen'] > TTL_S]:
				del _senders[s][k]
				_dirty = True
	if not _dirty:
		return
	_dirty = False
	_write_tables()
	_autoselect()
	svc = op('dmx_services')
	if svc is not None:
		try:
			svc.module.publish_matrix()   # audio_<x>_sender options changed
		except Exception as e:
			debug('publish_matrix after sender change failed:', e)


def _write_tables():
	for s in SERVICES:
		t = op('touch_senders_' + s)
		rows = [COLUMNS]
		for dev in sorted(_senders[s]):
			v = _senders[s][dev]
			label = '%s%s - %s:%d' % (dev, (' (%s)' % v['stanza']) if v['stanza'] else '', v['ip'], v['port'])
			rows.append([dev, label, v['ip'], v['tailscale_ip'], v['port'], v['name'], v['stanza'], v['family'],
				time.strftime('%H:%M:%S', time.localtime(v['last_seen']))])
		t.clear()
		for r in rows:
			t.appendRow(r)


def _autoselect():
	"""A source set to a Touch type with no valid Sender picks the only
	sender available (never overrides a valid manual choice)."""
	eng = me.parent().parent().op('audio_engine')
	if eng is None:
		return
	for src in (eng.op('source_a'), eng.op('source_b')):
		if src is None:
			continue
		s = str(src.par.Type.eval())
		if s not in SERVICES:
			continue
		if str(src.par.Sender.eval()) in _senders[s]:
			continue
		if len(_senders[s]) == 1:
			src.par.Sender = next(iter(_senders[s]))
