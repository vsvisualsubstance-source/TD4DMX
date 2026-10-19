"""head_programmer -- SELECTIVE control of the moving heads, shared by TD,
Plancia (OSC /mh/* on channel 5) and Gaia (heads_* params)
(GAIA_INTERFACE "TD/Win-PD, 23").

A HEAD = one unit of the heads group (head<n> of heads_dmx). Its KEY is the
uid of its first fixture (Plancia "p-..."), else "id:<fixture id>": stable
across re-patching, unlike the unit number.

  head_state      runtime (not on disk), one row per head that left the
                  global look:
                    mode    global  (no row) = moving_heads' own pars, as
                                    before (Pan/Tilt or PTZ, Look page)
                            manual  its own values below; a blank field
                                    falls back to the global one
                            follow  pan/tilt from the PTZ target of this
                                    head (mocap or pad), look as manual
                    pan, tilt       degrees from the head center
                    dimmer, red, green, blue, white, zoom, focus  0..1
                    color, gobo     wheel DMX value 0..255
                    strobe          0/1 (shutter at dmx_patch Stroberate)
  head_positions  position, label, head, pan, tilt: a named position =
                  pan/tilt PER HEAD (head = key, or * = any head without
                  its own row). Seeded with Plancia's 6 (Centro, Pubblico,
                  Palco, Cielo, Croce, Ventaglio), to calibrate on stage.
  head_presets    preset, label, head, <state fields>: full look of the
                  heads that were selected when stored.
  head_selections selection, label, heads (space-separated keys): named
                  sets ("sub-groups" of the heads: mh_sx, mh_fronte ...),
                  defined by Plancia (heads_selections) or in TD.

The current SELECTION is the Selection par of moving_heads (keys). Every
programming command acts on the selection; an empty selection = nothing.

Plancia normalized pan/tilt (-1..1, /mh/pantilt and its preview) = the
full mechanical range of the head's model (pan_range/2, tilt_range/2), with
tilt = -y of the pad, as in plancia/index.html.

Called by heads_dmx_callbacks (state per head), plancia_in/plancia_logic
(/mh/*), gaia_services/dmx_services (heads_*), the moving_heads Programmer
page (heads_callbacks).
"""
import math

STATE_COLS = ['head', 'mode', 'pan', 'tilt', 'dimmer', 'red', 'green', 'blue', 'white',
	'color', 'gobo', 'zoom', 'focus', 'strobe']
FIELDS = STATE_COLS[2:]
UNIT_FIELDS = ('dimmer', 'red', 'green', 'blue', 'white', 'zoom', 'focus')   # 0..1
MODES = ('global', 'manual', 'follow')
POS_COLS = ['position', 'label', 'head', 'pan', 'tilt']
PRESET_COLS = ['preset', 'label', 'head'] + FIELDS
SEL_COLS = ['selection', 'label', 'heads']

# Plancia's position names and formula (plancia/index.html POS / posOf),
# normalized [pan, tilt] for head i of n -- the first seed of head_positions
PLANCIA_POSITIONS = ['Centro', 'Pubblico', 'Palco', 'Cielo', 'Croce', 'Ventaglio']
PLANCIA_GOBOS = ['Open', 'Dots', 'Ring', 'Breakup', 'Prisma', 'Star']


def _plancia_pos(p, i, n):
	u = (i / (n - 1) * 2 - 1) if n > 1 else 0.0
	return [[-u * .32, .62], [u * .25, .98], [-u * .12, .45], [u * .45, -.75],
		[.42 if i % 2 else -.42, .55], [u * .85, .5]][p] if 0 <= p < 6 else [0.0, 0.5]


# ---------------------------------------------------------------- basics

def _comp():
	return me.parent()


def _fl():
	return _comp().parent().op('dmx_patch/fixture_logic').module


def _cat():
	return _comp().parent().op('dmx_patch/catalog_logic').module


def _f(v, d=None):
	try:
		return float(str(v))
	except (TypeError, ValueError):
		return d


def _table(name, cols):
	t = _comp().op(name)
	if t.numRows == 0 or t[0, 0] is None or t[0, 0].val != cols[0]:
		t.clear()
		t.appendRow(cols)
	for c in cols:
		if t[0, c] is None:
			t.appendCol([c] + [''] * (t.numRows - 1))
	return t


