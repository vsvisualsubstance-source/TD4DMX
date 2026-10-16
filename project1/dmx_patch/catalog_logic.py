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
	'pan_range', 'tilt_range', 'defaults', 'notes']
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
		'blue', 'white', 'color', 'gobo', 'zoom', 'focus', 'speed'],
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
	}
	if d['kind'] == 'heads':
		out['pan_range'] = _num(d['pan_range'], 540.0)
		out['tilt_range'] = _num(d['tilt_range'], 270.0)
		out['defaults'] = d['defaults']
	return out


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
	for k in ('pan_range', 'tilt_range'):
		v = d.get(k, cur.get(k, ''))
		row[k] = _fmt(_num(v, 0.0)) if str(v).strip() else ''
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
	model in use cannot change. Returns its name."""
	name = str(dict(raw).get('model') or dict(raw).get('name') or '').strip()
	t = models_table()
	r = _find(t, name)
	if r is None:
		raise ValueError('modello %r non trovato' % name)
	cur = {c: t[r, c].val for c in MODEL_COLUMNS}
	row = _clean_model(raw, source, cur)
	if row['kind'] != cur['kind']:
		users = model_users(name)
		if users:
			raise ValueError('modello %s in uso (%s): il kind non cambia' % (name, ', '.join(users)))
	_put(t, MODEL_COLUMNS, row, r)
	sync_profiles()
	return name


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
