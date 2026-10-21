"""catalog_logic -- the FIXTURE CATALOG: what a light IS, shared by TD and
Plancia (GAIA_INTERFACE "TD/Win-PD, 19"). Two sibling tables:

  fixture_models   one row per fixture MODEL (a DMX personality):
    model         unique name ("ZQ006018 8CH", "Generic Spot 11ch 16bit")
    kind          engine that drives it: chase (rig_a, rig_b, created chase
                  rigs), level (haze/blinder rigs), heads (moving_heads)
    channels      DMX roles in address order ("dimmer red green blue");
                  footprint = number of roles. A model entered with only its
                  channel COUNT gets placeholder roles ch1..chN: the address
                  range is right, the engines send 0 on them until the real
                  roles are filled in.
    manufacturer  free text
    source        builtin | manual (TD) | plancia | scan
    pan_range, tilt_range, defaults   heads only (degrees, "shutter=255")
    notes         free text
    gobos, colors heads only: wheel slots in order, "Open=0 Dots=16 ..."
                  (name=DMX value); /mh/gobo i picks slot i. A colour slot
                  may carry its colour, "Red=16#ff0000"; without it the
                  colour comes from the name (NAMED_COLORS: Red, Rosso,
                  CTO, UV ...), else it is unknown
    beam          colour of the lamp, hex ("ffd8a0" tungsten); blank =
                  white. The colour of a model without colour mixing
                  (dimmer / white only), and the light that CMY and the
                  wheel filter
    lamp          heads only, discharge lamps: "<channel> on=<v> off=<v>
                  hold=<s>" (channel = one of its roles, values DMX, hold
                  2..30 s, default 5). head_programmer.lamp() holds on/off
                  on that channel for hold seconds, then the channel goes
                  back to its default (GAIA_INTERFACE "TD/Win-PD, 43")
  Derived, not stored: color_mix = how the model makes colour, from its
  roles: rgb (red green blue [+ white amber lime uv]), cmy (cyan magenta
  yellow), wheel (color), lamp (none of them: the beam colour), [] = no
  light (haze). beam_color() gives the resulting colour from DMX values
  (gaia_services/dmx_output); nearest_color_slot() picks the wheel slot
  for a requested RGB (head_programmer: /mh/color on a wheel head).

  fixture_types    the stage TAXONOMY, defined by Plancia while building the
                   stage (par, wash, bar, mh, blinder, haze, wall, ...):
    type    Plancia type key
    label   human name
    group   patch group (name or alias) the type's fixtures go to
    kind    kind of that group, used to create it when missing: chase |
            level; heads only for the built-in heads group; none = no DMX
            (LED wall, speaker: the fixtures are skipped)
    model   default model of the type's fixtures ('' = the group's default)
    source  builtin | manual | plancia

The per-group profile tables the engines read (dmx_audio_chase/
fixture_profiles, moving_heads/head_profiles, level_profiles inside each
level rig) are DERIVED: sync_profiles() rewrites them from fixture_models
(every model of the group's kind). Edit the models here, not there: a direct
edit of those tables is overwritten at the next sync.

Automatic fill from the scan: not possible yet. TD's Art-Net DAT only polls
nodes and ports (scan_logic); model and footprint need RDM, which TD does
not implement and the current node does not support. source 'scan' is
reserved for it.

Called by catalog_watch (manual edits of the two tables), the dmx_patch
Catalog page (patch_callbacks), fixture_logic (Plancia types) and
gaia_services/dmx_services (dmx_models, dmx_types, ...).
"""
import re

MODEL_COLUMNS = ['model', 'kind', 'channels', 'manufacturer', 'source',
	'pan_range', 'tilt_range', 'defaults', 'notes', 'gobos', 'colors', 'beam', 'lamp']
TYPE_COLUMNS = ['type', 'label', 'group', 'kind', 'model', 'source']

KINDS = ('chase', 'level', 'heads')
TYPE_KINDS = KINDS + ('none',)
SOURCES = ('builtin', 'manual', 'plancia', 'scan')

# roles each engine DRIVES; any other role goes out at 0 (heads: at the
# model 'defaults' value). Published so Plancia can offer them.
ROLES = {
	'chase': ['dimmer', 'red', 'green', 'blue'],
	'level': ['dimmer', 'red', 'green', 'blue', 'white', 'amber', 'uv', 'output', 'fan'],
	'heads': ['pan', 'pan_fine', 'tilt', 'tilt_fine', 'dimmer', 'shutter', 'red', 'green',
		'blue', 'white', 'cyan', 'magenta', 'yellow', 'color', 'gobo', 'zoom', 'focus', 'speed'],
}

