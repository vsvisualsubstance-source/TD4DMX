"""timeline_ui -- Timeline tab of the Config window: draws /project1/show
(cues, automation lanes, playhead) and turns mouse input into edits.

Canvas rows, top to bottom: header (status), ruler (click/drag = seek), cue
lane (block per cue until the next one, fade ramp at its start; click =
select, drag = move in time), one row per automation lane (curve + keys;
click = select key / lane, drag a key = time + value).
Drags are previewed here and committed on release (file-synced tables).
View = show pars Viewstart / Viewlength / Follow (paging while playing).
"""
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


def _text(img, s, x, y, color=TEXT, scale=0.42):
	cv2.putText(img, str(s), (int(x), int(y)), FONT, scale, _c(color), 1, cv2.LINE_AA)


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
	return (t - _view['vs']) / _view['vl'] * _view['w']


def _t(x):
	return _view['vs'] + x / float(_view['w']) * _view['vl']


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
	_view.update(vs=vs, vl=vl, w=w, h=h)
	length = float(p.Length.eval())
	t_now = float(p.Time.eval())
	sel_cue, sel_key = int(p.Cue.eval()), int(p.Key.eval())
	sel_lane = str(p.Lane.eval())
	# beyond the end of the show: darker background, drawn first
	xe = int(_x(length))
	if xe < w:
		img[HEADER_H:, max(0, xe):] = _c(tuple(v * 0.45 for v in BG))

	# header
	_text(img, p.Status.eval(), 10, 20, TEXT, 0.48)
	msg = p.Message.eval()
	if msg:
		_text(img, msg, w - 10 - 8 * len(msg), 20, HEAD, 0.42)

	# ruler: tick step from zoom
	y0 = HEADER_H
	_rect(img, (0, y0), (w, y0 + RULER_H), PANEL, -1)
	step = next(s for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600) if vl / s <= 24)
	t = (vs // step) * step
	while t <= vs + vl:
		x = int(_x(t))
		_line(img, (x, y0 + RULER_H - 8), (x, y0 + RULER_H), DIM, 1)
		_line(img, (x, y0 + RULER_H), (x, h), GRID, 1)
		_text(img, _fmt(t), x + 3, y0 + 14, DIM, 0.36)
		t += step

	# cue lane
	cy0, cy1 = HEADER_H + RULER_H + 4, HEADER_H + RULER_H + 4 + CUE_H
	cs = _cues()
	scenes = {s['name']: s for s in sl.scenes()}
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
		label = scenes.get(c['scene'], {}).get('label', c['scene'])
		_text(img, c['label'] or ('cue %d' % c['id']), x0 + 6, cy0 + 18, TEXT, 0.45)
		_text(img, label, x0 + 6, cy0 + 38, TEXT, 0.42)
		_text(img, '%s  fade %.1fs' % (_fmt(c['time']), c['fade']), x0 + 6, cy1 - 8, DIM, 0.36)
	if not cs:
		_text(img, 'nessuna cue: Scene > New Scene From Live, poi Cue > Add Cue At Playhead', 12, cy0 + 48, DIM, 0.45)

	# automation lanes
	_view['lanes'] = []
	ly = cy1 + 8
	for lane, ks in _lanes().items():
		if ly + LANE_H > h:
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
		_text(img, lane.replace('.', '  '), 10, ly + 16, TEXT, 0.42)
		_text(img, '%.3g .. %.3g' % (lo, hi), 10, ly + LANE_H - 8, DIM, 0.34)
		ly += LANE_H + 6

	if xe < w:
		_line(img, (xe, HEADER_H), (xe, h), DIM, 1)
	# playhead
	xp = int(_x(t_now))
	if 0 <= xp < w:
		_line(img, (xp, HEADER_H), (xp, h), HEAD, 2)
		_rect(img, (xp - 1, HEADER_H), (xp + 52, HEADER_H + 14), HEAD, -1)
		_text(img, _fmt(t_now), xp + 3, HEADER_H + 11, (1, 1, 1), 0.36)

	# uint8 RGBA drawn top-down -> TD textures are bottom-up
	scriptOp.copyNumpyArray(np.ascontiguousarray(img[::-1]))


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
	if y < cue_top:
		_drag.clear()
		_drag.update(kind='seek')
		p.Time = _snap(_t(x))
		return
	if y < cue_top + CUE_H:
		cs = _cues()
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


def on_move(panel):
	if not _drag:
		return
	x, y = _xy(panel)
	if _drag['kind'] == 'seek':
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
