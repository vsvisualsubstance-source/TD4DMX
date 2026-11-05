"""rig_config -- advanced configuration of the DMX rigs, exchanged with the
Plancia (GAIA_INTERFACE "TD/Win-PD, 68"). Same content as the Look Rig tab
of the Config window, for every rig of the dmx_patch `groups` table (chase
and level kinds; the heads keep their heads_* params).

The single dmx_<rig>_* params stay as they are. This module adds:

  matrix()   dmx_matrix section 'rig_config' (structure only, no live
             values, so the matrix fingerprint changes only when the
             structure does):
               params    the two params below
               kinds     {kind: {sections: [{key, label, fields}]}}
               fields    {kind: {field: {type, label, help?, range?,
                         default?, options?, labels?}}}  (labels = shown
                         names of the options, same order) types: float | enum |
                         color_rgb (3 x 0-1) | bool
               groups    [{group, label, alias, kind, comp, fixtures,
                         profiles, inactive: {field: reason}}]
             `inactive` = fields that do nothing on that group today
             (e.g. dimmer_gamma when every light has a dimmer channel).

  values()   dmx_rig_config (read): {group: {field: value}} for every rig.

  apply(req) dmx_rig_config (write), one of:
               {group, values: {field: value}}
               {groups: {group: {field: value}}}
               [{group, values}, ...]
             + optional request_id. group = group name or alias (front,
             back). Everything is validated FIRST (unknown group/field,
             type, range, enum option, min_dimmer <= max_dimmer with the
             values after the write); on any error nothing is written,
             the result says why and ValueError goes to last_error. Then
             all the values are written in the same frame.
  result()   dmx_rig_config_result: {request_id, ts, ok, applied:
             {group: [fields]}, errors: [str]}

A write is a live tweak like one from the TD UI. LOOK fields hold until
the show timeline moves that par again; CALIBRATION fields (min/max dimmer,
boost, gamma, AGC, min range, kick thresholds = show_logic
RIG_CALIBRATION_PARS) are never written by scenes or lanes, so they hold
("TD/Win-PD, 69"). Every field schema carries role: calibration | look.

Calibration presets ("TD/Win-PD, 69"), only the calibration fields, per kind
(today chase: level rigs have no calibration):
  starters        theoretical starting points by the lights' channels:
                  'dimmer' (every light has a dimmer channel: gamma does
                  nothing) and 'no_dimmer' (at least one light without:
                  the level is multiplied into the colours with the gamma,
                  higher min so RGB LEDs do not step at the bottom). Full
                  values = par defaults + STARTERS. matrix groups[].starter
                  says which one fits a group (None without lights).
  presets()       dmx_rig_presets: [{name, kind, label, values, source,
                  updated}] from the rig_presets table (tsv, saved with the
                  project)
  preset_store    {name, group, label?}: capture the group's calibration
                  (same name = overwrite)
  preset_recall   {name | starter: true, group | groups: [...]}: write it
                  (through apply: validated, all or nothing; starter = each
                  group's own starter)
  preset_copy     {from: group, to: group | [groups]}: calibration of one
                  rig onto others of the same kind
  preset_remove   name
The result of every action is dmx_rig_config_result (+ action).
"""
import json
import time