# first run only: Plancia's FIX_TYPES of 2026-10-16 (gaia plancia/index.html),
# mapped like the old fixture_logic.PLANCIA_TYPES. model '' = the group's
# default profile at seeding time.
SEED_TYPES = [
	('mh', 'Testa mobile', 'mh', 'heads', ''),
	('par', 'PAR / Wash', 'front', 'chase', ''),
	('bar', 'Barra LED', 'ledbar', 'chase', 'D+RGB 4CH'),
	('blinder', 'Blinder', 'blinder', 'level', 'Dimmer 1CH'),
	('haze', 'Haze', 'haze', 'level', 'Haze 2CH'),
	('wall', 'LED wall', 'ledwall', 'none', ''),
	('speaker', 'Cassa', '', 'none', ''),
]

# the level rigs' profiles before the catalog (group_logic.LEVEL_PROFILES)
SEED_LEVEL = [('Dimmer 1CH', 'dimmer'), ('Haze 2CH', 'output fan')]

_ROLE = re.compile(r'^[a-z][a-z0-9_]*$')
_PLACEHOLDER = re.compile(r'^ch\d+$')
_TYPE = re.compile(r'^[a-z][a-z0-9_]{0,23}$')
_HEADS_COLS = ['name', 'channels', 'pan_range', 'tilt_range', 'defaults', 'notes']


# ---------------------------------------------------------------- tables

def _patch():
	return me.parent()


def _fl():
	return _patch().op('fixture_logic').module


def _gl():
	return _patch().op('group_logic').module


def _table(name, cols):
	t = _patch().op(name)
	if t.numRows == 0 or t[0, 0] is None or t[0, 0].val != cols[0]:
		t.clear()
		t.appendRow(cols)
	for c in cols:   # columns added later: append, empty
		if t[0, c] is None:
			t.appendCol([c] + [''] * (t.numRows - 1))
	return t


def models_table():
	return _table('fixture_models', MODEL_COLUMNS)


def types_table():
	return _table('fixture_types', TYPE_COLUMNS)


def _rows(t, cols):
	return [{c: (t[r, c].val if t[r, c] is not None else '') for c in cols}
		for r in range(1, t.numRows)]


def _find(t, key):
	"""Row index of `key` in the first column, None if absent."""
	for r in range(1, t.numRows):
		if t[r, 0].val == key:
			return r
	return None


def _put(t, cols, d, r=None):
	"""Write dict d on row r (None = append a row)."""
	if r is None:
		t.appendRow([''] * t.numCols)
		r = t.numRows - 1
	for c in cols:
		if c in d:
			t[r, c] = d[c]
	return r


def _num(v, d):
	try:
		return float(str(v))
	except (TypeError, ValueError):
		return d


def _fmt(v):
	return str(int(v)) if float(v).is_integer() else str(v)


# ---------------------------------------------------------------- models

def parse_channels(value):
	"""Role list from a list, a space/comma separated string, or a channel
	COUNT (int, or a string of digits): placeholder roles ch1..chN."""
	count = None
	if isinstance(value, bool):
		raise ValueError('canali non validi: %r' % value)
	if isinstance(value, (int, float)):
		count = int(value)
	elif isinstance(value, (list, tuple)):
		roles = [str(x).strip().lower() for x in value if str(x).strip()]
	else:
		s = str(value or '').strip()
		if s.isdigit():
			count = int(s)
		else:
			roles = [x.lower() for x in re.split(r'[\s,]+', s) if x]
	if count is not None:
		if not 1 <= count <= 512:
			raise ValueError('numero di canali fuori range 1..512: %d' % count)
		return ['ch%d' % i for i in range(1, count + 1)]
	if not roles:
		raise ValueError('canali vuoti: servono i ruoli o il numero di canali')
	if len(roles) > 512:
		raise ValueError('%d canali: oltre 512' % len(roles))
	bad = [x for x in roles if not _ROLE.match(x)]
	if bad:
		raise ValueError('ruoli non validi: %s (minuscole, cifre, _)' % ', '.join(bad))
	return roles


