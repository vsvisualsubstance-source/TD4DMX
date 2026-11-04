"""timeline_ui -- Timeline tab of the Config window: draws /project1/show
(cues, automation lanes, playhead) and turns mouse input into edits.

Canvas rows, top to bottom: header (status), ruler (click/drag = seek), cue
lane (block per cue until the next one, fade ramp at its start; click =
select, drag = move in time), one row per automation lane (curve + keys;
click = select key / lane, drag a key = time + value); at the bottom an
overview of the whole show with the visible window (click/drag = seek, the
view pages there).
Drags are previewed here and committed on release (file-synced tables).
View = show pars Viewstart / Viewlength / Follow (paging while playing).
"""
import re
import unicodedata
import numpy as np
import cv2

BG = (0.065, 0.07, 0.08)
PANEL = (0.09, 0.095, 0.11)
GRID = (0.14, 0.15, 0.17)
TEXT = (0.86, 0.88, 0.91)
DIM = (0.50, 0.53, 0.58)
HEAD = (0.95, 0.27, 0.25)
SEL = (1.0, 1.0, 1.0)
SCENE_COLORS = [(0.20, 0.62, 0.92), (0.96, 0.58, 0.18), (0.55, 0.82, 0.30), (0.82, 0.38, 0.95),
	(0.95, 0.80, 0.25), (0.25, 0.85, 0.78), (0.95, 0.42, 0.58), (0.60, 0.60, 0.95)]
FONT = cv2.FONT_HERSHEY_SIMPLEX

HEADER_H, RULER_H, CUE_H, LANE_H = 30, 24, 86, 54
TRACK_H = 46   # cue row height when there is more than one track
OV_H = 30      # overview strip at the bottom
GUT_W = 84     # left column with the row names, when there is more than one row
SNAP = 0.1


def _c(col):
	"""0..1 RGB -> 0..255 RGBA for the uint8 canvases."""
	return tuple(int(max(0.0, min(1.0, v)) * 255) for v in col[:3]) + (255,)


def _cv(fn, ci):
	"""cv2 drawing call with its colour argument (index ci) converted by _c."""
	def call(*args):
		args = list(args)
		args[ci] = _c(args[ci])
		return fn(*args)
	return call


_rect = _cv(cv2.rectangle, 3)
_line = _cv(cv2.line, 3)
_circle = _cv(cv2.circle, 3)
_polylines = _cv(cv2.polylines, 3)
_fillpoly = _cv(cv2.fillPoly, 2)

_drag = {}
_view = {}


def _show():
	return parent.Config.parent().op('show')


def _sl():
	return _show().op('show_logic').module


# cv2 Hershey fonts draw ASCII only: symbols the Plancia puts in labels get an
# ASCII stand-in, accents are dropped (e -> e), anything else is removed
_ASCII_SUBS = {'⟳': '>>', '↻': '>>', '→': '->', '…': '...', '–': '-',
	'—': '-', '‘': "'", '’': "'", '“': '"', '”': '"', '·': '-', '×': 'x'}


def _ascii(s):
	s = ''.join(_ASCII_SUBS.get(ch, ch) for ch in str(s))
	return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')


def _tw(s, scale):
	"""Pixel width of an (ASCII) string."""
	return cv2.getTextSize(s, FONT, scale, 1)[0][0]


def _fit(s, maxw, scale):
	"""s cut to maxw pixels ('.' marks the cut); '' when not even 2 chars fit."""
	if _tw(s, scale) <= maxw:
		return s
	while len(s) > 2 and _tw(s + '.', scale) > maxw:
		s = s[:-1]
	s = s.rstrip()
	return s + '.' if len(s) > 2 or _tw(s + '.', scale) <= maxw else ''


def _text(img, s, x, y, color=TEXT, scale=0.42, maxw=None):
	s = _ascii(s)
	if maxw is not None:
		s = _fit(s, maxw, scale)
	if s:
		cv2.putText(img, s, (int(x), int(y)), FONT, scale, _c(color), 1, cv2.LINE_AA)


