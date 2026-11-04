"""look_ui -- Look Rig tab of the Config window: one patch group at a time.

Left (group_list): every group of the dmx_patch `groups` table, with the
colour and label of the Fixture tab, its kind, how many lights it has and
their live colour; click = select. Top right (preview): the selected group's
lights with their live colour. Right (look_params): Parameter COMP on the
group's COMP, showing the look pars of its kind -- chase rigs: DMX Reactive +
Level/Dimmer gamma; level rigs: Level/Fan; heads: Level + the Look page.
The quick-patch pars stay out: the patch is edited in the Fixture tab.
Selection = par Group of tab_look.
"""
import numpy as np
import cv2

BG = (0.065, 0.07, 0.08)
PANEL = (0.09, 0.095, 0.11)
HOVER = (0.11, 0.12, 0.14)
SELBG = (0.16, 0.42, 0.62)
TEXT = (0.86, 0.88, 0.91)
DIM = (0.50, 0.53, 0.58)
FONT = cv2.FONT_HERSHEY_SIMPLEX
ROW_H, TOP = 58, 40
KIND_LABEL = {'chase': 'audio chase', 'level': 'livello', 'heads': 'teste mobili'}

# Parameter COMP pages per group kind; the quick-patch pars are left out
# (an explicit name list: '^name' exclusions are not applied by parscope)
PAGES = {'chase': ('DMX Reactive', 'Fixture'), 'level': ('Fixture',), 'heads': ('Heads', 'Look')}
QUICK = ('Fixtureprofile', 'Nbars', 'Count', 'Startaddress', 'Applyfixture', 'Outputport', 'Patchenable',
	'Profile', 'Addresses')


def _c(col):
	return tuple(int(max(0.0, min(1.0, v)) * 255) for v in col[:3]) + (255,)


def _text(img, s, x, y, color=TEXT, scale=0.45):
	cv2.putText(img, str(s), (int(x), int(y)), FONT, scale, _c(color), 1, cv2.LINE_AA)


def _rect(img, p1, p2, col, t=-1):
	cv2.rectangle(img, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), _c(col), t)


def _tab():
	return parent.Config.op('tab_look')


def _fxui():
	return parent.Config.op('tab_fixtures/fixture_ui').module


def _fl():
	return parent.Config.parent().op('dmx_patch/fixture_logic').module


def groups():
	"""[{group, label, kind, comp}] in the order of the groups table."""
	t = parent.Config.parent().op('dmx_patch/groups')
	out = []
	for r in range(1, t.numRows):
		g = t[r, 'group'].val
		out.append({'group': g, 'label': t[r, 'label'].val or g, 'kind': t[r, 'kind'].val,
			'comp': parent.Config.parent().op(t[r, 'comp'].val)})
	return out


def selected():
	"""The selected group's dict (first group when the par is empty/stale)."""
	gs = groups()
	cur = str(_tab().par.Group.eval())
	for g in gs:
		if g['group'] == cur:
			return g
	return gs[0] if gs else None


def group_comp():
	"""COMP shown by look_params (expression of its op par)."""
	g = selected()
	return g['comp'] if g else None


def page_scope():
	g = selected()
	pages = PAGES.get(g['kind'] if g else '')
	return ' '.join("'%s'" % p for p in pages) if pages else '*'


def par_scope():
	"""Names of the look pars of the selected group's COMP."""
	g = selected()
	pages = PAGES.get(g['kind'] if g else '')
	if not pages or g['comp'] is None:
		return '*'
	names = []   # tuplet names (Color, not Colorr Colorg Colorb), in page order
	for p in g['comp'].customPars:
		if p.page is not None and p.page.name in pages and p.name not in QUICK \
				and p.tupletName not in names:
			names.append(p.tupletName)
	return ' '.join(names) or '*'


def _fixtures(group):
	return sorted(_fl().rows(group), key=lambda f: (f['unit'], f['id']))


def _out(scriptOp, img):
	scriptOp.copyNumpyArray(np.ascontiguousarray(img[::-1]))


def render_groups(scriptOp):
	w = int(scriptOp.par.resolutionw.eval())
	h = int(scriptOp.par.resolutionh.eval())
	img = np.empty((h, w, 4), dtype=np.uint8)
	img[:] = _c(BG)
	_text(img, 'GRUPPI', 16, 27, DIM, 0.45)
	fxui = _fxui()
	sel = selected()
	panel = parent.Config.op('tab_look/group_list').panel
	hover = int(((1.0 - float(panel.v)) * h - TOP) // ROW_H) if panel.inside else None
	for i, g in enumerate(groups()):
		y0 = TOP + i * ROW_H
		if y0 + ROW_H > h:
			break
		if sel and g['group'] == sel['group']:
			_rect(img, (0, y0), (w, y0 + ROW_H - 4), SELBG)
		elif i == hover:
			_rect(img, (0, y0), (w, y0 + ROW_H - 4), HOVER)
		_rect(img, (0, y0), (5, y0 + ROW_H - 4), fxui._gcol(g['group']))
		_text(img, g['label'], 16, y0 + 22, TEXT, 0.5)
		fx = _fixtures(g['group'])
		info = '%s  -  %d luci' % (KIND_LABEL.get(g['kind'], g['kind']), len(fx))
		if g['comp'] is None:
			info = 'COMP mancante: %s' % g['group']
		_text(img, info, 16, y0 + 44, DIM, 0.38)
		# live colour of up to 8 lights, right aligned
		for k, f in enumerate(fx[:8]):
			x1 = w - 10 - k * 13
			_rect(img, (x1 - 10, y0 + 9), (x1, y0 + 19), fxui._live_rgb(f))
	_out(scriptOp, img)


def render_preview(scriptOp):
	w = int(scriptOp.par.resolutionw.eval())
	h = int(scriptOp.par.resolutionh.eval())
	img = np.empty((h, w, 4), dtype=np.uint8)
	img[:] = _c(PANEL)
	g = selected()
	if g is None:
		_out(scriptOp, img)
		return
	fxui = _fxui()
	fx = _fixtures(g['group'])
	_rect(img, (0, 0), (5, h), fxui._gcol(g['group']))
	_text(img, g['label'], 16, 26, TEXT, 0.6)
	_text(img, '%s   %s   %d luci' % (KIND_LABEL.get(g['kind'], g['kind']),
		g['comp'].name if g['comp'] is not None else '-', len(fx)), 16, 48, DIM, 0.4)
	if not fx:
		_text(img, 'nessuna luce in patch per questo gruppo (tab Fixture > Add Fixture)', 16, h - 20, DIM, 0.42)
		_out(scriptOp, img)
		return
	x0, top, bot = 16, 58, h - 22
	tw = max(18, min(90, (w - x0 - 10) // len(fx) - 6))
	for i, f in enumerate(fx):
		x = x0 + i * (tw + 6)
		if x + tw > w - 6:
			_text(img, '+%d' % (len(fx) - i), x, bot - 8, DIM, 0.42)
			break
		_rect(img, (x, top), (x + tw, bot), fxui._live_rgb(f))
		_rect(img, (x, top), (x + tw, bot), fxui._gcol(g['group']), 1)
		if tw >= 40:
			_text(img, f['name'][:8], x + 2, h - 6, DIM, 0.36)
	_out(scriptOp, img)


def on_click(panel_comp):
	h = float(panel_comp.height)
	i = int(((1.0 - float(panel_comp.panel.v)) * h - TOP) // ROW_H)
	gs = groups()
	if 0 <= i < len(gs):
		_tab().par.Group = gs[i]['group']