# field -> (par name, type); color_rgb uses <par>r/g/b
FIELDS = {
	'level': ('Level', 'float'),
	'min_dimmer': ('Mindimmer', 'float'),
	'max_dimmer': ('Maxdimmer', 'float'),
	'dimmer_boost': ('Dimmerboost', 'float'),
	'dimmer_gamma': ('Dimmergamma', 'float'),
	'palette': ('Palette', 'enum'),
	'custom_color1': ('Custompalette1', 'color_rgb'),
	'custom_color2': ('Custompalette2', 'color_rgb'),
	'custom_color3': ('Custompalette3', 'color_rgb'),
	'custom_color4': ('Custompalette4', 'color_rgb'),
	'custom_color5': ('Custompalette5', 'color_rgb'),
	'color_curve': ('Colorcurve', 'float'),
	'color_fade': ('Colorsmooth', 'float'),
	'color_speed': ('Colorspeed', 'float'),
	'color_phase': ('Colorphase', 'float'),
	'bar_phase': ('Barphase', 'float'),
	'audio_source': ('Audiobus', 'enum'),
	'audio_amount': ('Audioamount', 'float'),
	'smooth_factor': ('Smoothfactor', 'float'),
	'global_smooth': ('Globalsmooth', 'float'),
	'agc_release': ('Agcrelease', 'float'),
	'min_range': ('Minrange', 'float'),
	'kick_enable': ('Kickenable', 'bool'),
	'kick_threshold': ('Kickthresh', 'float'),
	'kick_boost': ('Kickboost', 'float'),
	'kick_decay': ('Kickdecay', 'float'),
	'kick_cooldown': ('Kickcooldown', 'float'),
	'kick_smooth': ('Kicksmooth', 'float'),
	'fan': ('Fan', 'float'),
}

LABELS = {
	'level': 'Livello', 'min_dimmer': 'Dimmer minimo', 'max_dimmer': 'Dimmer massimo',
	'dimmer_boost': 'Boost dimmer', 'dimmer_gamma': 'Gamma dimmer', 'palette': 'Palette',
	'custom_color1': 'Colore custom 1', 'custom_color2': 'Colore custom 2',
	'custom_color3': 'Colore custom 3', 'custom_color4': 'Colore custom 4',
	'custom_color5': 'Colore custom 5', 'color_curve': 'Curva colore',
	'color_fade': 'Dissolvenza colore', 'color_speed': 'Velocità colore',
	'color_phase': 'Fase colore', 'bar_phase': 'Fase tra le luci',
	'audio_source': 'Sorgente audio', 'audio_amount': 'Quanto segue la musica',
	'smooth_factor': 'Morbidezza livello', 'global_smooth': 'Morbidezza globale',
	'agc_release': 'Rilascio AGC', 'min_range': 'Range minimo', 'kick_enable': 'Kick',
	'kick_threshold': 'Soglia kick', 'kick_boost': 'Boost kick', 'kick_decay': 'Decadimento kick',
	'kick_cooldown': 'Pausa tra kick', 'kick_smooth': 'Morbidezza kick', 'fan': 'Ventola',
}

# help shown by the Plancia when the par has no help of its own
HELP = {
	'level': 'Livello del gruppo 0-1, dopo il look (come il fader /dmx/group).',
	'min_dimmer': 'Livello 0-255 a cui il rig scende senza musica.',
	'max_dimmer': 'Livello 0-255 massimo; con "Quanto segue la musica" a 0 il rig sta fermo qui.',
	'dimmer_boost': 'Quanto il livello audio spinge verso il massimo.',
	'dimmer_gamma': 'Curva del livello per le luci SENZA canale dimmer (es. RGBW): '
		'il livello si moltiplica dentro i colori con questa gamma.',
	'bar_phase': 'Sfasamento di colore tra una luce e la successiva (0 = tutte uguali).',
	'audio_source': 'Quale sorgente audio condivisa muove il rig (audio_engine, sorgente A o B). '
		'Tutti i rig su A = una sola sorgente; A e B = due sorgenti diverse.',
}

SECTIONS = {
	'chase': [
		('dimmer', 'Livello e dimmer', ['level', 'min_dimmer', 'max_dimmer', 'dimmer_boost', 'dimmer_gamma']),
		('color', 'Colore', ['palette', 'custom_color1', 'custom_color2', 'custom_color3',
			'custom_color4', 'custom_color5', 'color_curve', 'color_fade', 'color_speed',
			'color_phase', 'bar_phase']),
		('audio', 'Audio', ['audio_source', 'audio_amount', 'smooth_factor', 'global_smooth',
			'agc_release', 'min_range']),
		('kick', 'Kick', ['kick_enable', 'kick_threshold', 'kick_boost', 'kick_decay',
			'kick_cooldown', 'kick_smooth']),
	],
	'level': [
		('level', 'Livello', ['level', 'fan']),
	],
}

