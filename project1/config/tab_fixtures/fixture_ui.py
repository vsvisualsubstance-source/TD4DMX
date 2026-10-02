"""fixture_ui -- Fixture tab of the Config window (parent COMP = the tab).

Three views over /project1/dmx_patch (fixture_logic + patch_report):
- plan:  stage plan, one tile per fixture at its x/y (grid cells, y up),
         live colour from the generators; click = select, drag = move.
- umap:  512-cell map (32 x 16) of one Art-Net port; every fixture is a block
         of its channels; click = select, drag = re-address. Overlaps red.
- inspector: the tab's 'Fixture' page (parameterCOMP), edits the selected
         fixture in place; Add / Duplicate / Remove / Auto address pulses.

Drags are kept here (_drag) and committed to the table on release only:
the fixtures table is file-synced, no disk write per mouse move.

Rendering: render_plan / render_umap are called by the Script TOPs' onCook;
they draw top-down with OpenCV into uint8 RGBA (float32 canvases cost ~20 ms
a cook in conversion) and flip to TD's bottom-up texture order.
"""
import numpy as np
import cv2

GROUP_COLORS = {
	'rig_a': (0.20, 0.72, 0.95),
	'rig_b': (0.98, 0.60, 0.18),
	'heads': (0.82, 0.38, 0.98),
}
OTHER = (0.6, 0.6, 0.6)
BG = (0.065, 0.07, 0.08)
GRID = (0.12, 0.13, 0.15)
GRID_MAJOR = (0.19, 0.20, 0.23)
TEXT = (0.86, 0.88, 0.91)
DIM = (0.50, 0.53, 0.58)
BAD = (0.95, 0.26, 0.24)
SEL = (1.0, 1.0, 1.0)
FONT = cv2.FONT_HERSHEY_SIMPLEX

UMAP_COLS, UMAP_ROWS = 32, 16


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

_drag = {}    # active drag: {'view', 'id', 'x', 'y', 'address', 'grab'}
_view = {}    # last plan transform: x0, y0, s, w, h


# ---------------------------------------------------------------- lookups

def _tab():
	return me.parent()


def _patch():
	return parent.Config.parent().op('dmx_patch')


def _fl():
	return _patch().op('fixture_logic').module


def _report():
	"""{fixture id: patch_report row dict}"""
	rep = _patch().op('patch_report')
	head = [c.val for c in rep.row(0)]
	return {int(rep[r, 'id'].val): {h: rep[r, h].val for h in head} for r in range(1, rep.numRows)}


def selected():
	return int(_tab().par.Selected.eval())


def _nchans(f):
	return len(_fl().profile_channels(f['group'], f['profile']) or []) or 1


def map_port():
	"""Port shown by the universe map: the Mapport menu, or (auto) the
	selected fixture's port, else the first port in use."""
	p = str(_tab().par.Mapport.eval())
	if p and p != 'auto':
		return p
	fx = _fl().rows()
	sel = [f for f in fx if f['id'] == selected()]
	if sel:
		return sel[0]['port_id']
	return fx[0]['port_id'] if fx else ''


# ---------------------------------------------------------------- live colour

def _live_rgb(f):
	"""Current output colour of a fixture's unit, 0..1 (approximate: what the
	generator sends, dimmer applied)."""
	home = _patch().parent()
	g = _fl().group_info(f['group'])
	comp = home.op(g['comp']) if g else None
	if comp is None:
		return (0.0, 0.0, 0.0)
	if f['group'] == 'heads':
		p = comp.par
		d = float(p.Dimmer.eval())
		chans = _fl().profile_channels(f['group'], f['profile']) or []
		if 'red' in chans:
			return (float(p.Colorr.eval()) * d, float(p.Colorg.eval()) * d, float(p.Colorb.eval()) * d)
		return (d, d, d)
	gen = comp.op('dmx_generator')
	if gen is None:
		return (0.0, 0.0, 0.0)
	pre = 'bar%d_' % f['unit']

	def ch(n, dflt):
		c = gen[pre + n]
		return float(c[0]) / 255.0 if c is not None else dflt

	d = ch('dimmer', 1.0)
	w = ch('white', 0.0)
	return tuple(min(1.0, (ch(n, 0.0) + w) * d) for n in ('red', 'green', 'blue'))