def _model_dict(d):
	chans = d['channels'].split()
	out = {
		'model': d['model'], 'kind': d['kind'], 'channels': chans,
		'footprint': len(chans),
		'complete': bool(chans) and not any(_PLACEHOLDER.match(c) for c in chans),
		'manufacturer': d['manufacturer'], 'source': d['source'] or 'manual',
		'notes': d['notes'],
		'beam': _hex_rgb(d.get('beam')) or [1.0, 1.0, 1.0],
	}
	if d['kind'] == 'heads':
		out['pan_range'] = _num(d['pan_range'], 540.0)
		out['tilt_range'] = _num(d['tilt_range'], 270.0)
		out['defaults'] = d['defaults']
		out['gobos'] = parse_slots(d.get('gobos', ''))
		out['colors'] = parse_slots(d.get('colors', ''))
		for s in out['colors']:
			if 'rgb' not in s:
				s['rgb'] = named_rgb(s['name'])
		try:
			out['lamp'] = parse_lamp(d.get('lamp', ''), chans)
		except ValueError:
			out['lamp'] = None   # hand-edited row: no lamp until fixed
	out['color_mix'] = color_mix(chans, out.get('colors'))
	return out


def _hex_rgb(h):
	"""'ff8000' / '#ff8000' -> [1.0, 0.502, 0.0]; None if not a hex colour."""
	h = str(h or '').strip().lstrip('#')
	if not re.match(r'^[0-9a-fA-F]{6}$', h):
		return None
	return [round(int(h[i:i + 2], 16) / 255.0, 3) for i in (0, 2, 4)]


def _rgb_hex(rgb):
	return ''.join('%02x' % int(round(max(0.0, min(1.0, float(x))) * 255)) for x in rgb)


def _rgb_list(v):
	"""[r, g, b] 0-1 (or 0-255) list / hex string -> [r, g, b] 0-1, or None."""
	if isinstance(v, str):
		return _hex_rgb(v)
	try:
		x = [float(c) for c in v][:3]
	except (TypeError, ValueError):
		return None
	if len(x) != 3:
		return None
	if max(x) > 1.0:
		x = [c / 255.0 for c in x]
	return [round(max(0.0, min(1.0, c)), 3) for c in x]


def parse_slots(text):
	"""'Open=0 Dots=16' -> [{'name': 'Open', 'value': 0}, ...]; a colour
	slot may carry its colour: 'Red=16#ff0000' -> ..., 'rgb': [1, 0, 0].
	A list of such dicts ('rgb' list or 'hex') or [name, value] pairs
	passes through cleaned."""
	out = []
	items = text if isinstance(text, (list, tuple)) else str(text or '').split()
	for it in items:
		rgb = None
		if isinstance(it, dict):
			name, val = it.get('name'), it.get('value')
			rgb = _rgb_list(it.get('rgb') if it.get('rgb') is not None else it.get('hex'))
		elif isinstance(it, (list, tuple)) and len(it) == 2:
			name, val = it
		elif '=' in str(it):
			name, val = str(it).split('=', 1)
			if '#' in val:
				val, h = val.split('#', 1)
				rgb = _hex_rgb(h)
		else:
			continue
		try:
			v = max(0, min(255, int(float(val))))
		except (TypeError, ValueError):
			continue
		s = {'name': str(name).strip().replace(' ', '_'), 'value': v}
		if rgb is not None:
			s['rgb'] = rgb
		out.append(s)
	return out


LAMP_HOLD_S = 5.0


def parse_lamp(v, chans=None):
	"""Lamp command of a discharge head, {channel, on, off, hold}, from a
	dict or "control on=250 off=11 hold=5"; None when blank. chans = the
	model's roles: the channel must be one of them."""
	if v in (None, '') or (isinstance(v, str) and not v.strip()):
		return None
	if isinstance(v, dict):
		d = {str(k).lower(): x for k, x in v.items()}
	else:
		d = {}
		for tok in str(v).split():
			if '=' in tok:
				k, x = tok.split('=', 1)
				d[k.strip().lower()] = x
			else:
				d['channel'] = tok
	ch = str(d.get('channel') or '').strip().lower()
	if not ch:
		raise ValueError('lampada: manca il canale (es. "control on=250 off=11 hold=5")')
	if chans is not None and ch not in chans:
		raise ValueError('lampada: il canale %r non e\' tra i canali del modello' % ch)
	out = {'channel': ch}
	for k in ('on', 'off'):
		n = _num(d.get(k), None)
		if n is None or not 0 <= n <= 255:
			raise ValueError('lampada: %s deve essere un valore DMX 0..255' % k)
		out[k] = int(n)
	hold = _num(d.get('hold', LAMP_HOLD_S), None)
	if hold is None or not 2 <= hold <= 30:
		raise ValueError('lampada: hold in secondi, 2..30')
	out['hold'] = hold
	return out


