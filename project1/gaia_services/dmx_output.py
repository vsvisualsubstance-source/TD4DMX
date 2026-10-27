"""dmx_output -- what DMX Master is ACTUALLY sending, per fixture, for
Plancia's Render and any UI (GAIA_INTERFACE "TD/Win-PD, 28").

Source of truth: dmx_patch/universe_build, the 512 channels per universe
exactly as they go out (palette, effects, group Level, Master, Strobe and
Blackout already applied), read at each fixture's start address with the
channel names of its profile (dmx_patch/fixture_logic.profile_channels).
Nothing is inferred from palette names.

Topic gaia/devices/<device_id>/dmx_output, retained, QoS 0:
  {"v": 1, "device_id", "seq", "ts" (epoch ms, TD clock), "rate_hz",
   "master" 0-1, "blackout", "strobe", "scene": show_logic.active_scene(),
   "fixtures": [{"uid", "id", "name", "group", "comp", "profile",
     "universe" (1-based, as Plancia), "address", "status" (patch_report:
     ok | offline | conflict = sent; off | no_port | ... = NOT sent),
     "sent" bool,
     "dimmer" 0-255 | null, "rgb" [r, g, b] 0-255 | null (raw colour
     channels), "white", "amber", "uv" 0-255 | null,
     "intensity" 0-1 (dimmer; without one: the brightest colour, or the
     white channel), "rgb_out" [r, g, b] 0-1 = the colour as seen,
     "color_source" = how it is made (dmx_patch/catalog_logic
     beam_color, from the model's roles and colour slots): rgb (red
     green blue + white/amber/lime/uv) | cmy | wheel | cmy+wheel | lamp
     (no colour mixing: the model's 'beam' colour, white by default) |
     unknown (a wheel whose slots have no colour: white) | null = no
     light (haze: rgb_out null, intensity = output),
     heads only: "color_wheel", "gobo", "shutter" 0-255, "pan", "tilt"
     in degrees and "zoom", "focus" 0-1 from the head programmer,
     chase rigs only: "audio" (full | off | bass | mid | high | kick) and
     "audio_gain" 0..2, the light's own audio settings (patch)}],
   "rigs": {<chase group>: {"level" 0-1 (the rig's audio level, normalised
     on the track), "kicks" (kick counter: +1 per detected kick, compare
     with the previous message), "amount" 0-1 (Audio Amount),
     "kick_enable"}}}   ("TD/Win-PD, 45")
A fixture that is not sent has every output field null.

Published when an output value changes, at most Outputrate times per second,
and at least every HEARTBEAT_S (ts refreshed) so a UI can call it stale when
nothing arrives for 3 heartbeats (measure the gap on arrival, do not
compare ts with the UI's clock). Strobe: the gate is sampled at the
publishing rate, so "strobe": true says the values are flickering.

Rig meter, faster: topic gaia/devices/<device_id>/dmx_rigs, NOT retained,
QoS 0: {"v": 1, "device_id", "seq", "ts", "rate_hz", "rigs": {...same
as above}}, on change at most RIGS_HZ times per second and at least every
HEARTBEAT_S. Only the generators' debug channels are read (no snapshot),
so the level bar and the kick flash run smoother than dmx_output.
"rigs" stays in dmx_output too, for UIs that have not moved yet.

v2, the same data split in two retained topics (QoS 0), so the fast one
carries only values:
  gaia/devices/<device_id>/dmx_layout: {"v": 2, "device_id", "rev", "ts",
    "fixtures": [{"uid", + LAYOUT_KEYS}]}, when it changes (rev = hash of
    the content) and every LAYOUT_REFRESH_S.
  gaia/devices/<device_id>/dmx_live: {"v": 2, "device_id", "seq", "ts",
    "rate_hz", "layout_rev", "master", "blackout", "strobe", "scene",
    "fixtures": {<uid>: {output fields of v1, null ones LEFT OUT}}}, on
    change at most Outputrate per second, at least every HEARTBEAT_S. A
    missing field = null in v1; a layout_rev different from the last
    dmx_layout rev = a dmx_layout is on its way.
  The rig meter is only on dmx_rigs. OUTPUT_V1 = False turns dmx_output
  off (off since "OPS, 31": the Plancia reads v2 and dmx_rigs).

tick() from gaia_services/lifecycle onFrameStart; pars Outputenable,
Outputrate, Outputstatus on gaia_services.
"""
import hashlib
import json
import time

