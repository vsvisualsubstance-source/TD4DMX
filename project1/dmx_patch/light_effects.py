"""light_effects -- light effects computed per light every frame, on top of
the scene's look: dimmer waves running over a group, colour waves, sparkle,
chases (GAIA_INTERFACE "OPS, 42" point 3 / "TD/Win-PD, 59").

Effect (same pattern as the head motion scenes):
  {id, name,
   target: {group: <group or Plancia alias>} | {fixtures: [uid | id, ...]},
   channel: dimmer | color | white | strobe,
   shape: sine | triangle | saw | square | pulse | random,
   period: {value, unit: 'beats' | 's'},     one cycle of ONE light
   spread: {phase, mirror},                   light k: +k*phase of a cycle;
                                              mirror = k counted from the
                                              middle of the row outwards
   min, max,                                  0..1 (dimmer / white / strobe)
   colors: [[r, g, b] 0..1, ...] | palette,   channel color (palette = a rig
                                              palette name, as Palette)
   duty}                                      square: fraction ON (0.5);
                                              pulse: decay length (0.25);
                                              random: chance a light is on
                                              in a cycle (1 = always, value
                                              random)

Light order (k): the target's fixtures by unit, then x on the stage plan,
then id. Wave w(u) in 0..1 for u = fraction of the light's cycle:
  sine (1 - cos 2pi u)/2, triangle 1 - |2u - 1|, saw u, square u < duty,
  pulse max(0, 1 - u/duty), random = a fresh random value per light and
  cycle (sparkle).
What the effect does to a light (the scene look underneath stays):
  dimmer / strobe  intensity x (min + (max - min) * w)   -- the intensity
                   channels universe_build scales (dimmer*, else colour)
  white            white channel = (min + (max - min) * w) * 255
  color            RGB = the colour at w in `colors` (saw: cyclic over all
                   of them, random: one of them), keeping the light's
                   intensity (dimmer kept; without dimmer, scaled by the
                   look's brightness)
Several effects at once: applied in order (live after timeline), dimmer
factors multiply, the last colour wins. Group Level, Master, Strobe and
Blackout of dmx_patch still act after the effects.

Sources: live (start/stop, Gaia dmx_effect; t from its start) and the
timeline's effects track (show_logic.effects_at; show Active, t = show
Time, timeline BPM else 120). Applied by universe_build_callbacks.
"""
import math
import time

CHANNELS = ('dimmer', 'color', 'white', 'strobe')
SHAPES = ('sine', 'triangle', 'saw', 'square', 'pulse', 'random')
DUTY = {'square': 0.5, 'pulse': 0.25, 'random': 1.0}
RGB = ('red', 'green', 'blue')

_live = {}     # id -> {effect, bpm, started (absTime s), ts (epoch ms)}
_frame = {'frame': None, 'mods': {}}


# ---------------------------------------------------------------- math

def wave(shape, u, duty=None, seed=0.0):
	"""0..1 value of the wave at fraction u (0..1) of a cycle."""
	d = DUTY.get(shape, 0.5) if duty is None else max(0.001, min(1.0, float(duty)))
	if shape == 'triangle':
		return 1.0 - abs(2.0 * u - 1.0)
	if shape == 'saw':
		return u
	if shape == 'square':
		return 1.0 if u < d else 0.0
	if shape == 'pulse':
		return max(0.0, 1.0 - u / d)
	if shape == 'random':
		on = _rand(seed + 0.5) < d
		return _rand(seed) if on else 0.0
	return (1.0 - math.cos(2.0 * math.pi * u)) / 2.0


def _rand(x):
	v = math.sin(x * 12.9898 + 78.233) * 43758.5453
	return v - math.floor(v)


def period_s(e, bpm):
	p = e.get('period') or {}
	try:
		v = float(p.get('value') or 0) or 4.0
	except (TypeError, ValueError):
		v = 4.0
	return max(.05, v if p.get('unit') == 's' else v * 60.0 / (bpm if bpm and bpm > 0 else 120.0))


