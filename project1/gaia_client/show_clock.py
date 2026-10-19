"""
show_clock -- ONE show clock shared by every Gaia device (DMX Master,
PatchDeck, Controller, Plancia...). Part of the portable gaia_client: this
file stays identical across projects, the timeline it publishes is
project-specific and handed in with register_source().

Roles (Clockrole par on gaia_client):
  off       nothing published, nothing subscribed
  master    publishes the state of the registered timeline, answers pings,
            applies commands from anyone (one master per show: DMX Master)
  follower  reads the master's state and computes the show position
            locally, every frame, without per-frame network traffic

Topics (same broker / mqtt_device client as the device agent):
  gaia/show/clock/state         retained, master -> all. Sent on every
                                change (play/pause/seek/cue/loop/length)
                                and once per second as heartbeat
  gaia/show/clock/command       anyone -> master
                                {"action": "play"|"pause"|"toggle"|"stop"|
                                 "seek"|"go"|"back"|"cue", "value": ...}
                                seek value = seconds; cue value = cue
                                number (1-based); play value 0/1 optional
  gaia/show/clock/ping          follower -> master {"from": id, "n": k, "t0": ms}
  gaia/show/clock/pong/<from>   master -> follower, the ping payload echoed

State payload:
  {"v": 1, "master": device_id, "seq": n, "sent_ms": epoch ms (info only),
   "playing": bool, "pos": s, "rate": 1.0, "length": s, "loop": bool,
   "active": bool, "timeline": name,
   "cue": {"index": 1-based (0 = before the first cue), "count": n,
           "label": str, "scene": str, "time": s}}

Why state and not ticks: a follower never needs the clock to stream. It
anchors the last state on its OWN monotonic clock and extrapolates:
  pos_now = pos + (now - received + latency) * rate      (if playing)
latency = half the smallest ping round trip seen (follower -> broker ->
master -> broker -> follower), so no wall-clock (NTP/w32time) sync is
needed between machines. Precision ~1 frame of the master + LAN jitter.

The master registers its timeline once (re-arm it periodically: this
module's state is wiped on every hot-reload of this file):
    clock = op.Gaia.op('show_clock').module
    clock.register_source(state=fn() -> dict, command=fn(action, value) -> str)
state() returns the fields above minus v/master/seq/sent_ms; command()
applies one action and returns a status line (raise ValueError to refuse).
A follower project can read position() / state() or
register_listener(fn(state)) to react to every new state.

All entry points run on TD's main thread (Execute DAT / mqttclientDAT
callbacks), so touching pars here is safe.
"""
import json
import time

TOPIC = 'gaia/show/clock'
HEARTBEAT_S = 1.0          # master: state at least once per second
JUMP_S = 0.1               # master: republish when pos leaves the prediction
PING_S = 2.0               # follower: ping period
PING_KEEP = 10             # follower: round trips kept for the min filter
STALE_S = 3.5              # follower: no state for this long -> master lost
STATUS_S = 0.25            # Clockstatus refresh period

_source = {}               # {'state': fn, 'command': fn}
_listeners = []
_sub = {'dat': None, 'role': None}   # what is subscribed, on which client
_m = {'seq': 0, 'last': None, 'mono': 0.0, 'pub': 0.0, 'dirty': True, 'other': None}
_f = {'state': None, 'recv': 0.0, 'rtts': [], 'n': 0, 'ping': 0.0, 'sent': {}}
_status = {'t': 0.0, 'text': None}


def _host():
	return me.parent()


def _mqtt():
	return _host().op('mqtt_device')


def _device_id():
	return _host().op('gaia_device_agent').module._read_config()['device_id']


def role():
	try:
		return str(_host().par.Clockrole.eval())
	except Exception:
		return 'off'


def _now():
	return time.perf_counter()   # monotonic() ticks at ~16 ms on Windows


def _publish(topic, payload, retain=False):
	dat = _mqtt()
	if dat is None or not dat.isConnected:
		return False
	dat.publish(topic, json.dumps(payload).encode('utf-8'), retain=retain)
	return True


# ---------------------------------------------------------------- API

def register_source(state, command=None):
	"""Master side: the timeline this device publishes."""
	_source.clear()
	_source.update(state=state, command=command)
	_m['dirty'] = True


def has_source():
	return bool(_source)


def register_listener(fn):
	"""Follower side: fn(state) on every new state from the master."""
	if fn not in _listeners:
		_listeners.append(fn)


def latency():
	"""One-way master -> this device delay in seconds (0 until measured)."""
	return min(_f['rtts']) / 2.0 if _f['rtts'] else 0.0


def state():
	"""Last state: the local one on the master, the received one on a
	follower (None if nothing yet)."""
	return _m['last'] if role() == 'master' else _f['state']


def position():
	"""Show position in seconds right now."""
	if role() == 'master':
		st = _m['last']
		return float(st['pos']) if st else 0.0
	st = _f['state']
	if not st:
		return 0.0
	pos = float(st.get('pos', 0.0))
	if st.get('playing') and not stale():
		pos += (_now() - _f['recv'] + latency()) * float(st.get('rate', 1.0))
		length = float(st.get('length') or 0.0)
		if length > 0:
			pos = pos % length if st.get('loop') else min(pos, length)
	return pos


def stale():
	return _f['state'] is None or (_now() - _f['recv']) > STALE_S


def command(action, value=None):
	"""Send a transport command to the master (any role, also from the
	master itself: then it is applied directly)."""
	if role() == 'master':
		return _apply_command({'action': action, 'value': value})
	_publish(TOPIC + '/command', {'action': action, 'value': value, 'from': _device_id()})
	return 'inviato %s' % action