HEARTBEAT_S = 2.0
RIGS_HZ = 30.0
OUTPUT_V1 = False
LAYOUT_REFRESH_S = 30.0
LAYOUT_KEYS = ('id', 'name', 'group', 'comp', 'profile', 'universe', 'address', 'status', 'sent',
	'color_source', 'audio', 'audio_gain')
_st = {'seq': 0, 'pub': 0.0, 'chk': 0.0, 'sig': None}
_rg = {'seq': 0, 'pub': 0.0, 'sig': None}
_v2 = {'seq': 0, 'pub': 0.0, 'sig': None, 'lsig': None, 'lpub': 0.0, 'rev': None}


def _home():
	return parent().parent()


def _round(v):
	return None if v is None else int(round(v))


def _fixture(r, rep, fl, ub, uids, heads, models, audio):
	g = rep[r, 'group'].val
	prof = rep[r, 'profile'].val
	status = rep[r, 'status'].val
	fid = int(rep[r, 'id'].val)
	uni = rep[r, 'universe'].val
	d = {'uid': uids.get(fid, ''), 'id': fid, 'name': rep[r, 'name'].val, 'group': g,
		'comp': rep[r, 'comp'].val, 'profile': prof,
		'universe': int(uni) + 1 if uni.strip().lstrip('-').isdigit() else None,
		'address': int(rep[r, 'start'].val or 0), 'status': status,
		'sent': status in ('ok', 'offline', 'conflict'),
		'dimmer': None, 'rgb': None, 'white': None, 'amber': None, 'uv': None,
		'intensity': None, 'rgb_out': None}
	if g == 'heads':
		d.update(color_wheel=None, gobo=None, shutter=None, pan=None, tilt=None)
	a = audio.get(fid)
	if a is not None:
		d['audio'], d['audio_gain'] = a
	chans = fl.profile_channels(g, prof) or []
	ch = None
	if d['sent']:
		cb = _home().op('dmx_patch/universe_build_callbacks').module
		ch = ub[cb.chan_name(rep[r, 'net'].val, rep[r, 'subnet'].val, uni, rep[r, 'ip'].val)]
	if ch is None:
		return d
	start = d['address'] - 1
	vals = {}
	for i, name in enumerate(chans):
		if 0 <= start + i < 512 and name not in vals:
			vals[name] = float(ch[start + i])
	dim = next((vals[c] for c in chans if c == 'dimmer'), None)
	if dim is None:
		dim = next((vals[c] for c in chans if c.startswith('dimmer')), None)
	d['dimmer'] = _round(dim)
	for k in ('white', 'amber', 'uv'):
		d[k] = _round(vals.get(k))
	m = models.get(prof) or {'channels': chans}
	beam, src = _cat().beam_color(m, vals)
	d['color_source'] = src
	dim01 = None if dim is None else dim / 255.0
	if src == 'rgb':
		d['rgb'] = [_round(vals[c]) for c in ('red', 'green', 'blue')]
		d['intensity'] = round(dim01 if dim01 is not None else max(beam), 3)
		d['rgb_out'] = [round(x * (dim01 if dim01 is not None else 1.0), 3) for x in beam]
	elif src:
		lvl = dim01 if dim01 is not None else float(vals.get('white', 255.0)) / 255.0
		d['intensity'] = round(lvl, 3)
		d['rgb_out'] = [round(x * lvl, 3) for x in beam]
	elif 'output' in vals:
		d['intensity'] = round(vals['output'] / 255.0, 3)
	if g == 'heads':
		d['color_wheel'] = _round(vals.get('color'))
		d['gobo'] = _round(vals.get('gobo'))
		d['shutter'] = _round(vals.get('shutter'))
		h = heads.get(fid)
		if h is not None:
			d['pan'], d['tilt'] = round(h['pan'], 1), round(h['tilt'], 1)
			d['zoom'], d['focus'] = round(h['zoom'], 3), round(h['focus'], 3)
	return d