# ---------------------------------------------------------------- drawing

def _img(w, h):
	img = np.empty((h, w, 4), dtype=np.uint8)
	img[:] = _c(BG)
	return img


def _out(scriptOp, img):
	# uint8 RGBA, drawn top-down -> TD textures are bottom-up
	scriptOp.copyNumpyArray(np.ascontiguousarray(img[::-1]))


def _text(img, s, x, y, color=TEXT, scale=0.42, thick=1):
	cv2.putText(img, str(s), (int(x), int(y)), FONT, scale, _c(color), thick, cv2.LINE_AA)


def _positions():
	"""Fixture positions with the active plan drag applied."""
	out = []
	for f in _fl().rows():
		if _drag.get('view') == 'plan' and _drag.get('id') == f['id']:
			f = dict(f, x=_drag['x'], y=_drag['y'])
		out.append(f)
	return out


def render_plan(scriptOp):
	w = int(scriptOp.par.resolutionw.eval())
	h = int(scriptOp.par.resolutionh.eval())
	img = _img(w, h)
	fx = _positions()
	rep = _report()
	sel = selected()
	xs = [f['x'] for f in fx] or [0.0]
	ys = [f['y'] for f in fx] or [0.0]
	x0, x1 = min(xs) - 1.5, max(xs) + 1.5
	y0, y1 = min(ys) - 1.5, max(ys) + 1.5
	# at least 12 x 6 cells, centred
	if x1 - x0 < 12:
		c = (x0 + x1) / 2
		x0, x1 = c - 6, c + 6
	if y1 - y0 < 6:
		c = (y0 + y1) / 2
		y0, y1 = c - 3, c + 3
	s = min(w / (x1 - x0), (h - 24) / (y1 - y0))
	ox = (w - (x1 - x0) * s) / 2 - x0 * s
	oy = 24 + ((h - 24) - (y1 - y0) * s) / 2 + y1 * s   # image row of world y=0
	_view.update(ox=ox, oy=oy, s=s, w=w, h=h)

	def to_px(x, y):
		return ox + x * s, oy - y * s

	# grid: 1 cell minor, 4 cells major
	for gx in range(int(np.floor(x0)), int(np.ceil(x1)) + 1):
		px, _ = to_px(gx, 0)
		_line(img, (int(px), 24), (int(px), h), GRID_MAJOR if gx % 4 == 0 else GRID, 1)
	for gy in range(int(np.floor(y0)), int(np.ceil(y1)) + 1):
		_, py = to_px(0, gy)
		_line(img, (0, int(py)), (w, int(py)), GRID_MAJOR if gy % 4 == 0 else GRID, 1)
	# stage front marker
	_, py0 = to_px(0, y0 + 0.3)
	_text(img, 'FRONTE PALCO / PUBBLICO', 10, min(h - 6, int(py0)), DIM, 0.4)

	half = max(10, s * 0.42)
	for f in sorted(fx, key=lambda f: f['id'] == sel):
		cx, cy = to_px(f['x'], f['y'])
		gcol = GROUP_COLORS.get(f['group'], OTHER)
		st = rep.get(f['id'], {}).get('status', '')
		sending = st in ('ok', 'offline', 'conflict')
		p1 = (int(cx - half), int(cy - half * 0.62))
		p2 = (int(cx + half), int(cy + half * 0.62))
		if sending:
			live = _live_rgb(f)
			_rect(img, p1, p2, tuple(0.12 + 0.88 * c for c in live), -1)
			lum = 0.3 * live[0] + 0.6 * live[1] + 0.1 * live[2]
			tc = (0.05, 0.05, 0.05) if lum > 0.55 else TEXT
			border = BAD if st == 'conflict' else gcol
		else:
			# not sent (fixture/group off, no port, overflow...): hollow tile
			_rect(img, p1, p2, (0.09, 0.095, 0.105), -1)
			tc = DIM
			border = tuple(c * 0.55 for c in gcol) if st == 'off' else BAD
		_rect(img, p1, p2, border, 2)
		if f['id'] == sel:
			_rect(img, (p1[0] - 4, p1[1] - 4), (p2[0] + 4, p2[1] + 4), SEL, 2)
		_text(img, f['name'], p1[0] + 6, p1[1] + 17, tc, 0.45)
		_text(img, 'U%d  @%d' % (f['unit'], f['address']) if sending else '%s @%d' % (st.upper(), f['address']),
			p1[0] + 6, p2[1] - 7, tc, 0.38)
		if f['palette']:   # own palette (not the rig's): name above the tile
			_text(img, f['palette'][:14], p1[0], p1[1] - 5, gcol, 0.36)

	# header: legend
	x = 10
	for g, col in GROUP_COLORS.items():
		_rect(img, (x, 7), (x + 12, 19), col, -1)
		_text(img, g, x + 17, 18, TEXT, 0.42)
		x += 95
	_text(img, 'click = seleziona, trascina = sposta (griglia 0.5)', x + 10, 18, DIM, 0.4)
	_out(scriptOp, img)