def heads():
	"""[{unit, key, uid, id, name, profile}] one per unit, unit order."""
	by_unit = {}
	for f in sorted(_fl().rows('heads'), key=lambda f: (f['unit'], f['id'])):
		by_unit.setdefault(f['unit'], f)
	return [{'unit': u, 'key': f['uid'] or 'id:%d' % f['id'], 'uid': f['uid'], 'id': f['id'],
		'name': f['name'], 'profile': f['profile']} for u, f in sorted(by_unit.items())]


def keys_by_unit():
	return {h['unit']: h['key'] for h in heads()}


def resolve(ref):
	"""Head key for a uid, a key, a fixture id, a unit ("u3" / "#3") or a
	name; None if no head matches."""
	s = str(ref).strip()
	hs = heads()
	for h in hs:
		if s in (h['key'], h['uid'], h['name']):
			return h['key']
	if s.startswith(('u', '#')) and s[1:].isdigit():
		for h in hs:
			if h['unit'] == int(s[1:]):
				return h['key']
	if s.lstrip('-').isdigit():
		try:
			fid = _fl().fixture_id(s)
		except ValueError:
			return None
		for f in _fl().rows('heads'):
			if f['id'] == fid:
				return keys_by_unit().get(f['unit'])
	return None


def _ranges(key):
	"""(pan_range, tilt_range) of the head's model (degrees)."""
	for h in heads():
		if h['key'] == key:
			m = _cat().model(h['profile'])
			if m and m['kind'] == 'heads':
				return m.get('pan_range', 540.0), m.get('tilt_range', 270.0)
	return 540.0, 270.0


# ---------------------------------------------------------------- selection

def selection():
	known = {h['key'] for h in heads()}
	return [k for k in str(_comp().par.Selection.eval()).split() if k in known]


def _set_selection(keys):
	order = [h['key'] for h in heads()]
	keys = [k for k in order if k in set(keys)]
	_comp().par.Selection = ' '.join(keys)
	return keys


def selections():
	t = _table('head_selections', SEL_COLS)
	return [{'selection': t[r, 'selection'].val, 'label': t[r, 'label'].val,
		'heads': t[r, 'heads'].val.split()} for r in range(1, t.numRows) if t[r, 'selection'].val.strip()]


def select(spec):
	"""Change the selection. spec: {'all': 1} | {'clear': 1} |
	{'heads': [refs]} (replace) | {'add': [refs]} | {'remove': [refs]} |
	{'set': name} (a named selection) | {'mask': [0/1, ...]} (k-th head in
	unit order). Unknown refs raise. Returns the new selection."""
	spec = dict(spec or {})
	cur = selection()
	if spec.get('all'):
		return _set_selection([h['key'] for h in heads()])
	if spec.get('clear'):
		return _set_selection([])
	if 'mask' in spec:
		order = [h['key'] for h in heads()]
		return _set_selection([order[k] for k, v in enumerate(spec['mask'])
			if k < len(order) and (_f(v, 0) or 0) >= 0.5])
	if 'set' in spec:
		name = str(spec['set']).strip()
		for s in selections():
			if s['selection'] == name:
				return _set_selection([k for k in (resolve(x) for x in s['heads']) if k])
		raise ValueError('selezione %r non esiste' % name)

	def keys(refs):
		refs = refs if isinstance(refs, (list, tuple)) else str(refs).split()
		out = []
		for r in refs:
			k = resolve(r)
			if k is None:
				raise ValueError('testa %r non trovata' % r)
			out.append(k)
		return out

	if 'heads' in spec:
		return _set_selection(keys(spec['heads']))
	if 'add' in spec:
		return _set_selection(cur + keys(spec['add']))
	if 'remove' in spec:
		gone = set(keys(spec['remove']))
		return _set_selection([k for k in cur if k not in gone])
	raise ValueError('selezione: serve all, clear, heads, add, remove, set o mask')


