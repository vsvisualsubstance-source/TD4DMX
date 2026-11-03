"""head_motion -- motion engine of the moving heads: plays a Plancia "motion
scene" on every head, each head on its own (wave, mirror, fan), computed
every frame on top of the scene's position (GAIA_INTERFACE "OPS, 41" /
"TD/Win-PD, 57").

Scene (Plancia layout.headMotions[], plancia/src/63-head-motion.js):
  {id, name, path: {pts: [[x, y], ...], closed},   x, y in -1..1, y up
   center: [pan, tilt] | null,  size: [pan, tilt]  units of /mh/pantilt
                                (-1..1 = full mechanical range of the model)
   period: {value, unit: 'beats'|'s'},  easing, pingpong, reverse,
   spread: {mode: same|phase|mirror|phase_mirror, phase},
   motor: null | 0..1 (moving_heads Speed at the start, null = unchanged)}
  center null (TD extension) = every head moves around where it was when the
  scene started.

hm_point() is a line-by-line port of hmPoint (same numbers as the Plancia's
preview and engine, see self_test()). Head k = position of the head among the
moving heads, in programmer order (unit order).

Sources, every frame from show/show_clock right AFTER the show timeline
(show_logic.tick), so on pan/tilt the motion wins over the timeline's cues:
  live      start({scene, heads?, bpm?}) -- Gaia heads_motion; t from the
            start. Has priority until stop() (heads stay where they are).
  timeline  the timeline's motion track (show_logic.motion_track(): cues
            {time, scene: id | 'off'}), with show Active: last cue <= Time
            wins, t = show Time, BPM of the timeline (else 120). Paused
            timeline = heads hold the point of that time.
Writes pan/tilt (degrees) through head_programmer.program (a global head
becomes manual); every other field of the heads stays as it is. While a
scene moves a head, Plancia /mh/pantilt skips it (owns(), checked by
head_programmer.pantilt_norm): the motion wins, no jitter.
"""
import math
import time

EASINGS = ('linear', 'easeIn', 'easeOut', 'easeInOut', 'sine')
SPREADS = ('same', 'phase', 'mirror', 'phase_mirror')

_live = {}     # {scene, heads (keys|None), bpm, started (absTime s), ts (epoch ms)}
_run = {}      # what is playing: {key, source, scene, heads, bpm, cue, ts, base, ranges}
_last = {}     # head key -> (pan, tilt) last written


# ---------------------------------------------------------------- math (port of 63-head-motion.js)

def hm_ease(x, mode):
	if mode == 'easeIn':
		return x * x
	if mode == 'easeOut':
		return 1 - (1 - x) * (1 - x)
	if mode == 'easeInOut':
		return 2 * x * x if x < .5 else 1 - (-2 * x + 2) ** 2 / 2
	if mode == 'sine':
		return (1 - math.cos(math.pi * x)) / 2
	return x


def _path_cache(path):
	pts = (path or {}).get('pts') or []
	seq = list(pts) + [pts[0]] if (path or {}).get('closed') and pts else list(pts)
	acc = [0.0]
	for i in range(1, len(seq)):
		acc.append(acc[i - 1] + math.hypot(seq[i][0] - seq[i - 1][0], seq[i][1] - seq[i - 1][1]))
	return pts, seq, acc


def hm_path_at(path, u, cache=None):
	"""Point at fraction u (0..1) of the path LENGTH (constant speed)."""
	pts, seq, acc = cache or _path_cache(path)
	if not pts:
		return [0.0, 0.0]
	if len(pts) == 1:
		return list(pts[0])
	total = acc[-1]
	if not total > 0:
		return list(pts[0])
	d = max(0.0, min(1.0, u)) * total
	i = 1
	while i < len(acc) - 1 and acc[i] < d:
		i += 1
	a, b = seq[i - 1], seq[i]
	f = (d - acc[i - 1]) / ((acc[i] - acc[i - 1]) or 1)
	return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f]


def hm_period(sc, bpm):
	p = sc.get('period') or {}
	try:
		v = float(p.get('value') or 0) or 4.0
	except (TypeError, ValueError):
		v = 4.0
	if v != v:   # NaN
		v = 4.0
	return max(.05, v if p.get('unit') == 's' else v * 60 / (bpm if bpm and bpm > 0 else 120))


def hm_point(sc, t, k=0, bpm=120, cache=None, center=None):
	"""[pan, tilt] (-1..1) of head k at time t (s). center overrides the
	scene's (center null = the head's own start position)."""
	sp = sc.get('spread') or {}
	mode = sp.get('mode') or 'same'
	u = t / hm_period(sc, bpm) + (k * float(sp.get('phase') or 0) if mode in ('phase', 'phase_mirror') else 0)
	u -= math.floor(u)
	if sc.get('pingpong'):
		u = u * 2 if u < .5 else 2 - u * 2
	if sc.get('reverse'):
		u = 1 - u
	x, y = hm_path_at(sc.get('path'), hm_ease(u, sc.get('easing')), cache)
	if mode in ('mirror', 'phase_mirror') and k % 2:
		x = -x
	c = center or sc.get('center') or [0, 0]
	s = sc.get('size') or [.4, .3]
	cl = lambda v: max(-1.0, min(1.0, v))
	return [round(cl(c[0] + s[0] * x), 4), round(cl(c[1] + s[1] * y), 4)]