def _lamp_text(lamp):
	return '%s on=%d off=%d hold=%s' % (lamp['channel'], lamp['on'], lamp['off'],
		_fmt(lamp['hold'])) if lamp else ''


def _slots_text(v):
	return ' '.join('%s=%d%s' % (s['name'], s['value'], ('#' + _rgb_hex(s['rgb'])) if s.get('rgb') else '')
		for s in parse_slots(v))


# ---------------------------------------------------------------- colour

# colour of a wheel slot by its name when the slot has no '#rrggbb'
# (english and italian, case and punctuation ignored)
NAMED_COLORS = {
	'open': (1, 1, 1), 'white': (1, 1, 1), 'bianco': (1, 1, 1), 'aperto': (1, 1, 1),
	'red': (1, 0, 0), 'rosso': (1, 0, 0), 'deepred': (.7, 0, 0), 'congo': (.35, 0, .8),
	'orange': (1, .5, 0), 'arancio': (1, .5, 0), 'arancione': (1, .5, 0),
	'amber': (1, .75, 0), 'ambra': (1, .75, 0),
	'yellow': (1, 1, 0), 'giallo': (1, 1, 0),
	'lime': (.6, 1, 0), 'lightgreen': (.5, 1, .5), 'green': (0, 1, 0), 'verde': (0, 1, 0),
	'cyan': (0, 1, 1), 'ciano': (0, 1, 1), 'turquoise': (0, .9, .8),
	'lightblue': (.45, .75, 1), 'azzurro': (.45, .75, 1),
	'blue': (0, 0, 1), 'blu': (0, 0, 1), 'darkblue': (0, 0, .6), 'deepblue': (0, 0, .6),
	'magenta': (1, 0, 1), 'pink': (1, .45, .75), 'rosa': (1, .45, .75),
	'purple': (.6, 0, 1), 'violet': (.6, 0, 1), 'viola': (.6, 0, 1), 'lavender': (.75, .6, 1),
	'uv': (.4, 0, 1), 'cto': (1, .8, .6), 'warm': (1, .8, .6), 'ctb': (.8, .9, 1), 'cold': (.8, .9, 1),
}
_COLOR_ROLES = {'red', 'green', 'blue', 'white', 'amber', 'uv', 'lime',
	'cyan', 'magenta', 'yellow', 'color', 'dimmer', 'output'}


def named_rgb(name):
	k = re.sub(r'[^a-z]', '', str(name or '').lower())
	if k in NAMED_COLORS:
		return [float(x) for x in NAMED_COLORS[k]]
	for n, c in NAMED_COLORS.items():   # 'Red2', 'CTO_3200' ...
		if len(n) > 2 and k.startswith(n):
			return [float(x) for x in c]
	return None


def color_mix(chans, colors=None):
	"""How a model makes colour, from its roles: subset of ['rgb', 'cmy',
	'wheel'] ('wheel' only with colour slots that have a colour), or
	['lamp'] (fixed colour = 'beam'), [] when it emits no light (haze)."""
	ch = set(chans)
	mix = []
	if {'red', 'green', 'blue'} <= ch:
		mix.append('rgb')
	if {'cyan', 'magenta', 'yellow'} & ch:
		mix.append('cmy')
	if 'color' in ch:
		mix.append('wheel')
	if not mix and ch & {'dimmer', 'white'}:
		mix.append('lamp')
	return mix


def beam_color(m, vals):
	"""Colour of the beam BEFORE the dimmer, from DMX values {role: 0-255}
	of model dict m. Returns ([r, g, b] 0-1, source); source = 'rgb' |
	'cmy' | 'wheel' | 'cmy+wheel' | 'lamp' | 'unknown' (a wheel whose
	slots have no colour) | None (no light: rgb None)."""
	mix = m.get('color_mix') or color_mix(m.get('channels') or [])
	if not mix:
		return None, None
	lamp = m.get('beam') or [1.0, 1.0, 1.0]
	if 'rgb' in mix:
		v = lambda k: float(vals.get(k) or 0.0) / 255.0
		c = [v('red'), v('green'), v('blue')]
		for k, tint in (('white', (1, 1, 1)), ('amber', (1, .75, 0)), ('lime', (.6, 1, 0)), ('uv', (.25, 0, .6))):
			if k in vals:
				c = [a + v(k) * t for a, t in zip(c, tint)]
		return [round(min(1.0, x), 3) for x in c], 'rgb'
	c = list(lamp)
	src = []
	if 'cmy' in mix:
		f = [1.0 - float(vals.get(k) or 0.0) / 255.0 for k in ('cyan', 'magenta', 'yellow')]
		c = [a * b for a, b in zip(c, f)]
		src.append('cmy')
	if 'wheel' in mix:
		slot = slot_at(m, vals.get('color'))
		if slot is not None and slot.get('rgb'):
			c = [a * b for a, b in zip(c, slot['rgb'])]
			src.append('wheel')
		elif not src:
			return [round(x, 3) for x in c], 'unknown'
	return [round(x, 3) for x in c], '+'.join(src) or 'lamp'