def set_selections(items, source='plancia'):
	"""Replace the named selections: [{selection, label?, heads: [refs]}].
	Refs are stored as keys; unknown heads raise."""
	rows, seen = [], set()
	for it in items or []:
		d = dict(it)
		name = str(d.get('selection') or d.get('name') or '').strip()
		if not name or ' ' in name or '\t' in name:
			raise ValueError('selezione: nome %r non valido (senza spazi)' % name)
		if name in seen:
			raise ValueError('selezione %s ripetuta' % name)
		seen.add(name)
		refs = d.get('heads') or []
		refs = refs if isinstance(refs, (list, tuple)) else str(refs).split()
		ks = []
		for r in refs:
			k = resolve(r)
			if k is None:
				raise ValueError('selezione %s: testa %r non trovata' % (name, r))
			ks.append(k)
		rows.append([name, str(d.get('label') or name).replace('\t', ' '), ' '.join(ks)])
	t = _table('head_selections', SEL_COLS)
	t.clear()
	t.appendRow(SEL_COLS)
	for r in rows:
		t.appendRow(r)


def save_selection(name, label=''):
	"""Store the current selection as a named one (add or replace)."""
	name = str(name or '').strip()
	if not name or ' ' in name:
		raise ValueError('selezione: nome %r non valido (senza spazi)' % name)
	others = [s for s in selections() if s['selection'] != name]
	set_selections(others + [{'selection': name, 'label': label or name, 'heads': selection()}])


# ---------------------------------------------------------------- state

def _state_table():
	return _table('head_state', STATE_COLS)


def state():
	"""{key: {mode, <fields as float or None>}} of the heads with a row."""
	t = _state_table()
	out = {}
	for r in range(1, t.numRows):
		d = {'mode': t[r, 'mode'].val or 'manual'}
		for c in FIELDS:
			d[c] = _f(t[r, c].val)
		out[t[r, 'head'].val] = d
	return out


def _row(t, key):
	for r in range(1, t.numRows):
		if t[r, 'head'].val == key:
			return r
	t.appendRow([key, 'manual'] + [''] * len(FIELDS))
	return t.numRows - 1


def _global_values():
	"""moving_heads' own look/position, in programmer units."""
	p = _comp().par
	return {'pan': float(p.Pan.eval()), 'tilt': float(p.Tilt.eval()),
		'dimmer': float(p.Dimmer.eval()), 'red': float(p.Colorr.eval()),
		'green': float(p.Colorg.eval()), 'blue': float(p.Colorb.eval()),
		'white': float(p.White.eval()), 'color': float(p.Colorwheel.eval()),
		'gobo': float(p.Gobo.eval()), 'zoom': float(p.Zoom.eval()),
		'focus': float(p.Focus.eval()), 'strobe': 0.0}


def effective(key):
	"""What the head does now (mode + every field resolved)."""
	g = _global_values()
	st = state().get(key)
	if st is None:
		return dict(g, mode='global')
	out = {k: (st[k] if st[k] is not None else g[k]) for k in FIELDS}
	out['mode'] = st['mode']
	return out


def program(fields, keys=None, mode=None):
	"""Write fields on the selected heads (or `keys`). A global head becomes
	manual; pan/tilt on a follow head makes it manual again. fields values
	in programmer units; None or '' clears the field (back to global).
	Returns the keys written."""
	keys = list(keys) if keys is not None else selection()
	if not keys:
		return []
	t = _state_table()
	for k in keys:
		r = _row(t, k)
		for c, v in fields.items():
			if c not in FIELDS:
				raise ValueError('campo %r sconosciuto (%s)' % (c, ', '.join(FIELDS)))
			if v is None or v == '':
				t[r, c] = ''
				continue
			v = float(v)
			if c in UNIT_FIELDS or c == 'strobe':
				v = max(0.0, min(1.0, v))
			elif c in ('color', 'gobo'):
				v = max(0.0, min(255.0, v))
			t[r, c] = round(v, 4)
		if mode:
			t[r, 'mode'] = mode
		elif t[r, 'mode'].val == 'follow' and ('pan' in fields or 'tilt' in fields):
			t[r, 'mode'] = 'manual'
	return keys


def set_mode(mode, keys=None):
	"""global = release (row removed: the head follows moving_heads' pars
	again), manual, follow."""
	if mode not in MODES:
		raise ValueError('modo %r non valido (%s)' % (mode, ', '.join(MODES)))
	keys = list(keys) if keys is not None else selection()
	t = _state_table()
	if mode == 'global':
		for r in range(t.numRows - 1, 0, -1):
			if t[r, 'head'].val in keys:
				t.deleteRow(r)
		return keys
	for k in keys:
		t[_row(t, k), 'mode'] = mode
	return keys