def light_value(e, t, k, n, bpm):
	"""(w, u, cycle) of light k of n at time t."""
	sp = e.get('spread') or {}
	kk = abs(k - (n - 1) / 2.0) if sp.get('mirror') else k
	x = t / period_s(e, bpm) + kk * float(sp.get('phase') or 0)
	cyc = math.floor(x)
	u = x - cyc
	return wave(e.get('shape') or 'sine', u, e.get('duty'), seed=cyc * 7.31 + kk * 3.17), u, cyc


def color_at(e, w, cols):
	"""[r, g, b] 0..1 at wave value w."""
	if not cols:
		return None
	if len(cols) == 1:
		return list(cols[0])
	shape = e.get('shape') or 'sine'
	if shape == 'random':
		return list(cols[min(len(cols) - 1, int(w * len(cols)))])
	if shape == 'saw':
		x = (w % 1.0) * len(cols)
		i = int(x) % len(cols)
		a, b, f = cols[i], cols[(i + 1) % len(cols)], x - int(x)
	else:
		x = max(0.0, min(1.0, w)) * (len(cols) - 1)
		i = min(len(cols) - 2, int(x))
		a, b, f = cols[i], cols[i + 1], x - i
	return [a[j] + (b[j] - a[j]) * f for j in range(3)]


def check_effect(e):
	"""Validate an effect (raises ValueError); returns a clean copy."""
	if not isinstance(e, dict):
		raise ValueError('effetto: serve un oggetto')
	out = dict(e)
	out['id'] = str(e.get('id') or '').strip()
	if not out['id']:
		raise ValueError('effetto senza id')
	out['name'] = str(e.get('name') or out['id'])
	tg = e.get('target')
	if not isinstance(tg, dict) or not (tg.get('group') or tg.get('fixtures')):
		raise ValueError('effetto %r: target = {group} oppure {fixtures: [...]}' % out['id'])
	ch = e.get('channel') or 'dimmer'
	if ch not in CHANNELS:
		raise ValueError('effetto %r: channel %r (%s)' % (out['id'], ch, ', '.join(CHANNELS)))
	out['channel'] = ch
	sh = e.get('shape') or ('square' if ch == 'strobe' else 'sine')
	if sh not in SHAPES:
		raise ValueError('effetto %r: shape %r (%s)' % (out['id'], sh, ', '.join(SHAPES)))
	out['shape'] = sh
	for k, d in (('min', 0.0), ('max', 1.0)):
		out[k] = max(0.0, min(1.0, float(e.get(k, d) if e.get(k) is not None else d)))
	if e.get('duty') is not None:
		out['duty'] = max(0.001, min(1.0, float(e['duty'])))
	if ch == 'color':
		cols = e.get('colors')
		if cols is not None:
			if not isinstance(cols, list) or not cols:
				raise ValueError('effetto %r: colors = [[r, g, b], ...]' % out['id'])
			out['colors'] = [[max(0.0, min(1.0, float(c[j]))) for j in range(3)] for c in cols]
		elif not e.get('palette'):
			raise ValueError('effetto %r: channel color vuole colors o palette' % out['id'])
	return out


# ---------------------------------------------------------------- sources

def start(effect, bpm=None):
	"""Live: play `effect` from now (same id = restarted with the new one)."""
	e = check_effect(effect)
	_live[e['id']] = {'effect': e, 'bpm': float(bpm) if bpm else None,
		'started': absTime.seconds, 'ts': int(time.time() * 1000)}
	return e['id']


def stop(eid=None):
	"""Stop one live effect (id), or all of them (None)."""
	if eid is None:
		_live.clear()
	else:
		_live.pop(str(eid), None)


def live():
	return [{'effect': x['effect'], 'bpm': x['bpm']} for x in _live.values()]


def _show():
	return me.parent().parent().op('show')


def _active(bpm_tl):
	"""[(effect, t, bpm, source)] playing now: timeline track, then live."""
	out = []
	s = _show()
	if s is not None and s.par.Active.eval():
		sl = s.op('show_logic').module
		t = float(s.par.Time.eval())
		for e in sl.effects_at(t)[1]:
			if e['id'] not in _live:
				out.append((e, t, bpm_tl, 'timeline'))
	now = absTime.seconds
	for x in _live.values():
		out.append((x['effect'], now - x['started'], x['bpm'] or bpm_tl, 'live'))
	return out


