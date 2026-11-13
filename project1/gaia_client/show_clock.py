"""
show_clock -- ONE show clock shared by every Gaia device (DMX Master,
PatchDeck, Controller, Plancia...). Part of the portable gaia_client: this
file stays identical across projects, the timeline it publishes is
project-specific and handed in with register_source().

Roles (Clockrole par on gaia_client):
  off       nothing published, nothing subscribed
  master    publishes the state of the registered timeline, answers pings,
            applies commands from anyone. Since 1.5 a master is also the
            STANDBY of a higher-priority master (the Gaia audio engine on
            OPS, "prio": 2, see audio-engine/src/clock.rs): while that one
            is alive this device follows it (its timeline is driven by the
            clock, see register_source(follow=...)); when it goes silent
            for STALE_S this device takes over from where it is.
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
  gaia/show/clock/timeline      retained, from the device owning the cues
                                (register_source(timeline=...)), on change
                                and every TIMELINE_S: {"v": 1, "from": id,
                                "timeline", "name", "bpm", "length", "loop",
                                "active", "cues": [{"time", "label",
                                "scene", "fade"}]}. A master that is not a
                                timeline (the audio engine) takes length,
                                loop, active and cues from here.

State payload:
  {"v": 1, "master": device_id, "prio": 1|2, "kind": "td"|"audio",
   "seq": n, "sent_ms": epoch ms (info only),
   "playing": bool, "pos": s, "rate": 1.0, "length": s, "loop": bool,
   "active": bool, "timeline": name,
   "cue": {"index": 1-based (0 = before the first cue), "count": n,
           "label": str, "scene": str, "time": s},
   "cmd": {"seq": n, "action": str, "cue": {...}}   (audio master only:
           last command applied, so a standby timeline can do the local
           part of go/back/cue, e.g. recall the scene when not Active)}

Why state and not ticks: a follower never needs the clock to stream. It
anchors the last state on its OWN monotonic clock and extrapolates:
  pos_now = pos + (now - received + latency) * rate      (if playing)
latency = half the smallest ping round trip seen (follower -> broker ->
master -> broker -> follower), so no wall-clock (NTP/w32time) sync is
needed between machines.
TD hands MQTT messages over once per frame, so every state and pong is
processed up to a frame late (1.5): the round trip is taken minus one frame
period, and position() keeps the best of the recent states (a late one only
predicts a smaller position, never a larger one). Precision: a few ms.
Flywheel (1.5): when the master goes silent a follower keeps
extrapolating for FLYWHEEL_S, so the show goes on; the next state realigns.

A higher-priority master counts as alive only after two different seq
from it: the retained state replayed by the broker at connect (maybe hours
old) must not drive the timeline.

The master registers its timeline once (re-arm it periodically: this
module's state is wiped on every hot-reload of this file):
    clock = op.Gaia.op('show_clock').module
    clock.register_source(state=fn() -> dict, command=fn(action, value) -> str,
                          timeline=fn() -> dict, follow=fn(st, pos, cmd) -> None|(action, value))
state() returns the fields above minus v/master/seq/sent_ms; command()
applies one action and returns a status line (raise ValueError to refuse).
timeline() returns the timeline document above minus v/from. follow() is
called every frame while this device is the standby of a higher master:
drive the local timeline to pos (st = last state, cmd = the state's "cmd"
the first frame it is seen, else None) and return a command for the
master when the operator changed the timeline locally.
A follower project can read position() / state() or
register_listener(fn(state)) to react to every new state.

All entry points run on TD's main thread (Execute DAT / mqttclientDAT
callbacks), so touching pars here is safe.
"""
import json
import time

TOPIC = 'gaia/show/clock'
PRIO = 1                   # this device's master priority (audio engine = 2)
HEARTBEAT_S = 1.0          # master: state at least once per second
JUMP_S = 0.1               # master: republish when pos leaves the prediction
PING_S = 2.0               # follower: ping period
PING_KEEP = 10             # follower: round trips kept for the min filter
STALE_S = 3.5              # follower: no state for this long -> master lost
FLYWHEEL_S = 600.0         # follower: keep extrapolating this long without states
STARTUP_S = 2.5            # master: listen for a higher master before publishing
TIMELINE_S = 10.0          # timeline document: republished at least this often
TIMELINE_CHECK_S = 0.5     # timeline document: change check period
FOLLOW_JUMP_S = 0.25       # standby: farther than this from the clock = jump
STATUS_S = 0.25            # Clockstatus refresh period

_source = {}               # {'state': fn, 'command': fn, 'timeline': fn, 'follow': fn}
_listeners = []
_sub = {'dat': None, 'role': None, 't': 0.0}   # what is subscribed, on which client, since
_m = {'seq': 0, 'last': None, 'mono': 0.0, 'pub': 0.0, 'dirty': True, 'other': None,
	'standby': False}