def _base_label(s):
	"""'>> Colori veloci 12' -> 'Colori veloci' (run of chase-like cues)."""
	return re.sub(r'\s*\d+$', '', _ascii(s).replace('>>', '').strip())


GROUP_W = 70   # cue blocks narrower than this (px) get grouped by base label


def _fmt(t):
	m, s = divmod(max(0.0, t), 60)
	return '%d:%04.1f' % (m, s)


def _view_range(w):
	p = _show().par
	vl = max(2.0, float(p.Viewlength.eval()))
	vs = max(0.0, float(p.Viewstart.eval()))
	t = float(p.Time.eval())
	if p.Follow.eval() and p.Play.eval() and not (vs <= t < vs + vl):
		vs = (t // vl) * vl
	return vs, vl


def _x(t):
	g = _view.get('gut', 0)
	return g + (t - _view['vs']) / _view['vl'] * (_view['w'] - g)


def _t(x):
	g = _view.get('gut', 0)
	return _view['vs'] + (x - g) / float(_view['w'] - g) * _view['vl']


def _scene_color(name):
	names = _sl().scene_names()
	return SCENE_COLORS[names.index(name) % len(SCENE_COLORS)] if name in names else DIM


def _cues():
	cs = [dict(c) for c in _sl().cues()]
	if _drag.get('kind') == 'cue':
		for c in cs:
			if c['id'] == _drag['id']:
				c['time'] = _drag['time']
		cs.sort(key=lambda c: (c['time'], c['id']))
	return cs


def _track_rows(sl):
	"""Cue rows of the canvas: the show's tracks (main first)."""
	return sl.tracks() if hasattr(sl, 'tracks') else ['']


def _extra_rows(sl):
	"""[(title, [(time, text)])] of the chase / motion / effects tracks with
	cues ('' text = off)."""
	out = []
	if hasattr(sl, 'chases_track'):
		tr = sl.chases_track()
		names = {c['id']: c['name'] for c in tr.get('chases') or []}
		if tr.get('cues'):
			out.append(('CHASE', [(c['time'], '' if c['chase'] == 'off' else '>> %s' % names.get(c['chase'], c['chase']))   # cv2 fonts: ASCII only
				for c in tr['cues']]))
	if hasattr(sl, 'motion_track'):
		tr = sl.motion_track()
		names = {s['id']: s.get('name') or s['id'] for s in tr.get('scenes') or []}
		if tr.get('cues'):
			out.append(('MOVIMENTO', [(c['time'], '' if c['scene'] == 'off' else (c.get('label') or names.get(c['scene'], c['scene'])))
				for c in tr['cues']]))
	if hasattr(sl, 'effects_track'):
		tr = sl.effects_track()
		names = {e['id']: e.get('name') or e['id'] for e in tr.get('effects') or []}
		if tr.get('cues'):
			out.append(('EFFETTI', [(c['time'], ' + '.join(names.get(i, i) for i in c['effects'])) for c in tr['cues']]))
	return out


def _lanes():
	out = {}
	for lane, ks in _sl().lanes().items():
		ks = [dict(k) for k in ks]
		if _drag.get('kind') == 'key':
			for k in ks:
				if k['id'] == _drag['id']:
					k['time'], k['value'] = _drag['time'], _drag['value']
			ks.sort(key=lambda k: k['time'])
		out[lane] = ks
	return out


def _lane_range(lane, ks):
	lo, hi = _sl().par_range(lane)
	vals = [k['value'] for k in ks]
	lo, hi = min([lo] + vals), max([hi] + vals)
	return (lo, hi) if hi > lo else (lo, lo + 1.0)


def render(scriptOp):
	w = int(scriptOp.par.resolutionw.eval())
	h = int(scriptOp.par.resolutionh.eval())
	img = np.empty((h, w, 4), dtype=np.uint8)
	img[:] = _c(BG)
	show = _show()
	sl = _sl()
	p = show.par
	vs, vl = _view_range(w)
	rows = _track_rows(sl)
	extra = _extra_rows(sl)
	gut = GUT_W if (len(rows) > 1 or extra) else 0
	_view.update(vs=vs, vl=vl, w=w, h=h, gut=gut)
	hb = h - OV_H - 6   # bottom of the main area, above the overview
	length = float(p.Length.eval())
	t_now = float(p.Time.eval())
	sel_cue, sel_key = int(p.Cue.eval()), int(p.Key.eval())
	sel_lane = str(p.Lane.eval())
	# beyond the end of the show: darker background, drawn first
	xe = int(_x(length))
	if xe < w:
		img[HEADER_H:hb, max(0, xe):] = _c(tuple(v * 0.45 for v in BG))

	# header
	_text(img, p.Status.eval(), 10, 20, TEXT, 0.48)
	msg = p.Message.eval()
	if msg:
		_text(img, msg, w - 10 - _tw(_ascii(msg), 0.42), 20, HEAD, 0.42)

	# ruler: tick step from zoom; no tick label under the playhead tag
	xp = int(_x(t_now))
	y0 = HEADER_H
	_rect(img, (0, y0), (w, y0 + RULER_H), PANEL, -1)
	step = next(s for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600) if vl / s <= 24)
	t = (vs // step) * step
	while t <= vs + vl:
		x = int(_x(t))
		_line(img, (x, y0 + RULER_H - 8), (x, y0 + RULER_H), DIM, 1)
		_line(img, (x, y0 + RULER_H), (x, hb), GRID, 1)
		if not (x + 3 + _tw(_fmt(t), 0.36) >= xp - 2 and x + 3 <= xp + 54):
			_text(img, _fmt(t), x + 3, y0 + 14, DIM, 0.36)
		t += step

	# cue lanes: one row per track ("TD/Win-PD, 60"), the main one first
	scenes = {s['name']: s for s in sl.scenes()}
	allc = _cues()
	names = []   # (title, y0, y1, marker colour) for the left column
	_view['tracks'] = []
	cy0 = HEADER_H + RULER_H + 4
	rh = CUE_H if len(rows) == 1 else TRACK_H
	for track in rows:
		cy1 = cy0 + rh
		_view['tracks'].append((track, cy0, cy1))
		cs = [c for c in allc if c.get('track', track) == track]
		# runs of narrow blocks with the same base label (a chase expanded
		# into cues): one label for the whole run instead of a label each
		groups, run = [], []
		for i, c in enumerate(cs):
			end = cs[i + 1]['time'] if i + 1 < len(cs) else length
			key = _base_label(c['label'] or c['scene'])
			if _x(end) - _x(c['time']) < GROUP_W and run and run[-1][1] == key:
				run.append((c, key, end))
				continue
			if len(run) > 1:
				groups.append(run)
			run = [(c, key, end)] if _x(end) - _x(c['time']) < GROUP_W else []
		if len(run) > 1:
			groups.append(run)
		grouped = {c['id'] for g in groups for c, _k, _e in g}
		for i, c in enumerate(cs):
			end = cs[i + 1]['time'] if i + 1 < len(cs) else length
			x0, x1 = int(_x(c['time'])), int(_x(end))
			if x1 < 0 or x0 > w:
				continue
			col = _scene_color(c['scene'])
			_rect(img, (x0, cy0), (x1, cy1), tuple(v * 0.45 for v in col), -1)
			xf = int(_x(c['time'] + c['fade']))
			if xf > x0:   # fade ramp from the previous scene
				pts = np.array([[x0, cy1], [xf, cy0], [xf, cy1]], np.int32)
				_fillpoly(img, [pts], tuple(v * 0.8 for v in col))
			_line(img, (x0, cy0), (x0, cy1), col, 2)
			if c['id'] == sel_cue:
				_rect(img, (x0, cy0 - 2), (x1, cy1 + 2), SEL, 2)
			if c['id'] in grouped:
				continue
			label = scenes.get(c['scene'], {}).get('label', c['scene'])
			tw = max(0, min(x1, w) - max(x0, gut) - 10)
			tx = max(x0, gut) + 6
			_text(img, c['label'] or ('cue %d' % c['id']), tx, cy0 + 16, TEXT, 0.42, tw)
			if rh >= CUE_H:
				_text(img, label, tx, cy0 + 38, TEXT, 0.42, tw)
				s = _fit('%s  fade %.1fs' % (_fmt(c['time']), c['fade']), tw, 0.36)
				if s:   # dark plate: readable over the fade ramp
					_rect(img, (tx - 4, cy1 - 21), (tx + 4 + _tw(s, 0.36), cy1 - 3), tuple(v * 0.45 for v in col), -1)
					_text(img, s, tx, cy1 - 8, DIM, 0.36)
			else:
				_text(img, label, tx, cy1 - 8, DIM, 0.36, tw)
		for g in groups:   # one label on a dark plate over the run
			g0, g1 = int(_x(g[0][0]['time'])), int(_x(g[-1][2]))
			if g1 < 0 or g0 > w:
				continue
			gx0, gx1 = max(g0, gut), min(g1, w)
			s = _fit('%s  x%d' % (g[0][1] or 'cue', len(g)), gx1 - gx0 - 12, 0.42)
			if s:
				_rect(img, (gx0 + 2, cy0 + 3), (gx0 + 10 + _tw(s, 0.42), cy0 + 22), BG, -1)
				_text(img, s, gx0 + 6, cy0 + 17, TEXT, 0.42)
			if rh >= CUE_H:
				s = _fit('%s - %s' % (_fmt(g[0][0]['time']), _fmt(g[-1][2])), gx1 - gx0 - 12, 0.36)
				if s:
					_rect(img, (gx0 + 2, cy1 - 21), (gx0 + 10 + _tw(s, 0.36), cy1 - 3), BG, -1)
					_text(img, s, gx0 + 6, cy1 - 8, DIM, 0.36)
		if gut:
			names.append((track, cy0, cy1, HEAD if track == sl.MAIN_TRACK else DIM))
		cy0 = cy1 + 4
	# the other tracks of the timeline document (read-only blocks): chases,
	# head motion, light effects -- only when they have cues
	for title, blocks in extra:
		cy1 = cy0 + TRACK_H
		for i, (t0, text) in enumerate(blocks):
			end = blocks[i + 1][0] if i + 1 < len(blocks) else length
			x0, x1 = int(_x(t0)), int(_x(end))
			if x1 < 0 or x0 > w or not text:
				continue
			col = SCENE_COLORS[hash(text) % len(SCENE_COLORS)]
			_rect(img, (x0, cy0), (x1, cy1), tuple(v * 0.35 for v in col), -1)
			_line(img, (x0, cy0), (x0, cy1), col, 2)
			_text(img, text, max(x0, gut) + 6, cy0 + 16, TEXT, 0.42, min(x1, w) - max(x0, gut) - 10)
		names.append((title, cy0, cy1, DIM))
		cy0 = cy1 + 4
	cy1 = cy0 - 4
	if gut:   # left column: one name per row, the blocks scroll under it
		_rect(img, (0, HEADER_H), (gut - 1, cy1), PANEL, -1)
		_line(img, (gut - 1, HEADER_H), (gut - 1, cy1), GRID, 1)
		for title, y0r, y1r, col in names:
			_rect(img, (0, y0r), (3, y1r), col, -1)
			_text(img, title.upper(), 10, (y0r + y1r) // 2 + 4, TEXT if col == HEAD else DIM, 0.36, gut - 16)
	if not allc:
		_text(img, 'nessuna cue: Scene > New Scene From Live, poi Cue > Add Cue At Playhead', 12, cy1 - 30, DIM, 0.45)

	# automation lanes
	_view['lanes'] = []
	ly = cy1 + 8
	for lane, ks in _lanes().items():
		if ly + LANE_H > hb:
			break
		_view['lanes'].append((lane, ly, ly + LANE_H))
		_rect(img, (0, ly), (w, ly + LANE_H), PANEL, -1)
		if lane == sel_lane:
			_rect(img, (0, ly), (3, ly + LANE_H), SEL, -1)
		lo, hi = _lane_range(lane, ks)

		def ky(v):
			return int(ly + LANE_H - 6 - (v - lo) / (hi - lo) * (LANE_H - 12))

		pts = []
		for a, b in zip(ks, ks[1:]):
			n = 1 if a['interp'] == 'linear' else 16
			for j in range(n + 1):
				x = j / float(n)
				if a['interp'] == 'step':
					x = 0.0 if j < n else 1.0
				elif a['interp'] == 'smooth':
					x = x * x * (3 - 2 * x)
				tt = a['time'] + (b['time'] - a['time']) * (j / float(n))
				pts.append((int(_x(tt)), ky(a['value'] + (b['value'] - a['value']) * x)))
		if len(pts) > 1:
			_polylines(img, [np.array(pts, np.int32)], False, (0.85, 0.85, 0.5), 2, cv2.LINE_AA)
		for k in ks:
			c = (int(_x(k['time'])), ky(k['value']))
			_circle(img, c, 5, (0.95, 0.9, 0.4), -1, cv2.LINE_AA)
			if k['id'] == sel_key:
				_circle(img, c, 9, SEL, 2, cv2.LINE_AA)
		_text(img, lane.replace('.', '  '), gut + 10, ly + 16, TEXT, 0.42)
		_text(img, '%.3g .. %.3g' % (lo, hi), gut + 10, ly + LANE_H - 8, DIM, 0.34)
		ly += LANE_H + 6

	if xe < w:
		_line(img, (xe, HEADER_H), (xe, hb), DIM, 1)
	# playhead
	if gut <= xp < w:
		_line(img, (xp, HEADER_H), (xp, hb), HEAD, 2)
		_rect(img, (xp - 1, HEADER_H), (xp + 52, HEADER_H + 14), HEAD, -1)
		_text(img, _fmt(t_now), xp + 3, HEADER_H + 11, (1, 1, 1), 0.36)

	_draw_overview(img, allc, length, vs, vl, t_now)

	# uint8 RGBA drawn top-down -> TD textures are bottom-up
	scriptOp.copyNumpyArray(np.ascontiguousarray(img[::-1]))


def _ov_span(length):
	"""Seconds covered by the overview: the show, or more if cues/view go past."""
	return max(length, _view['vs'] + _view['vl'], 1.0)


def _draw_overview(img, allc, length, vs, vl, t_now):
	"""Whole show in one strip: cue blocks (main track), the visible window,
	the end of the show and the playhead."""
	h, w = img.shape[:2]
	y0, y1 = h - OV_H, h - 1
	span = _ov_span(length)
	_view['ov'] = (y0, span)

	def ox(t):
		return int(t / span * (w - 1))

	_rect(img, (0, y0 - 6), (w, h), PANEL, -1)
	main = getattr(_sl(), 'MAIN_TRACK', '')
	cs = [c for c in allc if c.get('track', main) == main]
	for i, c in enumerate(cs):
		end = cs[i + 1]['time'] if i + 1 < len(cs) else length
		col = _scene_color(c['scene'])
		_rect(img, (ox(c['time']), y0 + 4), (max(ox(c['time']) + 1, ox(end)), y1 - 4), tuple(v * 0.6 for v in col), -1)
		_line(img, (ox(c['time']), y0 + 4), (ox(c['time']), y1 - 4), col, 1)
	if length < span:
		_rect(img, (ox(length), y0 + 4), (w, y1 - 4), tuple(v * 0.45 for v in BG), -1)
	_rect(img, (ox(vs), y0 + 1), (ox(vs + vl), y1 - 1), SEL, 1)
	_line(img, (ox(t_now), y0), (ox(t_now), y1), HEAD, 2)


# ---------------------------------------------------------------- input

def _snap(t):
	return max(0.0, round(t / SNAP) * SNAP)


def _xy(panel):
	return float(panel.u) * _view.get('w', 1), (1.0 - float(panel.v)) * _view.get('h', 1)


def on_press(panel):
	if 'w' not in _view:
		return
	x, y = _xy(panel)
	p = _show().par
	cue_top = HEADER_H + RULER_H + 4
	if 'ov' in _view and y >= _view['ov'][0] - 6:
		_drag.clear()
		_drag.update(kind='overview')
		_seek_overview(x)
		return
	if y < cue_top:
		_drag.clear()
		_drag.update(kind='seek')
		p.Time = _snap(_t(x))
		return
	for track, y0, y1 in _view.get('tracks', []):
		if not (y0 <= y <= y1):
			continue
		cs = [c for c in _cues() if c.get('track', track) == track]
		hit = None
		for i, c in enumerate(cs):
			end = cs[i + 1]['time'] if i + 1 < len(cs) else float(p.Length.eval())
			if _x(c['time']) - 4 <= x <= _x(end):
				hit = c
		if hit is not None:
			p.Cue = hit['id']
			_drag.clear()
			_drag.update(kind='cue', id=hit['id'], time=hit['time'], grab=_t(x) - hit['time'], moved=False)
		return
	for lane, y0, y1 in _view.get('lanes', []):
		if y0 <= y <= y1:
			p.Lane = lane
			for k in _sl().lanes().get(lane, []):
				if abs(_x(k['time']) - x) <= 8:
					p.Key = k['id']
					_drag.clear()
					_drag.update(kind='key', id=k['id'], lane=lane, time=k['time'], value=k['value'],
						y0=y0, y1=y1, moved=False)
					return
			return


def _seek_overview(x):
	"""Overview click: playhead there, view paged to it (as Follow does)."""
	p = _show().par
	t = _snap(max(0.0, min(1.0, x / float(_view['w']))) * _view['ov'][1])
	p.Time = t
	vl = _view['vl']
	if not (_view['vs'] <= t < _view['vs'] + vl):
		p.Viewstart = (t // vl) * vl


def on_move(panel):
	if not _drag:
		return
	x, y = _xy(panel)
	if _drag['kind'] == 'overview':
		_seek_overview(x)
	elif _drag['kind'] == 'seek':
		_show().par.Time = _snap(_t(x))
	elif _drag['kind'] == 'cue':
		_drag['time'] = _snap(_t(x) - _drag['grab'])
		_drag['moved'] = True
	elif _drag['kind'] == 'key':
		ks = _sl().lanes().get(_drag['lane'], [])
		lo, hi = _lane_range(_drag['lane'], ks)
		f = (_drag['y1'] - 6 - y) / float(_drag['y1'] - _drag['y0'] - 12)
		_drag['time'] = _snap(_t(x))
		_drag['value'] = round(lo + max(0.0, min(1.0, f)) * (hi - lo), 4)
		_drag['moved'] = True


def on_release(panel):
	d = dict(_drag)
	_drag.clear()
	if not d.get('moved'):
		return
	sl = _sl()
	try:
		if d['kind'] == 'cue':
			sl.update_cue(d['id'], time=d['time'])
		elif d['kind'] == 'key':
			sl.update_key(d['id'], time=d['time'], value=d['value'])
		sl.load_all()
	except ValueError as e:
		_show().par.Message = str(e)