def pantilt_norm(x, y, keys=None):
	"""Plancia /mh/pantilt: x, y in -1..1 (pad); tilt = -y."""
	keys = list(keys) if keys is not None else selection()
	for k in keys:
		pr, tr = _ranges(k)
		program({'pan': max(-1.0, min(1.0, x)) * pr / 2.0,
			'tilt': -max(-1.0, min(1.0, y)) * tr / 2.0}, [k])
	return keys


def wheel_value(key, kind, index):
	"""DMX value of slot `index` of the head model's gobo/color wheel;
	without slots in the catalog: index * 32 (approximate)."""
	for h in heads():
		if h['key'] == key:
			m = _cat().model(h['profile']) or {}
			slots = m.get('gobos' if kind == 'gobo' else 'colors') or []
			if 0 <= index < len(slots):
				return slots[index]['value']
	return max(0, min(255, int(index) * 32))


def wheel_index(key, kind, value):
	"""Inverse of wheel_value: slot index of a gobo/color wheel DMX value
	(nearest slot; without slots in the catalog: value / 32)."""
	v = float(value or 0)
	for h in heads():
		if h['key'] == key:
			m = _cat().model(h['profile']) or {}
			slots = m.get('gobos' if kind == 'gobo' else 'colors') or []
			if slots:
				return min(range(len(slots)), key=lambda i: abs(float(slots[i]['value']) - v))
	return int(round(v / 32.0))


def pantilt_to_norm(key, pan, tilt):
	"""Inverse of pantilt_norm: degrees -> Plancia pad x, y (-1..1)."""
	pr, tr = _ranges(key)
	return (max(-1.0, min(1.0, pan / (pr / 2.0))), max(-1.0, min(1.0, -tilt / (tr / 2.0))))


def home(keys=None):
	keys = list(keys) if keys is not None else selection()
	for k in keys:
		program({'pan': 0.0, 'tilt': 0.0, 'gobo': 0.0, 'strobe': 0.0}, [k])
	return keys


# ---------------------------------------------------------------- positions

def positions():
	"""[{index, position, label, heads: {key|*: [pan, tilt]}}] table order."""
	t = _table('head_positions', POS_COLS)
	out, idx = [], {}
	for r in range(1, t.numRows):
		name = t[r, 'position'].val.strip()
		if not name:
			continue
		if name not in idx:
			idx[name] = len(out)
			out.append({'index': len(out), 'position': name, 'label': t[r, 'label'].val or name, 'heads': {}})
		out[idx[name]]['heads'][t[r, 'head'].val or '*'] = [_f(t[r, 'pan'].val, 0.0), _f(t[r, 'tilt'].val, 0.0)]
	return out


def _position(ref):
	ps = positions()
	s = str(ref).strip()
	if s.lstrip('-').replace('.', '', 1).isdigit():
		i = int(float(s))
		if 0 <= i < len(ps):
			return ps[i]
	for p in ps:
		if p['position'] == s:
			return p
	raise ValueError('posizione %r non esiste (%d posizioni)' % (ref, len(ps)))


def recall_position(ref, keys=None):
	"""Selected heads to their pan/tilt of position ref (index or name);
	a head without its own row uses the * row, else stays where it is."""
	p = _position(ref)
	keys = list(keys) if keys is not None else selection()
	done = []
	for k in keys:
		pt = p['heads'].get(k) or p['heads'].get('*')
		if pt:
			program({'pan': pt[0], 'tilt': pt[1]}, [k])
			done.append(k)
	return p['position'], done


def store_position(ref, label='', keys=None):
	"""Store the current pan/tilt of the selected heads into position ref
	(an existing index/name, or a new name). Other heads' rows stay."""
	keys = list(keys) if keys is not None else selection()
	try:
		name = _position(ref)['position']
	except ValueError:
		name = str(ref).strip()
		if not name or name.lstrip('-').isdigit():
			raise ValueError('posizione nuova: serve un nome, non un numero')
	t = _table('head_positions', POS_COLS)
	lab = label or next((p['label'] for p in positions() if p['position'] == name), name)
	for k in keys:
		e = effective(k)
		for r in range(t.numRows - 1, 0, -1):
			if t[r, 'position'].val == name and t[r, 'head'].val == k:
				t.deleteRow(r)
		t.appendRow([name, lab, k, round(e['pan'], 2), round(e['tilt'], 2)])
	return name