# theoretical starting points over the par defaults (min/max on 0-255).
# no_dimmer: level k = (dimmer/255)^gamma multiplies the RGB, 90 -> ~10%.
STARTERS = {
	'dimmer': {'min_dimmer': 30.0, 'max_dimmer': 255.0, 'dimmer_boost': 1.0},
	'no_dimmer': {'min_dimmer': 90.0, 'max_dimmer': 255.0, 'dimmer_boost': 1.0, 'dimmer_gamma': 2.2},
}
STARTER_LABELS = {'dimmer': 'Partenza: luci con canale dimmer',
	'no_dimmer': 'Partenza: luci senza canale dimmer (RGB/RGBW)'}
PRESET_COLS = ['name', 'kind', 'label', 'values', 'source', 'updated']
# fallback when show_logic is not reachable (same list as there)
_CALIBRATION_PARS = ['Mindimmer', 'Maxdimmer', 'Dimmerboost', 'Dimmergamma', 'Agcrelease',
	'Minrange', 'Kickthresh', 'Kickboost', 'Kickdecay', 'Kickcooldown', 'Kicksmooth']

_last = {'result': None}


# ---------------------------------------------------------------- basics

def _home():
	# this DAT lives in /project1/gaia_services; rig COMPs are under /project1
	return me.parent().parent()


def _fl():
	return _home().op('dmx_patch/fixture_logic').module


def _kind_fields(kind):
	return [f for _k, _l, fields in SECTIONS.get(kind, []) for f in fields]


def _calibration_pars():
	sl = _home().op('show/show_logic')
	return list(getattr(sl.module, 'RIG_CALIBRATION_PARS', _CALIBRATION_PARS)) if sl else _CALIBRATION_PARS


def calibration_fields(kind):
	"""Fields of a kind that are calibration (not touched by scenes)."""
	pars = set(_calibration_pars())
	return [f for f in _kind_fields(kind) if FIELDS[f][0] in pars]


def rigs():
	"""[{group, label, alias, kind, comp}] of the chase/level rigs that
	exist, in the order of the groups table."""
	out = []
	for g in _fl().groups():
		kind = g.get('kind', '')
		comp = _home().op(g.get('comp', '')) if g.get('comp') else None
		if kind in SECTIONS and comp is not None:
			out.append({'group': g['group'], 'label': g.get('label') or g['group'],
				'alias': g.get('alias', ''), 'kind': kind, 'comp': comp})
	return out


def _rig(name):
	g = _fl().resolve_group(name)
	for r in rigs():
		if r['group'] == g:
			return r
	return None


def _pars(comp, field):
	"""The Par(s) of a field on a rig COMP ([] when missing)."""
	par, typ = FIELDS[field]
	names = [par + c for c in 'rgb'] if typ == 'color_rgb' else [par]
	ps = [comp.par[n] for n in names]
	return ps if all(p is not None for p in ps) else []


def _range(p):
	"""Real control range: the clamp if set, otherwise the slider range."""
	lo = p.min if p.clampMin else p.normMin
	hi = p.max if p.clampMax else p.normMax
	return [round(float(lo), 6), round(float(hi), 6)]


def _schema(comp, field):
	ps = _pars(comp, field)
	if not ps:
		return None
	typ = FIELDS[field][1]
	p = ps[0]
	d = {'type': typ, 'label': LABELS.get(field, field),
		'role': 'calibration' if FIELDS[field][0] in _calibration_pars() else 'look'}
	h = HELP.get(field, '') or str(p.help or '').strip()
	if h:
		d['help'] = h
	if typ == 'float':
		d['range'] = _range(p)
		d['default'] = round(float(p.default), 6)
	elif typ == 'enum':
		d['options'] = list(p.menuNames)
		if list(p.menuLabels) != d['options']:
			d['labels'] = list(p.menuLabels)   # same order as options ("OPS, 51")
		d['default'] = str(p.default)
	elif typ == 'color_rgb':
		d['range'] = [0.0, 1.0]
	elif typ == 'bool':
		d['default'] = bool(p.default)
	return d