def slot_at(m, value):
	"""Colour slot of model m nearest to the DMX value (None: no slots)."""
	slots = m.get('colors') or []
	if value is None or not slots:
		return None
	return min(slots, key=lambda s: abs(float(s['value']) - float(value)))


def nearest_color_slot(m, rgb):
	"""Colour slot of model m whose colour is closest to [r, g, b] 0-1
	(hue/saturation: both normalized by their brightest channel); None
	without coloured slots."""
	slots = [s for s in (m.get('colors') or []) if s.get('rgb')]
	if not slots:
		return None
	norm = lambda c: [x / (max(c) or 1.0) for x in c]
	t = norm([float(x) for x in rgb])
	return min(slots, key=lambda s: sum((a - b) ** 2 for a, b in zip(norm(s['rgb']), t)))


def models(kind=None):
	"""Catalog models as dicts (table order), optionally of one kind."""
	return [_model_dict(d) for d in _rows(models_table(), MODEL_COLUMNS)
		if d['model'].strip() and (kind is None or d['kind'] == kind)]


def model(name):
	name = str(name or '').strip()
	for m in models():
		if m['model'] == name:
			return m
	return None


def _clean_model(raw, source, cur=None):
	"""Validated table row for a model dict (cur = the existing row on an
	update: missing fields keep its value). Raises ValueError."""
	d = dict(raw)
	cur = cur or {}
	name = str(d.get('model') or d.get('name') or cur.get('model') or '').strip()
	if not name or '\t' in name or '\n' in name:
		raise ValueError('modello: nome mancante o non valido')
	kind = str(d.get('kind') or cur.get('kind') or '').strip()
	if kind not in KINDS:
		raise ValueError('modello %s: kind %r non valido (%s)' % (name, kind, ', '.join(KINDS)))
	if d.get('channels') not in (None, ''):
		chans = parse_channels(d['channels'])
	elif d.get('footprint') not in (None, ''):
		chans = parse_channels(int(d['footprint']))
	elif cur.get('channels'):
		chans = cur['channels'].split()
	else:
		raise ValueError('modello %s: servono channels (ruoli) o footprint (numero di canali)' % name)
	row = {'model': name, 'kind': kind, 'channels': ' '.join(chans)}
	for k in ('manufacturer', 'notes', 'defaults'):
		v = d.get(k, cur.get(k, ''))
		row[k] = str(v if v is not None else '').replace('\t', ' ').replace('\n', ' ').strip()
	for k in ('gobos', 'colors'):
		row[k] = _slots_text(d.get(k, cur.get(k, '')))
	b = d.get('beam', cur.get('beam', ''))
	b = _rgb_list(b) if b not in (None, '') else None
	row['beam'] = _rgb_hex(b) if b else ''
	for k in ('pan_range', 'tilt_range'):
		v = d.get(k, cur.get(k, ''))
		row[k] = _fmt(_num(v, 0.0)) if str(v).strip() else ''
	lamp = d.get('lamp', cur.get('lamp', ''))
	row['lamp'] = _lamp_text(parse_lamp(lamp, chans)) if kind == 'heads' else ''
	src = str(d.get('source') or cur.get('source') or source)
	row['source'] = src if src in SOURCES else source
	return row


def model_users(name):
	"""What refers to model `name`: fixtures, types, group default pars."""
	fl = _fl()
	users = ['fixture %d (%s)' % (f['id'], f['name']) for f in fl.rows() if f['profile'] == name]
	users += ['tipo %s' % t['type'] for t in types() if t['model'] == name]
	for g in fl.groups():
		comp = fl.group_comp(g['group'])
		p = fl._first_par(comp, fl._PROFILE_PARS) if comp is not None else None
		if p is not None and str(p.eval()) == name:
			users.append('profilo di default di %s' % g['group'])
	return users


def add_model(raw, source='manual'):
	"""Add a model; raises if it exists already. Returns its name."""
	row = _clean_model(raw, source)
	t = models_table()
	if _find(t, row['model']) is not None:
		raise ValueError('modello %r esiste gia\' (usa dmx_model_update)' % row['model'])
	_put(t, MODEL_COLUMNS, row)
	sync_profiles()
	return row['model']