_f = {'state': None, 'recv': 0.0, 'rtts': [], 'n': 0, 'ping': 0.0, 'sent': {},
	'anchors': [], 'frame': 1 / 60.0, 'tick': 0.0}
ANCHOR_S = 10.0            # follower: states kept for the best-anchor filter
ANCHOR_JUMP_S = 0.1        # a state this far from the prediction = seek / new segment
_hi = {'master': None, 'seqs': set(), 'cmd': None}   # higher master seen live
_tl = {'body': None, 'pub': 0.0, 'check': 0.0}
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

def register_source(state, command=None, timeline=None, follow=None):
	"""Master side: the timeline this device publishes (and drives from a
	higher master while standing by)."""
	_source.clear()
	_source.update(state=state, command=command, timeline=timeline, follow=follow)
	_m['dirty'] = True
	_tl['body'] = None


def has_source():
	return bool(_source)


def register_listener(fn):
	"""Follower side: fn(state) on every new state from the master."""
	if fn not in _listeners:
		_listeners.append(fn)


def latency():
	"""One-way master -> this device delay in seconds (0 until measured).
	The pong waits for the next frame before TD hands it over: one frame
	period is taken off the round trip."""
	if not _f['rtts']:
		return 0.0
	return max(0.0005, (min(_f['rtts']) - _f['frame']) / 2.0)


def _predict(st, recv, now):
	pos = float(st.get('pos', 0.0))
	if st.get('playing'):
		pos += (now - recv + latency()) * float(st.get('rate', 1.0))
	return pos


def _prio(st):
	try:
		return int((st or {}).get('prio') or 1)
	except Exception:
		return 1


def standby():
	"""True while this master follows a higher-priority master."""
	return role() == 'master' and _m['standby']


def _higher_alive():
	st = _f['state']
	return st is not None and _prio(st) > PRIO and len(_hi['seqs']) >= 2 and \
		(_now() - _f['recv']) <= STALE_S


def following():
	"""True when position() comes from another master."""
	return role() == 'follower' or standby()


def state():
	"""Last state: the local one on the master, the received one on a
	follower or standby (None if nothing yet)."""
	return _f['state'] if following() else _m['last']


def position():
	"""Show position in seconds right now."""
	if not following():
		st = _m['last']
		return float(st['pos']) if st else 0.0
	st = _f['state']
	if not st:
		return 0.0
	now = _now()
	pos = float(st.get('pos', 0.0))
	if st.get('playing') and (now - _f['recv']) <= FLYWHEEL_S:
		pos = max(_predict(a, r, now) for r, a in _f['anchors']) if _f['anchors'] else _predict(st, _f['recv'], now)
		length = float(st.get('length') or 0.0)
		if length > 0:
			pos = pos % length if st.get('loop') else min(pos, length)
	return pos


def stale():
	return _f['state'] is None or (_now() - _f['recv']) > STALE_S


def command(action, value=None):
	"""Send a transport command to the master (any role, also from the
	master itself: then it is applied directly)."""
	if role() == 'master' and not standby():
		return _apply_command({'action': action, 'value': value})
	_publish(TOPIC + '/command', {'action': action, 'value': value, 'from': _device_id()})
	return 'inviato %s' % action


# ---------------------------------------------------------------- mqtt

def on_connect(dat):
	"""From gaia_device_agent.on_connect: (re)subscribe after a reconnect."""
	_sub['dat'] = None
	_tl['body'] = None
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
		dat.subscribe(TOPIC + '/pong/' + _device_id())
		_m['dirty'] = True
	else:
		dat.subscribe(TOPIC + '/state')
		dat.subscribe(TOPIC + '/pong/' + _device_id())
	_f['ping'] = 0.0
	_sub.update(dat=dat, role=r, t=_now())