def _lights(rig):
	return [f for f in _fl().rows(rig['group']) if f['enabled']]


def _all_have_dimmer(rig):
	"""True / False for a chase rig with lights, None without lights."""
	fx = _lights(rig)
	if rig['kind'] != 'chase' or not fx:
		return None
	fl = _fl()
	chans = [fl.profile_channels(rig['group'], f['profile']) or [] for f in fx]
	return all(any(c.startswith('dimmer') for c in ch) for ch in chans)


def starter_name(rig):
	"""'dimmer' | 'no_dimmer' | None: the starting preset fitting a rig."""
	d = _all_have_dimmer(rig)
	return None if d is None else ('dimmer' if d else 'no_dimmer')


def starter_values(kind, which, comp):
	"""Calibration values of a starter: par defaults + STARTERS[which]."""
	out = {}
	for f in calibration_fields(kind):
		ps = _pars(comp, f)
		if ps and FIELDS[f][1] == 'float':
			out[f] = round(float(ps[0].default), 6)
	out.update({f: v for f, v in STARTERS.get(which, {}).items() if f in out})
	return out


def _inactive(rig):
	"""{field: reason} of fields that do nothing on this rig today."""
	out = {}
	if _all_have_dimmer(rig):
		out['dimmer_gamma'] = 'tutte le luci del gruppo hanno un canale dimmer: ' \
			'la gamma agisce solo sui profili senza dimmer'
	if rig['kind'] == 'chase' and _lights(rig) and len({f['unit'] for f in _lights(rig)}) < 2:
		out['bar_phase'] = 'una sola luce nel gruppo'
	return out


# ---------------------------------------------------------------- read

def matrix():
	"""dmx_matrix 'rig_config' section (structure, no live values)."""
	rs = rigs()
	fields = {}
	for kind in SECTIONS:
		sample = next((r['comp'] for r in rs if r['kind'] == kind), None)
		if sample is None:
			continue
		fields[kind] = {}
		for f in _kind_fields(kind):
			s = _schema(sample, f)
			if s is not None:
				fields[kind][f] = s
	kinds = {kind: {'sections': [{'key': k, 'label': l, 'fields': [f for f in fs if f in fields.get(kind, {})]}
		for k, l, fs in secs]} for kind, secs in SECTIONS.items() if kind in fields}
	fl = _fl()
	groups = []
	for r in rs:
		fx = [f for f in fl.rows(r['group']) if f['enabled']]
		groups.append({'group': r['group'], 'label': r['label'], 'alias': r['alias'],
			'kind': r['kind'], 'comp': r['comp'].name, 'fixtures': len(fx),
			'profiles': sorted({f['profile'] for f in fx}), 'inactive': _inactive(r),
			'starter': starter_name(r)})
	starters = {}
	for kind in SECTIONS:
		sample = next((r['comp'] for r in rs if r['kind'] == kind), None)
		if sample is None or not calibration_fields(kind):
			continue
		starters[kind] = {w: {'label': STARTER_LABELS[w], 'values': starter_values(kind, w, sample)}
			for w in STARTERS}
	rw = {'kind': 'param', 'type': 'json', 'access': 'rw'}
	w = {'kind': 'param', 'type': 'json', 'access': 'w'}
	r_ = {'kind': 'param', 'type': 'json', 'access': 'r'}
	return {
		'params': {
			'dmx_rig_config': rw,
			'dmx_rig_config_result': r_,
			'dmx_rig_presets': r_,
			'dmx_rig_preset_store': w,
			'dmx_rig_preset_recall': w,
			'dmx_rig_preset_copy': w,
			'dmx_rig_preset_remove': w,
		},
		'kinds': kinds,
		'fields': fields,
		'calibration': {kind: calibration_fields(kind) for kind in kinds},
		'starters': starters,
		'groups': groups,
	}