def render_umap(scriptOp):
	w = int(scriptOp.par.resolutionw.eval())
	h = int(scriptOp.par.resolutionh.eval())
	img = _img(w, h)
	head = 26
	_view['umap_h'] = float(h)
	cw = w / float(UMAP_COLS)
	ch = (h - head) / float(UMAP_ROWS)
	port = map_port()
	fl = _fl()
	rep = _report()
	sel = selected()
	fx = [f for f in fl.rows() if f['port_id'] == port]
	if _drag.get('view') == 'umap':
		fx = [dict(f, address=_drag['address']) if f['id'] == _drag['id'] else f for f in fx]
	owner = [[] for _ in range(512)]
	for f in fx:
		for a in range(f['address'], f['address'] + _nchans(f)):
			if 1 <= a <= 512:
				owner[a - 1].append(f)

	def cell(a):
		i = a - 1
		cx, cy = (i % UMAP_COLS) * cw, head + (i // UMAP_COLS) * ch
		return int(cx) + 1, int(cy) + 1, int(cx + cw) - 1, int(cy + ch) - 1

	used = 0
	for a in range(1, 513):
		x0, y0, x1, y1 = cell(a)
		own = owner[a - 1]
		if not own:
			_rect(img, (x0, y0), (x1, y1), GRID, -1)
			if a % 8 == 1:
				_text(img, a, x0 + 2, y1 - 4, DIM, 0.3)
			continue
		used += 1
		f = own[-1]
		col = GROUP_COLORS.get(f['group'], OTHER)
		live = [o for o in own if rep.get(o['id'], {}).get('status') in ('ok', 'offline', 'conflict')]
		if len(live) > 1:
			col = BAD
		elif not live:
			col = tuple(c * 0.35 for c in col)   # in the patch but not sent
		_rect(img, (x0, y0), (x1, y1), col, -1)
		if a == f['address']:
			_rect(img, (x0, y0), (x0 + 3, y1), (0.02, 0.02, 0.02), -1)
			_text(img, a, x0 + 5, y1 - 4, (0.03, 0.03, 0.03), 0.32)
	# selected fixture outline (may wrap rows: outline every cell edge)
	for f in fx:
		if f['id'] != sel:
			continue
		for a in range(f['address'], min(512, f['address'] + _nchans(f) - 1) + 1):
			x0, y0, x1, y1 = cell(a)
			_rect(img, (x0 - 1, y0 - 1), (x1 + 1, y1 + 1), SEL, 1)
	pinfo = ''
	ports = _patch().op('ports')
	if ports is not None and ports[port, 'label'] is not None:
		pinfo = ports[port, 'label'].val + ('' if ports[port, 'online'].val == '1' else '  [OFFLINE]')
	conflicts = sum(1 for f in fx if rep.get(f['id'], {}).get('status') == 'conflict')
	_text(img, 'Porta %s   %s' % (port or '-', pinfo), 8, 17, TEXT, 0.42)
	_text(img, 'usati %d / 512   liberi %d%s' % (used, 512 - used,
		'   CONFLITTI: %d fixture' % conflicts if conflicts else ''),
		w - 330, 17, BAD if conflicts else DIM, 0.42)
	_out(scriptOp, img)


# ---------------------------------------------------------------- input

def _plan_world(u, v):
	px, py = u * _view.get('w', 1), (1.0 - v) * _view.get('h', 1)
	s = _view.get('s', 1.0) or 1.0
	return (px - _view.get('ox', 0)) / s, (_view.get('oy', 0) - py) / s


def _plan_hit(u, v):
	x, y = _plan_world(u, v)
	best, bd = None, 0.55
	for f in _fl().rows():
		d = max(abs(f['x'] - x), abs(f['y'] - y) / 0.62)
		if d < bd:
			best, bd = f, d
	return best


def _umap_address(u, v):
	h = _view.get('umap_h', 442.0)
	head = 26.0 / h
	if v > 1.0 - head:
		return None
	col = min(UMAP_COLS - 1, max(0, int(u * UMAP_COLS)))
	row = min(UMAP_ROWS - 1, max(0, int(((1.0 - head) - v) / (1.0 - head) * UMAP_ROWS)))
	return row * UMAP_COLS + col + 1


def _umap_hit(addr):
	port = map_port()
	for f in reversed(_fl().rows()):
		if f['port_id'] == port and f['address'] <= addr < f['address'] + _nchans(f):
			return f
	return None


def _snap(v, step=0.5):
	return round(v / step) * step


def on_press(view, panel):
	u, v = float(panel.u), float(panel.v)
	if view == 'plan':
		f = _plan_hit(u, v)
		if f is None:
			return
		x, y = _plan_world(u, v)
		_drag.clear()
		_drag.update(view='plan', id=f['id'], x=f['x'], y=f['y'], grab=(f['x'] - x, f['y'] - y))
	else:
		a = _umap_address(u, v)
		f = _umap_hit(a) if a else None
		if f is None:
			return
		_drag.clear()
		_drag.update(view='umap', id=f['id'], address=f['address'], grab=a - f['address'])
	select(f['id'])


def on_move(view, panel):
	if _drag.get('view') != view:
		return
	u, v = float(panel.u), float(panel.v)
	if view == 'plan':
		x, y = _plan_world(u, v)
		_drag['x'] = _snap(x + _drag['grab'][0])
		_drag['y'] = _snap(y + _drag['grab'][1])
	else:
		a = _umap_address(u, v)
		if a:
			f = [f for f in _fl().rows() if f['id'] == _drag['id']][0]
			n = _nchans(f)
			_drag['address'] = max(1, min(512 - n + 1, a - _drag['grab']))


def on_release(view, panel):
	d = dict(_drag)
	_drag.clear()
	if d.get('view') != view:
		return
	try:
		if view == 'plan':
			_fl().update_fixture(d['id'], x=d['x'], y=d['y'])
		else:
			_fl().update_fixture(d['id'], address=d['address'])
	except ValueError as e:
		_tab().par.Message = str(e)
	load_selected()


# ---------------------------------------------------------------- inspector

FIELDS = [  # (par, column)
	('Fgroup', 'group'), ('Fname', 'name'), ('Funit', 'unit'), ('Fprofile', 'profile'),
	('Fport', 'port_id'), ('Faddress', 'address'), ('Fx', 'x'), ('Fy', 'y'), ('Fenabled', 'enabled'),
	('Fpalette', 'palette'),
]
RIG_PALETTE = '_rig'   # Fpalette menu entry for "use the rig's palette" (table: '')


def profile_menu():
	"""menuSource of Fprofile: the library of the inspector's group."""
	t = _fl().profile_table(str(_tab().par.Fgroup.eval()))
	return tdu.TableMenu(t) if t is not None else tdu.TableMenu(_patch().op('groups'))


def palette_menu():
	"""menuSource of Fpalette: the rig's palettes + 'use the rig's'."""
	names = _fl().palette_names(str(_tab().par.Fgroup.eval()))
	return _Menu([RIG_PALETTE] + names, ['(palette del rig)'] + names)


def port_menu():
	return tdu.TableMenu(_patch().op('ports'), labelCol='label')


def mapport_menu():
	ports = _patch().op('ports')
	names = ['auto'] + [ports[r, 'port_id'].val for r in range(1, ports.numRows)]
	labels = ['Segui selezione'] + [ports[r, 'label'].val for r in range(1, ports.numRows)]
	return _Menu(names, labels)


class _Menu:
	def __init__(self, names, labels):
		self.menuNames = names
		self.menuLabels = labels


def select(fid):
	_tab().par.Selected = int(fid)
	load_selected()


def load_selected():
	"""Copy the selected fixture into the inspector pars. The parexec sees
	values equal to the table and writes nothing back."""
	tab = _tab()
	f = [f for f in _fl().rows() if f['id'] == selected()]
	if not f:
		return
	f = f[0]
	for par_name, col in FIELDS:
		p = tab.par[par_name]
		v = f[col]
		if p.style == 'Toggle':
			v = bool(v)
		if par_name == 'Fpalette' and not v:
			v = RIG_PALETTE
		if str(p.eval()) != str(v):
			p.val = v
	tab.par.Message = ''


def on_field_change(par):
	"""Inspector par edited -> write that field of the selected fixture."""
	fl = _fl()
	fid = selected()
	f = [f for f in fl.rows() if f['id'] == fid]
	if not f:
		return
	f = f[0]
	col = dict(FIELDS)[par.name]
	val = par.eval()
	if par.style == 'Toggle':
		val = 1 if val else 0
	if par.name == 'Fpalette' and val == RIG_PALETTE:
		val = ''
	if str(val) == str(f[col]) or (par.style == 'Float' and abs(float(val) - float(f[col])) < 1e-6):
		return
	changes = {col: val}
	if col == 'group':
		# another library: keep the profile if it exists there, else the first
		if fl.profile_channels(val, f['profile']) is None:
			names = fl.profile_names(val)
			changes['profile'] = names[0] if names else ''
		changes['unit'] = max([0] + [x['unit'] for x in fl.rows(val)]) + 1
		if f['palette'] and f['palette'] not in fl.palette_names(val):
			changes['palette'] = ''   # e.g. moved to the heads: no palette there
	try:
		fl.update_fixture(fid, **changes)
		_tab().par.Message = ''
	except ValueError as e:
		_tab().par.Message = str(e)
		load_selected()
		return
	if col == 'group':
		load_selected()


def on_pulse(par):
	fl = _fl()
	tab = _tab()
	cur = [f for f in fl.rows() if f['id'] == selected()]
	cur = cur[0] if cur else None
	try:
		if par.name == 'Add':
			g = str(tab.par.Fgroup.eval())
			select(fl.add_fixture(g, profile=cur['profile'] if cur and cur['group'] == g else None))
		elif par.name == 'Duplicate' and cur:
			select(fl.add_fixture(cur['group'], profile=cur['profile'], port_id=cur['port_id'],
				x=cur['x'] + 1, y=cur['y'], name=cur['name'] + ' copia'))
		elif par.name == 'Remove' and cur:
			same = [f for f in fl.rows(cur['group']) if f['id'] != cur['id']]
			fl.remove_fixture(cur['id'])
			if same:
				select(same[-1]['id'])
		elif par.name == 'Autoaddress' and cur:
			fx = [f for f in fl.rows(cur['group']) if f['port_id'] == cur['port_id']]
			fl.auto_address(cur['group'], min(f['address'] for f in fx) if fx else 1)
			load_selected()
		tab.par.Message = ''
	except ValueError as e:
		tab.par.Message = str(e)


def status_text():
	"""Read-only status line of the inspector."""
	rep = _report()
	r = rep.get(selected())
	if r is None:
		return 'nessuna fixture selezionata'
	s = '%s: %s  DMX %s-%s (%s ch)' % (r['name'], r['status'].upper(), r['start'], r['end'], r['nchans'])
	if r['universe'] != '':
		s += '  universo %s:%s:%s' % (r['net'], r['subnet'], r['universe'])
	return s