def _take_state(d):
	now = _now()
	keep = []
	if d.get('playing') and _f['anchors']:
		r0, a0 = _f['anchors'][-1]
		same = a0.get('master') == d.get('master') and a0.get('rate') == d.get('rate') and a0.get('playing')
		if same and abs(_predict(a0, r0, now) - _predict(d, now, now)) <= ANCHOR_JUMP_S:
			keep = [(r, a) for r, a in _f['anchors'] if now - r <= ANCHOR_S]
	_f['anchors'] = keep + [(now, d)] if d.get('playing') else []
	_f['state'] = d
	_f['recv'] = now
	for fn in list(_listeners):
		try:
			fn(d)
		except Exception as e:
			debug('show_clock listener: %s' % e)


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
	if sub.startswith('pong/'):
		t0 = _f['sent'].pop(d.get('n'), None)
		if t0 is not None:
			_f['rtts'] = (_f['rtts'] + [_now() - t0])[-PING_KEEP:]
		return
	if r == 'master':
		if sub == 'ping' and d.get('from'):
			if not _m['standby']:
				_publish(TOPIC + '/pong/' + str(d['from']), d)
		elif sub == 'command':
			if not _m['standby']:
				_apply_command(d)
		elif sub == 'state' and d.get('master') not in (None, _device_id()):
			if _prio(d) > PRIO:
				if _hi['master'] != d.get('master'):
					_hi.update(master=d.get('master'), seqs=set())
				_hi['seqs'] = set(list(_hi['seqs'])[-3:]) | {d.get('seq')}
				_take_state(d)
			else:
				_m['other'] = str(d.get('master'))
		return
	if sub == 'state':
		_take_state(d)


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
	now = _now()
	if _f['tick']:
		_f['frame'] += 0.05 * (min(0.25, now - _f['tick']) - _f['frame'])
	_f['tick'] = now
	r = role()
	if r != _sub['role']:
		_sub['dat'] = None
		_f.update(state=None, rtts=[], sent={}, anchors=[])
		_m.update(last=None, other=None, dirty=True, standby=False)
		_hi.update(master=None, seqs=set(), cmd=None)
		if r == 'off':
			_sub['role'] = 'off'
			_set_status('spento', force=True)
	if r == 'off':
		return
	_ensure_subscribed()
	if r == 'master':
		hi = _higher_alive()
		if hi != _m['standby']:
			_m['standby'] = hi
			if hi:
				_set_status('riserva: segue %s' % _hi['master'], force=True)
			else:
				# the higher master went silent: from here on this device is
				# the clock again, from the position its timeline holds now
				_m['dirty'] = True
				_hi.update(master=None, seqs=set())
				debug('show_clock: %s muto, riprendo come master' % (_f['state'] or {}).get('master'))
		if hi:
			_ping_tick()
			_follow_tick()
		else:
			_master_tick()
		_timeline_tick()
	else:
		_ping_tick()
		_follower_tick()


def _master_tick():
	if (_now() - _sub['t']) < STARTUP_S:
		_set_status('master: in ascolto di un orologio superiore')
		return
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
		st.update(v=1, master=_device_id(), prio=PRIO, kind='td', seq=_m['seq'],
			sent_ms=int(time.time() * 1000))
		if _publish(TOPIC + '/state', st, retain=True):
			_m.update(last=st, mono=now, pub=now, dirty=False)
	if _m['other']:
		_set_status('ATTENZIONE: anche %s pubblica come master' % _m['other'])
	else:
		_set_status('master %s %s  seq %d' % ('PLAY' if st.get('playing') else 'STOP',
			_fmt(st.get('pos', 0.0)), _m['seq']))


def _follow_tick():
	"""Standby: drive the local timeline from the higher master."""
	st = _f['state']
	fn = _source.get('follow')
	if fn is not None and st is not None:
		cmd = st.get('cmd') if isinstance(st.get('cmd'), dict) else None
		new_cmd = cmd if cmd and cmd.get('seq') != _hi['cmd'] else None
		if cmd:
			_hi['cmd'] = cmd.get('seq')
		try:
			out = fn(st, position(), new_cmd)
		except Exception as e:
			out = None
			_set_status('riserva: errore timeline %s' % e)
		if out:
			action, value = out
			_publish(TOPIC + '/command', {'action': action, 'value': value, 'from': _device_id()})
	_set_status('riserva di %s %s %s  lat %.0f ms' % (_hi['master'],
		'PLAY' if (st or {}).get('playing') else 'STOP', _fmt(position()), latency() * 1000))


def _timeline_tick():
	"""Publish the timeline document (cues, length, loop) when it changes."""
	fn = _source.get('timeline')
	now = _now()
	if fn is None or (now - _tl['check']) < TIMELINE_CHECK_S:
		return
	_tl['check'] = now
	try:
		doc = dict(fn())
	except Exception as e:
		debug('show_clock timeline: %s' % e)
		return
	body = json.dumps(doc, sort_keys=True)
	if body == _tl['body'] and (now - _tl['pub']) < TIMELINE_S:
		return
	doc.update(v=1, **{'from': _device_id()})
	if _publish(TOPIC + '/timeline', doc, retain=True):
		_tl.update(body=body, pub=now)


def _ping_tick():
	now = _now()
	if (now - _f['ping']) >= PING_S or (len(_f['rtts']) < 3 and (now - _f['ping']) >= 0.2):
		_f['ping'] = now
		_f['n'] += 1
		_f['sent'] = {k: v for k, v in _f['sent'].items() if now - v < 10.0}
		if _publish(TOPIC + '/ping', {'from': _device_id(), 'n': _f['n'], 't0': int(time.time() * 1000)}):
			_f['sent'][_f['n']] = now


def _follower_tick():
	now = _now()
	st = _f['state']
	if st is None:
		_set_status('follower: nessun master')
	elif stale():
		_set_status('follower: master %s muto da %.0fs, vado avanti da solo %s' % (
			st.get('master'), now - _f['recv'], _fmt(position())))
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