def _value(comp, field):
	ps = _pars(comp, field)
	if not ps:
		return None
	typ = FIELDS[field][1]
	if typ == 'color_rgb':
		return [round(float(p.eval()), 4) for p in ps]
	if typ == 'enum':
		return str(ps[0].eval())
	if typ == 'bool':
		return bool(ps[0].eval())
	return round(float(ps[0].eval()), 4)


def values():
	"""dmx_rig_config: {group: {field: value}} of every rig."""
	out = {}
	for r in rigs():
		vals = {}
		for f in _kind_fields(r['kind']):
			v = _value(r['comp'], f)
			if v is not None:
				vals[f] = v
		out[r['group']] = vals
	return out


def result():
	return _last['result']


# ---------------------------------------------------------------- write

def _requests(req):
	"""[(group ref, {field: value})] from the accepted shapes."""
	if isinstance(req, list):
		items = req
	elif isinstance(req, dict) and isinstance(req.get('groups'), dict):
		items = [{'group': g, 'values': v} for g, v in req['groups'].items()]
	elif isinstance(req, dict) and 'group' in req:
		items = [req]
	else:
		raise ValueError('atteso {group, values}, {groups: {...}} o una lista')
	out = []
	for it in items:
		if not isinstance(it, dict) or not isinstance(it.get('values'), dict):
			raise ValueError('ogni voce vuole group e values {campo: valore}')
		out.append((it.get('group'), it['values']))
	return out


def _check(comp, field, value):
	"""Validated value ready to write, or raises ValueError."""
	typ = FIELDS[field][1]
	ps = _pars(comp, field)
	if typ == 'float':
		try:
			v = float(value)
		except (TypeError, ValueError):
			raise ValueError('%s: numero atteso, arrivato %r' % (field, value))
		lo, hi = _range(ps[0])
		if not lo - 1e-9 <= v <= hi + 1e-9:
			raise ValueError('%s: %s fuori range [%s, %s]' % (field, v, lo, hi))
		return v
	if typ == 'enum':
		names = list(ps[0].menuNames)
		if str(value) in names:
			return str(value)
		try:
			i = int(value)
		except (TypeError, ValueError):
			i = None
		if i is not None and not isinstance(value, bool) and 0 <= i < len(names):
			return names[i]
		raise ValueError('%s: %r non valido (opzioni: %s)' % (field, value, ', '.join(names)))
	if typ == 'color_rgb':
		try:
			rgb = [float(c) for c in value]
		except (TypeError, ValueError):
			rgb = []
		if len(rgb) != 3 or not all(0.0 <= c <= 1.0 for c in rgb):
			raise ValueError('%s: atteso [r, g, b] con valori 0-1, arrivato %r' % (field, value))
		return rgb
	if typ == 'bool':
		if isinstance(value, bool):
			return value
		s = str(value).strip().lower()
		if s in ('1', 'true', 'on', 'yes'):
			return True
		if s in ('0', 'false', 'off', 'no'):
			return False
		raise ValueError('%s: atteso true/false, arrivato %r' % (field, value))
	raise ValueError('%s: tipo sconosciuto' % field)


def _finish(res):
	_last['result'] = res
	if res['errors']:
		raise ValueError('%s: %s' % (res.get('action', 'dmx_rig_config'), '; '.join(res['errors'])))
	return res


def _new_result(action, rid):
	return {'action': action, 'request_id': rid, 'ts': int(time.time() * 1000), 'ok': True,
		'applied': {}, 'errors': []}