def check_scene(sc):
	"""Validate a motion scene (raises ValueError); returns a clean copy."""
	if not isinstance(sc, dict):
		raise ValueError('scena di movimento: serve un oggetto')
	path = sc.get('path')
	if not isinstance(path, dict) or not isinstance(path.get('pts'), list) or not path['pts']:
		raise ValueError('scena %r: path.pts mancante' % sc.get('id'))
	pts = []
	for p in path['pts']:
		if not isinstance(p, (list, tuple)) or len(p) < 2:
			raise ValueError('scena %r: punto %r non valido' % (sc.get('id'), p))
		pts.append([float(p[0]), float(p[1])])
	out = dict(sc)
	out['path'] = {'pts': pts, 'closed': bool(path.get('closed'))}
	for k in ('center', 'size'):
		v = sc.get(k)
		if v is not None:
			if not isinstance(v, (list, tuple)) or len(v) < 2:
				raise ValueError('scena %r: %s deve essere [pan, tilt]' % (sc.get('id'), k))
			out[k] = [float(v[0]), float(v[1])]
	if sc.get('easing') not in (None,) + EASINGS:
		raise ValueError('scena %r: easing %r (%s)' % (sc.get('id'), sc.get('easing'), ', '.join(EASINGS)))
	mode = (sc.get('spread') or {}).get('mode')
	if mode not in (None,) + SPREADS:
		raise ValueError('scena %r: spread.mode %r (%s)' % (sc.get('id'), mode, ', '.join(SPREADS)))
	m = sc.get('motor')
	if m is not None:
		out['motor'] = max(0.0, min(1.0, float(m)))
	out['id'] = str(sc.get('id') or '')
	out['name'] = str(sc.get('name') or out['id'])
	return out


# ---------------------------------------------------------------- engine

def _hp():
	return me.parent().op('head_programmer').module


def _show_logic():
	s = me.parent().parent().op('show')
	return s.op('show_logic').module if s is not None else None


def start(scene, heads=None, bpm=None):
	"""Live: play `scene` (dict) on `heads` (keys; None = all) from now."""
	sc = check_scene(scene)
	_live.clear()
	_live.update(scene=sc, heads=list(heads) if heads else None,
		bpm=float(bpm) if bpm else None, started=absTime.seconds, ts=int(time.time() * 1000))


def stop():
	"""Live off: the heads stay where they are (the timeline track, if any,
	takes over)."""
	_live.clear()


def owns(key):
	"""True while a motion scene is moving head `key` (pan/tilt): Plancia
	/mh/pantilt leaves it alone (head_programmer.pantilt_norm)."""
	return bool(_run.get('scene')) and key in _run.get('heads', ())


def live():
	return {'scene': _live['scene'], 'heads': _live['heads'], 'bpm': _live['bpm']} if _live else None


def _source(show_t, active, bpm):
	"""(source, scene, t, bpm, heads, cue) of what has to play now."""
	if _live:
		return ('live', _live['scene'], absTime.seconds - _live['started'],
			_live['bpm'] or bpm or 120.0, _live['heads'], -1)
	sl = _show_logic()
	if active and sl is not None:
		idx, sc = sl.motion_at(show_t)
		if sc is not None:
			return ('timeline', sc, show_t, bpm or 120.0, None, idx)
		return ('off', None, 0.0, bpm, None, idx)
	return ('off', None, 0.0, bpm, None, -1)


def tick(show_t=0.0, active=False, bpm=None):
	"""Every frame, after the timeline: write pan/tilt of the moving heads."""
	src, sc, t, bpm, refs, cue = _source(show_t, active, bpm)
	if sc is None:
		if _run:
			_run.clear()
			_last.clear()
		_run['source'], _run['cue'] = src, cue
		return
	hp = _hp()
	key = '%s:%s:%s' % (src, sc.get('id'), _live.get('ts', '') if src == 'live' else cue)
	if _run.get('key') != key:
		_begin(hp, key, src, sc, refs, bpm, cue)
	_run['bpm'] = bpm
	cache = _run['cache']
	for k, hk in enumerate(_run['heads']):
		pr, tr = _run['ranges'][hk]
		x, y = hm_point(sc, t, k, bpm, cache, _run['base'].get(hk))
		pan, tilt = round(x * pr / 2.0, 3), round(-y * tr / 2.0, 3)
		if _last.get(hk) == (pan, tilt):
			continue
		_last[hk] = (pan, tilt)
		try:
			hp.program({'pan': pan, 'tilt': tilt}, [hk])
		except Exception as e:
			debug('head_motion %s: %s' % (hk, e))