def set_positions(items):
	"""Replace all positions: [{position, label?, heads: {ref|*: [pan,
	tilt]}}] (degrees)."""
	rows = []
	for it in items or []:
		d = dict(it)
		name = str(d.get('position') or d.get('name') or '').strip()
		if not name:
			raise ValueError('posizione senza nome')
		for ref, pt in dict(d.get('heads') or {}).items():
			k = '*' if ref == '*' else resolve(ref)
			if k is None:
				raise ValueError('posizione %s: testa %r non trovata' % (name, ref))
			rows.append([name, str(d.get('label') or name), k, float(pt[0]), float(pt[1])])
	t = _table('head_positions', POS_COLS)
	t.clear()
	t.appendRow(POS_COLS)
	for r in rows:
		t.appendRow(r)


def ensure_seeded():
	"""First run: Plancia's 6 positions, per head from its formula,
	converted to degrees with each head's model range."""
	t = _table('head_positions', POS_COLS)
	if t.numRows > 1:
		return False
	hs = heads()
	n = len(hs)
	for p, name in enumerate(PLANCIA_POSITIONS):
		for i, h in enumerate(hs):
			pr, tr = _ranges(h['key'])
			pn, tn = _plancia_pos(p, i, n)
			t.appendRow([name, name, h['key'], round(pn * pr / 2.0, 1), round(tn * tr / 2.0, 1)])
		t.appendRow([name, name, '*', 0.0, round(_plancia_pos(p, 0, 1)[1] * 135.0, 1)])
	return True


# ---------------------------------------------------------------- presets

def presets():
	t = _table('head_presets', PRESET_COLS)
	out, idx = [], {}
	for r in range(1, t.numRows):
		name = t[r, 'preset'].val.strip()
		if not name:
			continue
		if name not in idx:
			idx[name] = len(out)
			out.append({'index': len(out), 'preset': name, 'label': t[r, 'label'].val or name, 'heads': {}})
		out[idx[name]]['heads'][t[r, 'head'].val] = {c: _f(t[r, c].val) for c in FIELDS}
	return out


def store_preset(name, label='', keys=None):
	"""Store the full look (effective values) of the selected heads as
	preset `name` (replaces that preset)."""
	name = str(name or '').strip()
	if not name:
		raise ValueError('preset: serve un nome')
	keys = list(keys) if keys is not None else selection()
	if not keys:
		raise ValueError('preset %s: nessuna testa selezionata' % name)
	t = _table('head_presets', PRESET_COLS)
	for r in range(t.numRows - 1, 0, -1):
		if t[r, 'preset'].val == name:
			t.deleteRow(r)
	for k in keys:
		e = effective(k)
		t.appendRow([name, label or name, k] + [round(e[c], 4) for c in FIELDS])
	return name


def recall_preset(ref, keys=None):
	"""Apply a preset (index or name) to the selected heads it has values
	for; with nothing selected, to every head it has."""
	ps = presets()
	s = str(ref).strip()
	p = None
	if s.isdigit() and int(s) < len(ps):
		p = ps[int(s)]
	for x in ps:
		if x['preset'] == s:
			p = x
	if p is None:
		raise ValueError('preset %r non esiste (%d preset)' % (ref, len(ps)))
	sel = list(keys) if keys is not None else selection()
	targets = [k for k in p['heads'] if not sel or k in sel]
	for k in targets:
		program({c: v for c, v in p['heads'][k].items() if v is not None}, [k], mode='manual')
	return p['preset'], targets


def remove_preset(ref):
	t = _table('head_presets', PRESET_COLS)
	s = str(ref).strip()
	n = 0
	for r in range(t.numRows - 1, 0, -1):
		if t[r, 'preset'].val == s:
			t.deleteRow(r)
			n += 1
	if not n:
		raise ValueError('preset %r non esiste' % ref)


# ---------------------------------------------------------------- readouts

def heads_list():
	"""Per head, for Plancia / Gaia: identity, selected, mode, effective
	values."""
	sel = set(selection())
	out = []
	for h in heads():
		e = effective(h['key'])
		out.append(dict({k: h[k] for k in ('unit', 'key', 'uid', 'id', 'name', 'profile')},
			selected=h['key'] in sel, **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in e.items()}))
	return out