# ---------------------------------------------------------------- mqtt

def on_connect(dat):
	"""From gaia_device_agent.on_connect: (re)subscribe after a reconnect."""
	_sub['dat'] = None
	_ensure_subscribed(dat)


def _ensure_subscribed(dat=None):
	dat = dat or _mqtt()
	r = role()
	if dat is None or not dat.isConnected or r == 'off':
		return
	if _sub['dat'] is dat and _sub['role'] == r:
		return
	if r == 'master':
		dat.subscribe(TOPIC + '/command')
		dat.subscribe(TOPIC + '/ping')
		dat.subscribe(TOPIC + '/state')
		_m['dirty'] = True
	else:
		dat.subscribe(TOPIC + '/state')
		dat.subscribe(TOPIC + '/pong/' + _device_id())
		_f['ping'] = 0.0
	_sub.update(dat=dat, role=r)


def on_message(topic, payload):
	"""From gaia_device_agent.on_message for every gaia/show/clock/* topic."""
	r = role()
	if r == 'off':
		return
	try:
		d = json.loads(payload)
	except Exception:
		return
	if not isinstance(d, dict):
		return
	sub = topic[len(TOPIC) + 1:]
	if r == 'master':
		if sub == 'ping' and d.get('from'):
			_publish(TOPIC + '/pong/' + str(d['from']), d)
		elif sub == 'command':
			_apply_command(d)
		elif sub == 'state' and d.get('master') not in (None, _device_id()):
			_m['other'] = str(d.get('master'))
		return
	if sub == 'state':
		_f['state'] = d
		_f['recv'] = _now()
		for fn in list(_listeners):
			try:
				fn(d)
			except Exception as e:
				debug('show_clock listener: %s' % e)
	elif sub.startswith('pong/'):
		t0 = _f['sent'].pop(d.get('n'), None)
		if t0 is not None:
			_f['rtts'] = (_f['rtts'] + [_now() - t0])[-PING_KEEP:]


def _apply_command(d):
	fn = _source.get('command')
	action = str(d.get('action', '')).strip().lower()
	if fn is None:
		msg = 'comando %s: nessuna timeline registrata' % action
	else:
		try:
			msg = fn(action, d.get('value')) or action
		except Exception as e:
			msg = 'comando %s rifiutato: %s' % (action, e)
	_m['dirty'] = True
	_set_status(msg, force=True)
	return msg


# ---------------------------------------------------------------- tick

def tick():
	"""Every frame, from agent_lifecycle onFrameStart."""
	r = role()
	if r != _sub['role']:
		_sub['dat'] = None
		_f.update(state=None, rtts=[], sent={})
		_m.update(last=None, other=None, dirty=True)
		if r == 'off':
			_sub['role'] = 'off'
			_set_status('spento', force=True)
	if r == 'off':
		return
	_ensure_subscribed()
	if r == 'master':
		_master_tick()
	else:
		_follower_tick()


def _master_tick():
	fn = _source.get('state')
	if fn is None:
		_set_status('master: nessuna timeline registrata')
		return
	try:
		st = dict(fn())
	except Exception as e:
		_set_status('master: errore timeline %s' % e)
		return
	now = _now()
	last = _m['last']
	send = _m['dirty'] or last is None or (now - _m['pub']) >= HEARTBEAT_S
	if not send:
		keys = ('playing', 'loop', 'length', 'rate', 'active', 'timeline')
		send = any(st.get(k) != last.get(k) for k in keys) or \
			(st.get('cue') or {}).get('index') != (last.get('cue') or {}).get('index')
	if not send:
		pred = float(last['pos'])
		if last.get('playing'):
			pred += (now - _m['mono']) * float(last.get('rate', 1.0))
		send = abs(float(st.get('pos', 0.0)) - pred) > JUMP_S
	if send:
		_m['seq'] += 1
		st.update(v=1, master=_device_id(), seq=_m['seq'], sent_ms=int(time.time() * 1000))
		if _publish(TOPIC + '/state', st, retain=True):
			_m.update(last=st, mono=now, pub=now, dirty=False)
	if _m['other']:
		_set_status('ATTENZIONE: anche %s pubblica come master' % _m['other'])
	else:
		_set_status('master %s %s  seq %d' % ('PLAY' if st.get('playing') else 'STOP',
			_fmt(st.get('pos', 0.0)), _m['seq']))


def _follower_tick():
	now = _now()
	if (now - _f['ping']) >= PING_S or (len(_f['rtts']) < 3 and (now - _f['ping']) >= 0.2):
		_f['ping'] = now
		_f['n'] += 1
		_f['sent'] = {k: v for k, v in _f['sent'].items() if now - v < 10.0}
		if _publish(TOPIC + '/ping', {'from': _device_id(), 'n': _f['n'], 't0': int(time.time() * 1000)}):
			_f['sent'][_f['n']] = now
	st = _f['state']
	if st is None:
		_set_status('follower: nessun master')
	elif stale():
		_set_status('follower: master %s muto da %.0fs' % (st.get('master'), now - _f['recv']))
	else:
		_set_status('follower di %s %s %s  lat %.0f ms' % (st.get('master'),
			'PLAY' if st.get('playing') else 'STOP', _fmt(position()), latency() * 1000))


def _fmt(t):
	m, s = divmod(float(t), 60)
	return '%02d:%05.2f' % (m, s)


def _set_status(text, force=False):
	now = _now()
	if not force and (now - _status['t']) < STATUS_S:
		return
	_status['t'] = now
	if text == _status['text']:
		return
	_status['text'] = text
	try:
		_host().par.Clockstatus = text
	except Exception:
		pass