def _cat():
	return _home().op('dmx_patch/catalog_logic').module


def snapshot():
	"""The payload without seq/ts (see the module doc)."""
	home = _home()
	patch = home.op('dmx_patch')
	rep = patch.op('patch_report')
	fl = patch.op('fixture_logic').module
	ub = patch.op('universe_build')
	uids = {f['id']: f['uid'] for f in fl.rows()}
	heads = {}
	hp_dat = home.op('moving_heads/head_programmer')
	if hp_dat is not None:
		hp = hp_dat.module
		by_unit = {h['unit']: h['key'] for h in hp.heads()}
		for f in fl.rows('heads'):
			key = by_unit.get(f['unit'])
			if key is not None:
				heads[f['id']] = hp.effective(key)
	models = {m['model']: m for m in _cat().models()}
	chase = [g for g in fl.groups() if g.get('kind') == 'chase' and g['comp']]
	chase_names = {g['group'] for g in chase}
	audio = {f['id']: (f['audio'] or 'full', 1.0 if f['audio_gain'] == '' else f['audio_gain'])
		for f in fl.rows() if f['group'] in chase_names}
	fixtures = [_fixture(r, rep, fl, ub, uids, heads, models, audio) for r in range(1, rep.numRows)]
	pp = patch.par
	sl = home.op('show/show_logic')
	return {'v': 1, 'master': round(float(pp.Master.eval()), 3), 'blackout': bool(pp.Blackout.eval()),
		'strobe': bool(pp.Strobe.eval()), 'scene': sl.module.active_scene() if sl is not None else None,
		'fixtures': fixtures, 'rigs': rigs(chase)}


def rigs(chase=None):
	"""{<chase group>: _rig_meter} for every chase rig (see the module doc)."""
	home = _home()
	if chase is None:
		fl = home.op('dmx_patch/fixture_logic').module
		chase = [g for g in fl.groups() if g.get('kind') == 'chase' and g['comp']]
	return {g['group']: _rig_meter(home.op(g['comp'])) for g in chase}


def _rig_meter(comp):
	"""Live audio of a chase rig, from its generator's debug channels."""
	gen = comp.op('dmx_generator') if comp is not None else None
	if gen is None:
		return None
	ch = lambda n: gen[n][0] if gen[n] is not None else None
	lvl, kicks = ch('debug_level_norm'), ch('debug_kicks')
	p = comp.par
	return {'level': None if lvl is None else round(float(lvl), 2),
		'kicks': None if kicks is None else int(kicks),
		'amount': round(float(p.Audioamount.eval()), 3) if hasattr(p, 'Audioamount') else 1.0,
		'kick_enable': bool(p.Kickenable.eval()) if hasattr(p, 'Kickenable') else None}


def tick():
	c = parent()
	if not c.par.Outputenable.eval():
		_st['sig'] = None
		_status('spento')
		return
	now = time.perf_counter()
	_tick_rigs(now)
	rate = max(0.5, float(c.par.Outputrate.eval()))
	# gate on the last check, not the last publish: an unchanged rig would
	# otherwise rebuild the snapshot every frame
	if now - _st['chk'] < 1.0 / rate - 0.008:
		return
	_st['chk'] = now
	try:
		snap = snapshot()
	except Exception as e:
		_status('errore: %s' % e)
		return
	g = op.Gaia
	dat = g.op('mqtt_device') if g is not None else None
	if dat is None or not dat.isConnected:
		_status('MQTT non connesso')
		return
	device_id = str(g.par.Deviceid.eval())
	ts = int(time.time() * 1000)
	_publish_v2(dat, device_id, snap, now, ts, rate)
	if not OUTPUT_V1:
		_st['pub'] = now
		_status('dmx_live seq %d: %d fixture (v1 spento)' % (_v2['seq'], len(snap['fixtures'])))
		return
	sig = json.dumps(snap, sort_keys=True)
	if sig == _st['sig'] and now - _st['pub'] < HEARTBEAT_S:
		return
	_st['seq'] += 1
	snap.update(device_id=device_id, seq=_st['seq'], ts=ts, rate_hz=rate)
	topic = 'gaia/devices/%s/dmx_output' % device_id
	dat.publish(topic, json.dumps(snap).encode('utf-8'), retain=True)
	_st['pub'] = now
	_st['sig'] = sig
	sent = sum(1 for f in snap['fixtures'] if f['sent'])
	_status('%s seq %d: %d fixture, %d inviate' % (topic, _st['seq'], len(snap['fixtures']), sent))