def status_text():
	st = state()
	modes = {}
	for h in heads():
		m = st.get(h['key'], {}).get('mode', 'global')
		modes[m] = modes.get(m, 0) + 1
	return '%d teste, %d selezionate | %s' % (len(heads()), len(selection()),
		', '.join('%s %d' % kv for kv in sorted(modes.items())))


# ---------------------------------------------------------------- engine

def unit_state(unit_keys=None):
	"""{unit: state dict or None} for heads_dmx (one table read per cook)."""
	st = state()
	ku = unit_keys if unit_keys is not None else keys_by_unit()
	return {u: st.get(k) for u, k in ku.items()}


def strobe_open():
	"""Shutter phase for strobing heads: open 22% of each period at
	dmx_patch Stroberate (same gate as the group strobe)."""
	patch = _comp().parent().op('dmx_patch')
	rate = max(0.5, float(patch.par.Stroberate.eval())) if patch is not None else 8.0
	return (absTime.seconds * rate) % 1.0 < 0.22


# ---------------------------------------------------------------- OSC /mh/*

def _pressed(args):
	return not args or (_f(args[0], 0) or 0) >= 0.5


def _ref(args, v):
	"""Position / preset reference of an OSC message: a string argument is
	a name, a number an index."""
	if args and isinstance(args[0], str) and _f(args[0]) is None:
		return args[0]
	return int(round(v))


def on_osc(address, args):
	"""Plancia channel 5 /mh/*; returns a status line."""
	a = address[len('/mh/'):] if address.startswith('/mh/') else address
	v = _f(args[0], 0.0) if args else 0.0
	if a == 'select':
		ks = select({'mask': list(args)})
		return 'teste selezionate: %d' % len(ks)
	if a.startswith('select/'):
		what = a[len('select/'):]
		if what in ('all', 'clear'):
			if not _pressed(args):
				return None
			ks = select({what: 1})
		elif what in ('heads', 'uids'):
			ks = select({'heads': [str(x) for x in args]})
		elif what in ('add', 'remove'):
			ks = select({what: [str(x) for x in args]})
		elif what == 'set':
			ks = select({'set': str(args[0]) if args else ''})
		else:
			return 'select/%s sconosciuto' % what
		return 'teste selezionate: %d' % len(ks)
	sel = selection()
	if not sel:
		return 'nessuna testa selezionata (%s ignorato)' % address
	if a == 'pantilt':
		pantilt_norm(v, _f(args[1], 0.0) if len(args) > 1 else 0.0)
	elif a == 'pan':
		program({'pan': v})
	elif a == 'tilt':
		program({'tilt': v})
	elif a == 'color':
		program({'red': v, 'green': _f(args[1], 0.0) if len(args) > 1 else 0.0,
			'blue': _f(args[2], 0.0) if len(args) > 2 else 0.0})
	elif a in ('dimmer', 'zoom', 'focus', 'white'):
		program({a: v})
	elif a == 'strobe':
		program({'strobe': 1.0 if v >= 0.5 else 0.0})
	elif a in ('gobo', 'colorwheel'):
		kind = 'gobo' if a == 'gobo' else 'color'
		for k in sel:
			program({kind: wheel_value(k, kind, int(round(v)))}, [k])
	elif a == 'position':
		name, done = recall_position(_ref(args, v))
		return 'posizione %s su %d teste' % (name, len(done))
	elif a == 'position/store':
		return 'posizione salvata: %s' % store_position(str(args[1]) if len(args) > 1 else int(round(v)))
	elif a == 'preset/recall':
		name, done = recall_preset(_ref(args, v))
		return 'preset %s su %d teste' % (name, len(done))
	elif a == 'preset/store':
		name = str(args[1]) if len(args) > 1 else 'P%d' % (int(round(v)) + 1)
		return 'preset salvato: %s' % store_preset(name)
	elif a == 'home':
		if not _pressed(args):
			return None
		home()
	elif a == 'follow':
		set_mode('follow' if v >= 0.5 else 'manual')
	elif a == 'release':
		if not _pressed(args):
			return None
		set_mode('global')
	else:
		return 'indirizzo %s sconosciuto' % address
	return '%s su %d teste' % (a, len(sel))