def update_model(raw, source='manual'):
	"""Change a model (named by 'model'); missing fields stay. The kind of a
	model in use cannot change. A new channel count that makes the model's
	fixtures overlap other fixtures follows raw['on_conflict'] (GAIA_INTERFACE
	"TD/Win-PD, 43"): reject (default) = refused, naming the overlaps; auto =
	written, and those fixtures move to the first free address
	(conflict_logic.suggest, same port first); accept = written as is (the
	patch report flags the overlaps). Returns its name."""
	raw = dict(raw)
	on_conflict = str(raw.pop('on_conflict', 'reject') or 'reject').strip().lower()
	if on_conflict not in ('accept', 'reject', 'auto'):
		raise ValueError('on_conflict %r non valido (accept, reject, auto)' % on_conflict)
	name = str(raw.get('model') or raw.get('name') or '').strip()
	t = models_table()
	r = _find(t, name)
	if r is None:
		raise ValueError('modello %r non trovato' % name)
	cur = {c: (t[r, c].val if t[r, c] is not None else '') for c in MODEL_COLUMNS}
	row = _clean_model(raw, source, cur)
	if row['kind'] != cur['kind']:
		users = model_users(name)
		if users:
			raise ValueError('modello %s in uso (%s): il kind non cambia' % (name, ', '.join(users)))
	n_old, n_new = len(cur['channels'].split()), len(row['channels'].split())
	clashes = _new_overlaps(name, n_new) if n_new != n_old else []
	if clashes and on_conflict == 'reject':
		raise ValueError('modello %s: %d canali invece di %d, le sue fixture si sovrappongono: %s '
			'(on_conflict "auto" le sposta, "accept" scrive lo stesso)' % (name, n_new, n_old,
			', '.join('%s %d-%d con %s %d-%d' % (a['name'], a['start'], a['end'], b['name'], b['start'], b['end'])
				for a, b in clashes)))
	_put(t, MODEL_COLUMNS, row, r)
	sync_profiles()
	if clashes and on_conflict == 'auto':
		_move_clashing({e['id'] for pair in clashes for e in pair if e['profile'] == name})
	return name


def _cl():
	return _patch().op('conflict_logic').module


def _new_overlaps(name, n):
	"""Overlaps the fixtures of model `name` would have with n channels and
	do not have now: [(fixture entry, other entry)], each pair once."""
	cl = _cl()
	occ = cl.occupancy()
	grown = [dict(e, end=e['start'] + n - 1, footprint=n) if e['profile'] == name else e for e in occ]

	def pairs(entries):
		out = set()
		for a in entries:
			if a['profile'] != name:
				continue
			for b in entries:
				if b['id'] != a['id'] and b['port_id'] == a['port_id'] and \
						cl._overlaps(a['start'], a['end'], b) and (b['id'], a['id']) not in out:
					out.add((a['id'], b['id']))
		return out

	by_id = {e['id']: e for e in grown}
	return [(by_id[a], by_id[b]) for a, b in sorted(pairs(grown) - pairs(occ))]


def _move_clashing(ids):
	"""Move each fixture in ids that still overlaps another to its first
	free address (from its own address on, same port first), in address
	order: one that overlaps only LATER fixtures of ids stays, those move
	(a row of grown heads keeps its order). Returns the moves [{id, name,
	from, to}]."""
	cl, fl = _cl(), _fl()
	moves = []
	start = {e['id']: (e['port_id'], e['start']) for e in cl.occupancy() if e['id'] in ids}
	order = sorted(start, key=lambda i: start[i])
	for i, fid in enumerate(order):
		e = next((x for x in cl.occupancy() if x['id'] == fid), None)
		if e is None:
			continue
		hits = [o for o in cl.occupancy((fid,))
			if o['port_id'] == e['port_id'] and cl._overlaps(e['start'], e['end'], o)]
		if all(o['id'] in ids and o['start'] > e['start'] for o in hits):
			continue
		# the later ones of ids move after this one: their place is not taken
		s = cl.suggest(e['footprint'], e['port_id'], e['start'], tuple(order[i:]))
		if s is None:
			debug('modello: nessuno spazio libero per %s (%d canali)' % (e['name'], e['footprint']))
			continue
		fl.update_fixture(fid, port_id=s['port_id'], address=s['address'])
		moves.append({'id': fid, 'name': e['name'], 'from': [e['port_id'], e['start']],
			'to': [s['port_id'], s['address']]})
	return moves