def _begin(hp, key, src, sc, refs, bpm, cue):
	order = [h['key'] for h in hp.heads()]
	heads = [k for k in order if refs is None or k in refs]
	ranges = {k: hp._ranges(k) for k in heads}
	base = {}
	if sc.get('center') is None:
		for k in heads:   # around where each head is now
			e = hp.effective(k)
			base[k] = list(hp.pantilt_to_norm(k, float(e['pan']), float(e['tilt'])))
	_run.clear()
	_last.clear()
	_run.update(key=key, source=src, scene=sc, heads=heads, ranges=ranges, base=base, bpm=bpm,
		cue=cue, ts=int(time.time() * 1000), cache=_path_cache(sc.get('path')))
	if sc.get('motor') is not None:
		try:
			me.parent().par.Speed = float(sc['motor'])
		except Exception as e:
			debug('head_motion motor: %s' % e)


def state():
	"""{source live|timeline|off, scene_id, name, heads, bpm, period_s,
	started_ts, cue} -- changes only at a start/stop (t = now - started_ts)."""
	sc = _run.get('scene')
	if not sc:
		return {'source': _run.get('source', 'off'), 'scene_id': None, 'name': None, 'heads': [],
			'bpm': None, 'period_s': None, 'started_ts': None, 'cue': _run.get('cue', -1)}
	bpm = _run.get('bpm')
	return {'source': _run['source'], 'scene_id': sc.get('id'), 'name': sc.get('name'),
		'heads': list(_run['heads']), 'bpm': bpm, 'period_s': round(hm_period(sc, bpm), 4),
		'started_ts': _live.get('ts') if _run['source'] == 'live' else _run['ts'], 'cue': _run.get('cue', -1)}


# ---------------------------------------------------------------- parity with the Plancia tests

def _templates():
	"""The Plancia templates used by plancia/test/head-motion.test.js."""
	tau = math.pi * 2

	def P(n, f, closed):
		return {'pts': [[round(a, 4), round(b, 4)] for a, b in
			(f(i / (n if closed else n - 1)) for i in range(n))], 'closed': closed}

	def T(id_, path, **o):
		d = {'id': 'hm-' + id_, 'name': id_, 'path': path, 'center': [0, 0], 'size': [.35, .25],
			'period': {'value': 8, 'unit': 'beats'}, 'easing': 'linear', 'pingpong': False,
			'reverse': False, 'spread': {'mode': 'same', 'phase': 0}, 'motor': None}
		d.update(o)
		return d
	circle = P(72, lambda u: (math.cos(u * tau), math.sin(u * tau)), True)
	return {
		'hm-cerchio': T('cerchio', circle),
		'hm-scanner': T('scanner', {'pts': [[-1, 0], [1, 0]], 'closed': False}, size=[.45, 0],
			pingpong=True, easing='sine'),
		'hm-apri': T('apri', {'pts': [[0, 0], [1, 0]], 'closed': False}, size=[.4, 0], pingpong=True,
			easing='sine', spread={'mode': 'mirror', 'phase': 0}),
		'hm-onda-cerchi': T('cerchio', circle, id='hm-onda-cerchi', spread={'mode': 'phase', 'phase': .15}),
	}


def self_test():
	"""The assertions of plancia/test/head-motion.test.js; returns [] or the
	failures."""
	tpl = _templates()
	fails = []

	def eq(a, b, what):
		if [round(x + 0.0, 4) for x in a] != [round(x + 0.0, 4) for x in b]:
			fails.append('%s: %r != %r' % (what, a, b))
	c = tpl['hm-cerchio']
	eq(hm_point(c, 0), [0.35, 0], 'cerchio t0')
	eq(hm_point(c, 1), [0, 0.25], 'cerchio t1')
	eq(hm_point(c, 2), [-0.35, 0], 'cerchio t2')
	eq(hm_point(c, 4), hm_point(c, 0), 'cerchio giro')
	eq(hm_point(c, 2, 0, 60), [0, 0.25], 'cerchio 60 BPM')
	s = tpl['hm-scanner']
	eq([hm_point(s, t)[0] for t in range(5)], [-0.45, 0, 0.45, 0, -0.45], 'scanner pingpong')
	fan = tpl['hm-apri']
	eq([hm_point(fan, 1, 1)[0]], [-hm_point(fan, 1, 0)[0]], 'ventaglio specchio')
	w = tpl['hm-onda-cerchi']
	if hm_point(w, 0, 0) == hm_point(w, 0, 1):
		fails.append('onda: teste 0 e 1 uguali')
	sq = {'pts': [[-1, -1], [1, -1], [1, 1], [-1, 1]], 'closed': True}
	eq(hm_path_at(sq, 0.25), [1, -1], 'quadrato 1/4')
	eq(hm_path_at(sq, 0.5), [1, 1], 'quadrato 1/2')
	big = dict(c, center=[0.9, 0.9], size=[1, 1])
	for i in range(40):
		if any(v < -1 or v > 1 for v in hm_point(big, i * 0.1)):
			fails.append('fuori dal pad a t=%.1f' % (i * 0.1))
	return fails