def _bpm():
	s = _show()
	b = s.fetch('timeline_bpm', None, search=False) if s is not None else None
	return float(b) if b else 120.0


# ---------------------------------------------------------------- per-light modifiers

def _fl():
	return op('fixture_logic').module


def _targets(e, rows):
	tg = e['target']
	fl = _fl()
	if tg.get('group'):
		g = fl.resolve_group(tg['group'])
		fx = [f for f in rows if f['group'] == g and f['enabled']]
	else:
		want = {str(x) for x in tg.get('fixtures') or []}
		fx = [f for f in rows if f['enabled'] and (f['uid'] in want or str(f['id']) in want)]
	return sorted(fx, key=lambda f: (f['unit'], f['x'], f['id']))


def _palette_colors(e, rows):
	"""Colours of a rig palette name, read from a chase rig's generator."""
	name = e.get('palette')
	home = me.parent().parent()
	for g in _fl().groups():
		comp = home.op(g['comp'])
		gen = comp.op('dmx_generator_callbacks1') if comp is not None else None
		pals = getattr(gen.module, 'ALL_PALETTES', None) if gen is not None else None
		if pals and name in pals:
			cols = [[c / 255.0 for c in rgb] for rgb in pals[name]]
			return cols[:-1] if len(cols) > 1 and cols[-1] == cols[0] else cols
	return []


def mods():
	"""{fixture id: {'dim': factor, 'rgb': [0..1]|None, 'white': 0..255|None}}
	for this frame (computed once per frame)."""
	f = absTime.frame
	if _frame['frame'] == f:
		return _frame['mods']
	out = {}
	act = _active(_bpm()) if (_live or _show() is not None) else []
	if act:
		rows = _fl().rows()
		for e, t, bpm, _src in act:
			fx = _targets(e, rows)
			n = len(fx)
			cols = e.get('colors') or (_palette_colors(e, rows) if e['channel'] == 'color' else None)
			for k, fxr in enumerate(fx):
				w, _u, _c = light_value(e, t, k, n, bpm)
				m = out.setdefault(fxr['id'], {'dim': 1.0, 'rgb': None, 'white': None})
				lvl = e['min'] + (e['max'] - e['min']) * w
				if e['channel'] in ('dimmer', 'strobe'):
					m['dim'] *= lvl
				elif e['channel'] == 'white':
					m['white'] = lvl * 255.0
				else:
					c = color_at(e, w, cols)
					if c is not None:
						m['rgb'] = c
	_frame['frame'], _frame['mods'] = f, out
	return out


def apply(m, chans, vals, intensity):
	"""Apply one light's modifiers to its channel values (list, in place).
	chans = profile channel names, intensity = indices universe_build
	scales for the level."""
	if m['rgb'] is not None:
		idx = {c: i for i, c in enumerate(chans)}
		if all(c in idx for c in RGB):
			has_dim = any(c.startswith('dimmer') for c in chans)
			b = 1.0 if has_dim else max([vals[idx[c]] for c in RGB if idx[c] < len(vals)] + [0.0]) / 255.0
			for j, c in enumerate(RGB):
				if idx[c] < len(vals):
					vals[idx[c]] = m['rgb'][j] * 255.0 * b
	if m['white'] is not None:
		for i, c in enumerate(chans):
			if c == 'white' and i < len(vals):
				vals[i] = m['white']
	if m['dim'] != 1.0:
		for i in intensity:
			if i < len(vals):
				vals[i] *= m['dim']


def state():
	"""{live: [{id, name, started_ts, bpm}], timeline: {cue, ids},
	active: [ids]} -- changes only at start/stop/cue."""
	s = _show()
	tl = {'cue': -1, 'ids': []}
	if s is not None and s.par.Active.eval():
		idx, effs = s.op('show_logic').module.effects_at(float(s.par.Time.eval()))
		tl = {'cue': idx, 'ids': [e['id'] for e in effs]}
	lv = [{'id': x['effect']['id'], 'name': x['effect']['name'], 'started_ts': x['ts'], 'bpm': x['bpm']}
		for x in _live.values()]
	return {'live': lv, 'timeline': tl,
		'active': [i for i in tl['ids'] if i not in _live] + [x['id'] for x in lv]}