def set_model(raw, source='manual'):
	"""Add or update (upsert)."""
	name = str(dict(raw).get('model') or dict(raw).get('name') or '').strip()
	if _find(models_table(), name) is None:
		return add_model(raw, source)
	return update_model(raw, source)


def remove_model(name):
	name = str(name or '').strip()
	t = models_table()
	r = _find(t, name)
	if r is None:
		raise ValueError('modello %r non trovato' % name)
	users = model_users(name)
	if users:
		raise ValueError('modello %s in uso: %s' % (name, ', '.join(users)))
	t.deleteRow(r)
	sync_profiles()


# ---------------------------------------------------------------- types

def types():
	return [d for d in _rows(types_table(), TYPE_COLUMNS) if d['type'].strip()]


def type_info(typ):
	typ = str(typ or '').strip()
	for d in types():
		if d['type'] == typ:
			return d
	return None


def _clean_type(raw, source, pending):
	"""Validated row for a type dict. `pending` = models created by this
	same call ({name: row}), not yet in the table. A type naming a model
	that does not exist, with 'channels' or 'footprint', creates it (added
	to pending, written by the caller)."""
	d = dict(raw)
	typ = str(d.get('type') or '').strip()
	if not _TYPE.match(typ):
		raise ValueError('tipo %r non valido (minuscole, cifre, _; max 24)' % typ)
	fl = _fl()
	kind = str(d.get('kind') or '').strip()
	group = str(d.get('group') or '').strip()
	mdl = str(d.get('model') or '').strip()
	g = fl.resolve_group(group) if group else None
	if g is not None:
		gkind = (fl.group_info(g) or {}).get('kind') or 'chase'
		if kind and kind != gkind:
			raise ValueError('tipo %s: il gruppo %s e\' %s, non %s' % (typ, group, gkind, kind))
		kind = gkind
	if kind not in TYPE_KINDS:
		raise ValueError('tipo %s: kind %r non valido (%s)' % (typ, kind, ', '.join(TYPE_KINDS)))
	if kind == 'none':
		mdl = ''
	else:
		gl = _gl()
		if not group:
			raise ValueError('tipo %s: serve il gruppo' % typ)
		if g is None and kind == 'heads':
			raise ValueError('tipo %s: kind heads solo per il gruppo heads (mh)' % typ)
		if g is None and (not gl._NAME.match(group) or group in gl.RESERVED):
			raise ValueError('tipo %s: nome gruppo %r non valido o riservato' % (typ, group))
		if mdl:
			m = pending.get(mdl) or model(mdl)
			if m is None:
				if d.get('channels') in (None, '') and d.get('footprint') in (None, ''):
					raise ValueError('tipo %s: modello %r non nel catalogo (aggiungi channels o footprint per crearlo)' % (typ, mdl))
				m = _clean_model({'model': mdl, 'kind': kind, 'channels': d.get('channels'),
					'footprint': d.get('footprint'), 'manufacturer': d.get('manufacturer', '')}, source)
				pending[mdl] = m
			if m['kind'] != kind:
				raise ValueError('tipo %s: il modello %s e\' %s, il gruppo %s' % (typ, mdl, m['kind'], kind))
	label = str(d.get('label') or typ).replace('\t', ' ').strip()
	src = str(d.get('source') or source)
	return {'type': typ, 'label': label, 'group': group, 'kind': kind, 'model': mdl,
		'source': src if src in SOURCES else source}


def _write_pending(pending):
	t = models_table()
	for row in pending.values():
		if _find(t, row['model']) is None:
			_put(t, MODEL_COLUMNS, row)


def set_type(raw, source='manual'):
	"""Add or replace one type. Returns its key."""
	pending = {}
	row = _clean_type(raw, source, pending)
	_write_pending(pending)
	t = types_table()
	_put(t, TYPE_COLUMNS, row, _find(t, row['type']))
	if pending:
		sync_profiles()
	return row['type']


def set_types(items, source='plancia'):
	"""Replace the whole taxonomy (Plancia, stage construction). Everything
	is validated before anything is written."""
	if not isinstance(items, (list, tuple)):
		raise ValueError('dmx_types: serve una lista di tipi')
	pending, rows, seen = {}, [], set()
	for raw in items:
		row = _clean_type(raw, source, pending)
		if row['type'] in seen:
			raise ValueError('tipo %s ripetuto' % row['type'])
		seen.add(row['type'])
		rows.append(row)
	_write_pending(pending)
	t = types_table()
	t.clear()
	t.appendRow(TYPE_COLUMNS)
	for row in rows:
		_put(t, TYPE_COLUMNS, row)
	if pending:
		sync_profiles()


