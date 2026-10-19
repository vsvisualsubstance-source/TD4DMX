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
     "intensity" 0-1 (dimmer, or the brightest colour channel without
     one), "rgb_out" [r, g, b] 0-1 = rgb * dimmer: the colour as seen,
     null without colour channels,
     heads only: "color_wheel", "gobo", "shutter" 0-255 and "pan",
     "tilt" in degrees from the head programmer (a wheel has no RGB:
     rgb / rgb_out stay null)}]}
A fixture that is not sent has every output field null.

Published when an output value changes, at most Outputrate times per second,
and at least every HEARTBEAT_S (ts refreshed) so a UI can call it stale when
nothing arrives for 3 heartbeats (measure the gap on arrival, do not
compare ts with the UI's clock). Strobe: the gate is sampled at the
publishing rate, so "strobe": true says the values are flickering.

tick() from gaia_services/lifecycle onFrameStart; pars Outputenable,
Outputrate, Outputstatus on gaia_services.
"""
import json
import time

HEARTBEAT_S = 2.0
_st = {'seq': 0, 'pub': 0.0, 'sig': None}


def _home():
	return parent().parent()


def _round(v):
	return None if v is None else int(round(v))


def _fixture(r, rep, fl, ub, uids, heads):
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
	if all(c in vals for c in ('red', 'green', 'blue')):
		rgb = [vals['red'], vals['green'], vals['blue']]
		d['rgb'] = [_round(x) for x in rgb]
		k = 1.0 if dim is None else dim / 255.0
		d['rgb_out'] = [round(x / 255.0 * k, 3) for x in rgb]
		d['intensity'] = round((dim if dim is not None else max(rgb)) / 255.0, 3)
	elif dim is not None:
		d['intensity'] = round(dim / 255.0, 3)
	elif 'output' in vals:
		d['intensity'] = round(vals['output'] / 255.0, 3)
	if g == 'heads':
		d['color_wheel'] = _round(vals.get('color'))
		d['gobo'] = _round(vals.get('gobo'))
		d['shutter'] = _round(vals.get('shutter'))
		h = heads.get(fid)
		if h is not None:
			d['pan'], d['tilt'] = round(h['pan'], 1), round(h['tilt'], 1)
	return d


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
	fixtures = [_fixture(r, rep, fl, ub, uids, heads) for r in range(1, rep.numRows)]
	pp = patch.par
	sl = home.op('show/show_logic')
	return {'v': 1, 'master': round(float(pp.Master.eval()), 3), 'blackout': bool(pp.Blackout.eval()),
		'strobe': bool(pp.Strobe.eval()), 'scene': sl.module.active_scene() if sl is not None else None,
		'fixtures': fixtures}


def tick():
	c = parent()
	if not c.par.Outputenable.eval():
		_st['sig'] = None
		_status('spento')
		return
	now = time.perf_counter()
	rate = max(0.5, float(c.par.Outputrate.eval()))
	if now - _st['pub'] < 1.0 / rate:
		return
	try:
		snap = snapshot()
	except Exception as e:
		_status('errore: %s' % e)
		return
	sig = json.dumps(snap, sort_keys=True)
	if sig == _st['sig'] and now - _st['pub'] < HEARTBEAT_S:
		return
	g = op.Gaia
	dat = g.op('mqtt_device') if g is not None else None
	if dat is None or not dat.isConnected:
		_status('MQTT non connesso')
		return
	_st['seq'] += 1
	device_id = str(g.par.Deviceid.eval())
	snap.update(device_id=device_id, seq=_st['seq'], ts=int(time.time() * 1000), rate_hz=rate)
	topic = 'gaia/devices/%s/dmx_output' % device_id
	dat.publish(topic, json.dumps(snap).encode('utf-8'), retain=True)
	_st['pub'] = now
	_st['sig'] = sig
	sent = sum(1 for f in snap['fixtures'] if f['sent'])
	_status('%s seq %d: %d fixture, %d inviate' % (topic, _st['seq'], len(snap['fixtures']), sent))


def _status(text):
	p = parent().par.Outputstatus
	if p.eval() != text:
		p.val = text
