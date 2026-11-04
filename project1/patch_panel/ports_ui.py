"""ports_ui -- 'Rete DMX': the DMX output ports of dmx_patch (Art-Net ports
found by the scan + USB interfaces), one row each: online state, node, IP,
Art-Net address and universe, how many lights / channels the patch puts on
it, conflicts, last time it was seen. Click a row = open the Fixture tab of
the Config window on that port's universe map (tab_fixtures Mapport).
Data: dmx_patch ports / fixtures / patch_report (read only).
"""
import numpy as np
import cv2

BG = (0.065, 0.07, 0.08)
ROWBG = (0.085, 0.09, 0.105)
HOVER = (0.11, 0.12, 0.14)
TEXT = (0.86, 0.88, 0.91)
DIM = (0.50, 0.53, 0.58)
OK = (0.35, 0.85, 0.45)
BAD = (0.95, 0.26, 0.24)
FONT = cv2.FONT_HERSHEY_SIMPLEX
HEAD_H, COLS_H, ROW_H = 34, 24, 34
# (title, x) of the columns
COLS = [('', 12), ('PORTA', 34), ('IP', 430), ('ART-NET', 560), ('U', 660), ('LUCI', 710),
	('CANALI', 770), ('CONFLITTI', 880), ('ULTIMA VOLTA', 990)]
REF_W = 1150   # the column x above are for this width; narrower panels scale them

_view = {}


def _c(col):
	return tuple(int(max(0.0, min(1.0, v)) * 255) for v in col[:3]) + (255,)


def _text(img, s, x, y, color=TEXT, scale=0.42, maxw=None):
	s = str(s)
	if maxw is not None:
		while len(s) > 3 and cv2.getTextSize(s, FONT, scale, 1)[0][0] > maxw:
			s = s[:-2]
	cv2.putText(img, s, (int(x), int(y)), FONT, scale, _c(color), 1, cv2.LINE_AA)


def _patch():
	return me.parent().parent().op('dmx_patch')


def _config():
	return me.parent().parent().op('config')


def _when(stamp):
	"""'2026-10-31 19:56:41' -> '31/10 19:56' ('mai' when never seen)."""
	s = str(stamp or '')
	if len(s) >= 16 and s[4] == '-':
		return '%s/%s %s' % (s[8:10], s[5:7], s[11:16])
	return s or 'mai'


def rows():
	"""[{port_id, label, node, ip, artnet, universe, online, last_seen, kind,
	lights, channels, conflicts}] in ports-table order."""
	patch = _patch()
	t = patch.op('ports')
	fl = patch.op('fixture_logic').module
	rep = patch.op('patch_report')
	status = {}
	if rep is not None and rep.numRows > 1 and rep[0, 'id'] is not None:
		status = {rep[r, 'id'].val: rep[r, 'status'].val for r in range(1, rep.numRows)}
	fx = fl.rows()
	out = []
	for r in range(1, t.numRows if t is not None else 0):
		pid = t[r, 'port_id'].val
		mine = [f for f in fx if f['port_id'] == pid]
		chans = set()
		for f in mine:
			n = len(fl.profile_channels(f['group'], f['profile']) or [])
			chans.update(a for a in range(f['address'], f['address'] + n) if 1 <= a <= 512)
		net, sub, uni = (t[r, k].val for k in ('net', 'subnet', 'universe'))
		out.append({
			'port_id': pid, 'label': t[r, 'label'].val, 'node': t[r, 'node'].val, 'ip': t[r, 'ip'].val,
			'artnet': '%s:%s:%s' % (net, sub, uni), 'kind': t[r, 'kind'].val,
			'universe': int(uni) + 1 if net == '0' and sub == '0' and uni.isdigit() else None,
			'online': t[r, 'online'].val == '1', 'last_seen': t[r, 'last_seen'].val,
			'lights': len(mine), 'channels': len(chans),
			'conflicts': sum(1 for f in mine if status.get(str(f['id'])) == 'conflict')})
	return out


def render(scriptOp):
	w = int(scriptOp.par.resolutionw.eval())
	h = int(scriptOp.par.resolutionh.eval())
	img = np.empty((h, w, 4), dtype=np.uint8)
	img[:] = _c(BG)
	rs = rows()
	_view.update(w=w, h=h, rows=[r['port_id'] for r in rs])
	on = sum(1 for r in rs if r['online'])
	_text(img, 'PORTE DI USCITA', 12, 23, TEXT, 0.5)
	_text(img, '%d online su %d   -   clic su una porta = la sua mappa nel tab Fixture' % (on, len(rs)),
		190, 23, DIM, 0.42)
	k = min(1.0, w / float(REF_W))
	X = [x if x <= 34 else int(34 + (x - 34) * k) for _t, x in COLS]   # dot + name column fixed
	y = HEAD_H
	for title, x in zip([c[0] for c in COLS], X):
		_text(img, title, x, y + 16, DIM, 0.36, w - x - 4)
	panel = me.parent().op('ports').panel
	hover = int(((1.0 - float(panel.v)) * h - HEAD_H - COLS_H) // ROW_H) if panel.inside else None
	y += COLS_H
	if not rs:
		_text(img, 'nessuna porta: Scan Network qui sopra, o un\'interfaccia USB nel dmx_patch', 34, y + 22, DIM, 0.45)
	for i, r in enumerate(rs):
		if y + ROW_H > h:
			_text(img, '... altre %d porte' % (len(rs) - i), 34, h - 8, DIM, 0.4)
			break
		cv2.rectangle(img, (0, y), (w, y + ROW_H - 3), _c(HOVER if i == hover else ROWBG), -1)
		cy = y + 21
		cv2.circle(img, (18, cy - 5), 6, _c(OK if r['online'] else BAD), -1, cv2.LINE_AA)
		name = r['node'] or r['label']
		if r['kind'] == 'artnet':
			name = '%s  -  porta %s' % (r['node'], r['port_id'].split(':')[-1])
		cells = [
			(name, TEXT if r['online'] else DIM, 0.44),
			(r['ip'] or r['kind'].upper(), DIM, 0.4),
			(r['artnet'] if r['kind'] == 'artnet' else '-', DIM, 0.4),
			(r['universe'] or '-', TEXT, 0.44),
			(r['lights'], TEXT if r['lights'] else DIM, 0.44),
			('%d / 512' % r['channels'], TEXT if r['channels'] else DIM, 0.42),
			(r['conflicts'] or '-', BAD if r['conflicts'] else DIM, 0.44),
			('online' if r['online'] else _when(r['last_seen']), OK if r['online'] else DIM, 0.4)]
		for j, (s, col, sc) in enumerate(cells):
			x = X[j + 1]
			nx = X[j + 2] if j + 2 < len(X) else w
			_text(img, s, x, cy, col, sc, nx - x - 8)
		y += ROW_H
	scriptOp.copyNumpyArray(np.ascontiguousarray(img[::-1]))


def on_click(panel_comp):
	h = float(panel_comp.height)
	i = int(((1.0 - float(panel_comp.panel.v)) * h - HEAD_H - COLS_H) // ROW_H)
	ids = _view.get('rows') or []
	if not 0 <= i < len(ids):
		return
	cfg = _config()
	tab = cfg.op('tab_fixtures') if cfg is not None else None
	if tab is None:
		return
	if ids[i] in tab.par.Mapport.menuNames:
		tab.par.Mapport = ids[i]
	cfg.par.Tab = 'fixtures'