def remove_type(typ):
	t = types_table()
	r = _find(t, str(typ or '').strip())
	if r is None:
		raise ValueError('tipo %r non trovato' % typ)
	t.deleteRow(r)


# ---------------------------------------------------------------- derived

def _profile_rows(kind, cols):
	out = [list(cols)]
	for m in models(kind):
		row = [m['model'], ' '.join(m['channels'])]
		if len(cols) > 2:
			row += [_fmt(m['pan_range']), _fmt(m['tilt_range']), m['defaults'], m['notes']]
		out.append(row)
	return out


def profile_rows(kind):
	"""Rows (header first) of a profile table of `kind`, from the catalog."""
	return _profile_rows(kind, _HEADS_COLS if kind == 'heads' else ['name', 'channels'])


def sync_profiles():
	"""Rewrite every group's profile table from fixture_models (the models of
	the group's kind) and refresh the profile menus. A table that already
	matches is not touched: each write re-saves a synced file and recooks
	the engines. Returns the paths rewritten."""
	fl = _fl()
	done, changed = set(), []
	for g in fl.groups():
		kind = g.get('kind') or 'chase'
		if kind not in KINDS:
			continue
		t = fl.profile_table(g['group'])
		comp = fl.group_comp(g['group'])
		if t is None or t.path in done:
			continue
		done.add(t.path)
		rows = profile_rows(kind)
		if [[c.val for c in row] for row in t.rows()] != rows:
			t.clear()
			for row in rows:
				t.appendRow(row)
			changed.append(t.path)
		_refresh_menu(comp, kind, [r[0] for r in rows[1:]])
	return changed


def _refresh_menu(comp, kind, names):
	"""Static profile menus (chase Fixtureprofile, level Profile) get the
	catalog names; the value is never changed here (that would re-patch the
	group). The heads menu is a TableMenu on head_profiles: nothing to do."""
	if comp is None or not names:
		return
	par = getattr(comp.par, 'Fixtureprofile', None) if kind == 'chase' else \
		getattr(comp.par, 'Profile', None) if kind == 'level' else None
	if par is None or par.menuSource:
		return
	if list(par.menuNames) != names:
		par.menuNames = names
		par.menuLabels = names


def ensure_seeded():
	"""First run: fill fixture_models from the profile tables that were the
	libraries before the catalog, plus the level profiles, and
	fixture_types from SEED_TYPES. Returns True when something was seeded."""
	fl = _fl()
	seeded = False
	mt = models_table()
	if mt.numRows <= 1:
		seen = set()
		for g in fl.groups():
			kind = g.get('kind') or 'chase'
			t = fl.profile_table(g['group'])
			if t is None or kind not in KINDS:
				continue
			for r in range(1, t.numRows):
				name = t[r, 0].val.strip()
				if not name or name in seen:
					continue
				seen.add(name)
				cell = {c: (t[r, c].val if t[r, c] is not None else '') for c in _HEADS_COLS}
				_put(mt, MODEL_COLUMNS, {'model': name, 'kind': kind,
					'channels': ' '.join(cell['channels'].split()), 'source': 'builtin',
					'pan_range': cell['pan_range'], 'tilt_range': cell['tilt_range'],
					'defaults': cell['defaults'], 'notes': cell['notes']})
		for name, chans in SEED_LEVEL:
			if name not in seen:
				_put(mt, MODEL_COLUMNS, {'model': name, 'kind': 'level', 'channels': chans,
					'source': 'builtin'})
		seeded = True
	tt = types_table()
	if tt.numRows <= 1:
		for typ, label, group, kind, mdl in SEED_TYPES:
			if kind != 'none' and not mdl:
				g = fl.resolve_group(group)
				mdl = fl.default_profile(g) if g else ''
			_put(tt, TYPE_COLUMNS, {'type': typ, 'label': label, 'group': group,
				'kind': kind, 'model': mdl, 'source': 'builtin'})
		seeded = True
	return seeded


def to_matrix():
	"""JSON-friendly catalog for dmx_matrix / the status."""
	return {
		'models': models(),
		'types': types(),
		'kinds': {k: {'roles': ROLES[k],
			'groups': [g['group'] for g in _fl().groups() if (g.get('kind') or 'chase') == k]}
			for k in KINDS},
		'type_kinds': list(TYPE_KINDS),
		'sources': list(SOURCES),
	}