def apply(req, action='set', rid=None, extra=None):
	"""dmx_rig_config write: validate everything, then write everything.
	rid / extra: request_id and fields for the result of a preset action."""
	if rid is None and isinstance(req, dict):
		rid = req.get('request_id')
	errors = []
	plan = []   # (rig, {field: value})
	try:
		items = _requests(req)
	except ValueError as e:
		items = []
		errors.append(str(e))
	for ref, vals in items:
		rig = _rig(ref)
		if rig is None:
			errors.append('gruppo %r inesistente o non e\' un rig chase/level' % (ref,))
			continue
		allowed = _kind_fields(rig['kind'])
		ok = {}
		for field, value in vals.items():
			if field not in allowed or not _pars(rig['comp'], field):
				errors.append('%s: campo %r non disponibile (tipo %s)' % (rig['group'], field, rig['kind']))
				continue
			try:
				ok[field] = _check(rig['comp'], field, value)
			except ValueError as e:
				errors.append('%s: %s' % (rig['group'], e))
		if 'min_dimmer' in allowed and ('min_dimmer' in ok or 'max_dimmer' in ok):
			lo = ok.get('min_dimmer', _value(rig['comp'], 'min_dimmer'))
			hi = ok.get('max_dimmer', _value(rig['comp'], 'max_dimmer'))
			if lo is not None and hi is not None and lo > hi:
				errors.append('%s: min_dimmer %s maggiore di max_dimmer %s' % (rig['group'], lo, hi))
		plan.append((rig, ok))
	res = _new_result(action, rid)
	res.update(extra or {})
	res['ok'], res['errors'] = not errors, errors
	if not errors:
		for rig, ok in plan:
			comp = rig['comp']
			for field, v in ok.items():
				ps = _pars(comp, field)
				typ = FIELDS[field][1]
				if typ == 'color_rgb':
					for p, c in zip(ps, v):
						p.val = c
				elif typ == 'bool':
					ps[0].val = 1 if v else 0
				else:
					ps[0].val = v
			res['applied'].setdefault(rig['group'], []).extend(sorted(ok))
	return _finish(res)


# ---------------------------------------------------------------- presets

def _table():
	t = me.parent().op('rig_presets')
	if t.numRows == 0 or t[0, 0] is None or t[0, 0].val != PRESET_COLS[0]:
		t.clear()
		t.appendRow(PRESET_COLS)
	return t


def presets():
	"""dmx_rig_presets: [{name, kind, label, values, source, updated}]."""
	t = _table()
	out = []
	for r in range(1, t.numRows):
		try:
			vals = json.loads(t[r, 'values'].val or '{}')
		except ValueError:
			vals = {}
		try:
			upd = int(t[r, 'updated'].val)
		except ValueError:
			upd = 0
		out.append({'name': t[r, 'name'].val, 'kind': t[r, 'kind'].val,
			'label': t[r, 'label'].val or t[r, 'name'].val, 'values': vals,
			'source': t[r, 'source'].val, 'updated': upd})
	return out


def _preset(name):
	return next((p for p in presets() if p['name'] == name), None)


def _arg(req):
	if not isinstance(req, dict):
		raise ValueError('atteso un oggetto JSON')
	return req, req.get('request_id')


def _targets(req):
	g = req.get('groups', req.get('group'))
	return [g] if isinstance(g, str) else list(g or [])


def preset_store(req):
	"""{name, group, label?}: save the group's calibration as a preset."""
	req, rid = _arg(req)
	res = _new_result('preset_store', rid)
	name = str(req.get('name') or '').strip()
	rig = _rig(req.get('group'))
	if not name or len(name) > 40 or '\t' in name or '\n' in name:
		res['errors'].append('name: da 1 a 40 caratteri, senza tab o a capo')
	if rig is None:
		res['errors'].append('gruppo %r inesistente o non e\' un rig chase/level' % (req.get('group'),))
	elif not calibration_fields(rig['kind']):
		res['errors'].append('%s: un rig %s non ha taratura' % (rig['group'], rig['kind']))
	old = _preset(name) if name else None
	if rig is not None and old and old['kind'] != rig['kind']:
		res['errors'].append('il preset %r esiste gia\' per i rig %s' % (name, old['kind']))
	if res['errors']:
		res['ok'] = False
		return _finish(res)
	vals = {f: _value(rig['comp'], f) for f in calibration_fields(rig['kind'])}
	vals = {f: v for f, v in vals.items() if v is not None}
	label = str(req.get('label') or (old['label'] if old else '') or name).replace('\t', ' ').replace('\n', ' ')
	row = [name, rig['kind'], label, json.dumps(vals, sort_keys=True), rig['group'], str(res['ts'])]
	t = _table()
	for r in range(1, t.numRows):
		if t[r, 'name'].val == name:
			for c, v in zip(PRESET_COLS, row):
				t[r, c] = v
			break
	else:
		t.appendRow(row)
	res['applied'] = {rig['group']: sorted(vals)}
	res['preset'] = name
	return _finish(res)


