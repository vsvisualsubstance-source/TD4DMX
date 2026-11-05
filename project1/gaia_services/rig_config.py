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
                         default?, options?}}}  types: float | enum |
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

A write is a live tweak like one from the TD UI: it holds until the show
timeline moves that par again (show_logic).
"""
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

_last = {'result': None}


# ---------------------------------------------------------------- basics

def _home():
	# this DAT lives in /project1/gaia_services; rig COMPs are under /project1
	return me.parent().parent()


def _fl():
	return _home().op('dmx_patch/fixture_logic').module


def _kind_fields(kind):
	return [f for _k, _l, fields in SECTIONS.get(kind, []) for f in fields]


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
	d = {'type': typ, 'label': LABELS.get(field, field)}
	h = str(p.help or '').strip() or HELP.get(field, '')
	if h:
		d['help'] = h
	if typ == 'float':
		d['range'] = _range(p)
		d['default'] = round(float(p.default), 6)
	elif typ == 'enum':
		d['options'] = list(p.menuNames)
		d['default'] = str(p.default)
	elif typ == 'color_rgb':
		d['range'] = [0.0, 1.0]
	elif typ == 'bool':
		d['default'] = bool(p.default)
	return d


def _inactive(rig):
	"""{field: reason} of fields that do nothing on this rig today."""
	out = {}
	if rig['kind'] != 'chase':
		return out
	fl = _fl()
	fx = [f for f in fl.rows(rig['group']) if f['enabled']]
	if fx:
		chans = {f['profile']: fl.profile_channels(rig['group'], f['profile']) or [] for f in fx}
		if all(any(c.startswith('dimmer') for c in ch) for ch in chans.values()):
			out['dimmer_gamma'] = 'tutte le luci del gruppo hanno un canale dimmer: ' \
				'la gamma agisce solo sui profili senza dimmer'
		if len({f['unit'] for f in fx}) < 2:
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
			'profiles': sorted({f['profile'] for f in fx}), 'inactive': _inactive(r)})
	return {
		'params': {
			'dmx_rig_config': {'kind': 'param', 'type': 'json', 'access': 'rw'},
			'dmx_rig_config_result': {'kind': 'param', 'type': 'json', 'access': 'r'},
		},
		'kinds': kinds,
		'fields': fields,
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


def apply(req):
	"""dmx_rig_config write: validate everything, then write everything."""
	rid = req.get('request_id') if isinstance(req, dict) else None
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
	res = {'request_id': rid, 'ts': int(time.time() * 1000), 'ok': not errors,
		'applied': {}, 'errors': errors}
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
	_last['result'] = res
	if errors:
		raise ValueError('dmx_rig_config: ' + '; '.join(errors))
	return res