def _publish_v2(dat, device_id, snap, now, ts, rate):
	"""dmx_layout when it changes, dmx_live when a value changes or on the
	heartbeat (see the module doc)."""
	layout = [dict({'uid': f['uid']}, **{k: f[k] for k in LAYOUT_KEYS if k in f}) for f in snap['fixtures']]
	lsig = json.dumps(layout, sort_keys=True)
	if lsig != _v2['lsig'] or now - _v2['lpub'] >= LAYOUT_REFRESH_S:
		rev = hashlib.sha1(lsig.encode('utf-8')).hexdigest()[:12]
		msg = {'v': 2, 'device_id': device_id, 'rev': rev, 'ts': ts, 'fixtures': layout}
		dat.publish('gaia/devices/%s/dmx_layout' % device_id,
			json.dumps(msg, separators=(',', ':')).encode('utf-8'), retain=True)
		_v2.update(lsig=lsig, lpub=now, rev=rev)
	live = {f['uid']: {k: v for k, v in f.items() if k != 'uid' and k not in LAYOUT_KEYS and v is not None}
		for f in snap['fixtures']}
	body = {'master': snap['master'], 'blackout': snap['blackout'], 'strobe': snap['strobe'],
		'scene': snap['scene'], 'fixtures': live}
	sig = json.dumps(body, sort_keys=True)
	if sig == _v2['sig'] and now - _v2['pub'] < HEARTBEAT_S:
		return
	_v2['seq'] += 1
	msg = dict({'v': 2, 'device_id': device_id, 'seq': _v2['seq'], 'ts': ts, 'rate_hz': rate,
		'layout_rev': _v2['rev']}, **body)
	dat.publish('gaia/devices/%s/dmx_live' % device_id,
		json.dumps(msg, separators=(',', ':')).encode('utf-8'), retain=True)
	_v2.update(sig=sig, pub=now)


def _tick_rigs(now):
	"""Publish the rig meter on dmx_rigs (see the module doc)."""
	# -8 ms: at 60 fps 1/30 s falls on a frame edge and jitter would skip to the next
	if now - _rg['pub'] < 1.0 / RIGS_HZ - 0.008:
		return
	g = op.Gaia
	dat = g.op('mqtt_device') if g is not None else None
	if dat is None or not dat.isConnected:
		return
	try:
		r = rigs()
	except Exception:
		return
	sig = json.dumps(r, sort_keys=True)
	if sig == _rg['sig'] and now - _rg['pub'] < HEARTBEAT_S:
		return
	_rg['seq'] += 1
	device_id = str(g.par.Deviceid.eval())
	msg = {'v': 1, 'device_id': device_id, 'seq': _rg['seq'], 'ts': int(time.time() * 1000),
		'rate_hz': RIGS_HZ, 'rigs': r}
	dat.publish('gaia/devices/%s/dmx_rigs' % device_id, json.dumps(msg, separators=(',', ':')).encode('utf-8'),
		retain=False)
	_rg['pub'] = now
	_rg['sig'] = sig


def mqtt_ok():
	"""True while dmx_output reaches the broker: enabled, connected, last
	publish within 3 heartbeats (plancia_in's OSC backup reads this)."""
	if not parent().par.Outputenable.eval():
		return False
	g = op.Gaia
	dat = g.op('mqtt_device') if g is not None else None
	if dat is None or not dat.isConnected:
		return False
	return time.perf_counter() - _st['pub'] < 3 * HEARTBEAT_S


def _status(text):
	p = parent().par.Outputstatus
	if p.eval() != text:
		p.val = text