def preset_recall(req):
	"""{name | starter: true, group | groups}: write a preset (or each
	group's starter) on the groups, all or nothing."""
	req, rid = _arg(req)
	res = _new_result('preset_recall', rid)
	targets = _targets(req)
	if not targets:
		res['errors'].append('group o groups mancante')
	items = []
	if req.get('starter'):
		for ref in targets:
			rig = _rig(ref)
			which = starter_name(rig) if rig else None
			if rig is None:
				res['errors'].append('gruppo %r inesistente o non e\' un rig chase/level' % (ref,))
			elif which is None:
				res['errors'].append('%s: nessuna luce in patch, partenza non definita' % rig['group'])
			else:
				items.append({'group': rig['group'], 'values': starter_values(rig['kind'], which, rig['comp'])})
	else:
		p = _preset(str(req.get('name') or ''))
		if p is None:
			res['errors'].append('preset %r inesistente' % (req.get('name'),))
		else:
			for ref in targets:
				rig = _rig(ref)
				if rig is not None and rig['kind'] != p['kind']:
					res['errors'].append('%s: il preset %r e\' per i rig %s' % (rig['group'], p['name'], p['kind']))
				else:
					items.append({'group': ref, 'values': p['values']})   # apply() checks the group
			res['preset'] = p['name']
	if res['errors']:
		res['ok'] = False
		return _finish(res)
	extra = {'starter': True} if req.get('starter') else {'preset': res.get('preset')}
	return apply(items, action='preset_recall', rid=rid, extra=extra)


def preset_copy(req):
	"""{from: group, to: group | [groups]}: calibration of one rig onto others."""
	req, rid = _arg(req)
	res = _new_result('preset_copy', rid)
	src = _rig(req.get('from'))
	to = req.get('to')
	to = [to] if isinstance(to, str) else list(to or [])
	if src is None:
		res['errors'].append('from: gruppo %r inesistente o non e\' un rig chase/level' % (req.get('from'),))
	if not to:
		res['errors'].append('to mancante')
	items = []
	if src is not None:
		vals = {f: _value(src['comp'], f) for f in calibration_fields(src['kind'])}
		for ref in to:
			rig = _rig(ref)
			if rig is not None and rig['kind'] != src['kind']:
				res['errors'].append('%s: tipo %s diverso da %s (%s)' % (rig['group'], rig['kind'], src['group'], src['kind']))
			else:
				items.append({'group': ref, 'values': vals})
	if res['errors']:
		res['ok'] = False
		return _finish(res)
	return apply(items, action='preset_copy', rid=rid, extra={'from': src['group']})


def preset_remove(req):
	"""name (or {name, request_id?})."""
	rid = req.get('request_id') if isinstance(req, dict) else None
	name = str(req.get('name') if isinstance(req, dict) else req or '').strip()
	res = _new_result('preset_remove', rid)
	t = _table()
	for r in range(1, t.numRows):
		if t[r, 'name'].val == name:
			t.deleteRow(r)
			res['preset'] = name
			return _finish(res)
	res['ok'] = False
	res['errors'].append('preset %r inesistente' % (name,))
	return _finish(res)
