"""group_logic -- creates and removes patch GROUPS at runtime (Plancia
"design palco", GAIA_PLANCIA_INTEGRATION.md channel 1b). One group = one
rig COMP + one row of the `groups` table (group, comp, select, profiles,
alias, kind):

  kind 'chase'  copy of dmx_audio_chase, cloned from it (same engine as
                rig_a / rig_b: palette, audio, kick). Fixtures use the
                rig's fixture_profiles.
  kind 'level'  minimal rig: every unit outputs full intensity on its
                intensity channels and Fan on 'fan'; the group level
                (Level par, applied in universe_build with Master/Strobe)
                does the rest. For haze, blinder and other single-level
                lights. Profiles: level_profiles inside the COMP.

The built-in groups (rig_a, rig_b, heads) are never removed here. New rigs
are saved inside project1.tox (no own externaltox, like dmx_audio_chase_b).
Called by gaia_services/dmx_services.py (dmx_group_add / dmx_group_remove).
"""
import re

KINDS = ('chase', 'level')
PROTECTED = ('rig_a', 'rig_b', 'heads')
# would collide with the dmx_<key>_* names of gaia_services/dmx_services
RESERVED = ('a', 'b', 'group', 'fixture', 'fixtures', 'patch', 'scan', 'output', 'blackout',
	'model', 'models', 'type', 'types', 'universe', 'groups')
CHASE_MASTER = 'dmx_audio_chase'

# profiles of 'level' rigs: the catalog models of kind 'level'
# (catalog_logic; see COLOUR in universe_build_callbacks for which channels
# follow Level/Master/Strobe). Fallback when the catalog has none:
LEVEL_PROFILES = [
	('Dimmer 1CH', 'dimmer'),
	('Haze 2CH', 'output fan'),
]
DEFAULT_LEVEL_PROFILE = {'haze': 'Haze 2CH'}


def _level_profiles():
	"""[(name, channels)] of the level models in the catalog."""
	cat = _patch().op('catalog_logic')
	rows = cat.module.profile_rows('level')[1:] if cat is not None else []
	return [(r[0], r[1]) for r in rows] or LEVEL_PROFILES

ROW_Y = -3000      # network row of the rigs created here (below the heads)
ROW_X0 = -600
SLOT = 400

_NAME = re.compile(r'^[a-z][a-z0-9_]{0,23}$')


def _patch():
	return me.parent()


def _home():
	return me.parent().parent()


def _fl():
	return _patch().op('fixture_logic').module


def _groups_table():
	return _patch().op('groups')


def _free_slot():
	home = _home()
	taken = [(c.nodeX, c.nodeX + c.nodeWidth) for c in home.children
		if abs(c.nodeY - ROW_Y) < 200]
	x = ROW_X0
	while any(lo < x + 200 and x < hi for lo, hi in taken):
		x += SLOT
	return x


def _build_level_rig(name):
	home = _home()
	comp = home.create(baseCOMP, name)
	page = comp.appendCustomPage('Fixture')

	p = page.appendFloat('Level', label='Level')[0]
	p.default = 1.0
	p.min, p.max, p.clampMin, p.clampMax = 0.0, 1.0, True, True
	p.normMin, p.normMax = 0.0, 1.0
	p.help = ('Livello del gruppo 0-1 (Plancia /dmx/group/<gruppo>). '
		'Applicato in dmx_patch/universe_build ai canali di intensita\', '
		'insieme a Master e Strobe.')
	comp.par.Level = 1.0

	p = page.appendFloat('Fan', label='Fan')[0]
	p.default = 0.5
	p.min, p.max, p.clampMin, p.clampMax = 0.0, 1.0, True, True
	p.normMin, p.normMax = 0.0, 1.0
	p.help = 'Canale "fan" delle macchine haze (0-1). Non segue Level/Master.'
	comp.par.Fan = 0.5

	p = page.appendInt('Count', label='Count')[0]
	p.default = 1
	p.min, p.clampMin = 1, True
	p.normMin, p.normMax = 1, 16
	p.help = 'Numero di unita\' del gruppo (patch rapida, riflessa dalla tabella fixtures).'
	p.startSection = True

	p = page.appendInt('Startaddress', label='Start Address')[0]
	p.default = 1
	p.min, p.max, p.clampMin, p.clampMax = 1, 512, True, True
	p.normMin, p.normMax = 1, 512
	p.help = 'Indirizzo DMX della prima unita\' (riflesso dalla tabella fixtures).'

	profiles = _level_profiles()
	p = page.appendStrMenu('Profile', label='Profile')[0]
	p.menuNames = [n for n, _ in profiles]
	p.menuLabels = [n for n, _ in profiles]
	p.default = profiles[0][0]
	p.help = 'Profilo di default delle fixture del gruppo (tabella level_profiles).'

	p = page.appendStrMenu('Outputport', label='Output Port')[0]
	p.menuSource = "tdu.TableMenu(me.parent().op('dmx_patch/ports'), nameCol='port_id', labelCol='label')"
	p.help = 'Porta Art-Net del gruppo ("<ip nodo>:<porta>", dalla scansione di dmx_patch).'

	p = page.appendToggle('Patchenable', label='Patch Enable')[0]
	p.default = True
	p.help = 'Spento = il gruppo resta in patch ma non viene inviato.'
	comp.par.Patchenable = True

	prof = comp.create(tableDAT, 'level_profiles')
	prof.clear()
	prof.appendRow(['name', 'channels'])
	for n, ch in profiles:
		prof.appendRow([n, ch])
	prof.nodeX, prof.nodeY = 0, 0

	cb = comp.create(textDAT, 'level_out_callbacks')
	cb.text = LEVEL_OUT_CALLBACKS
	cb.nodeX, cb.nodeY = 0, -200

	out = comp.create(scriptCHOP, 'level_out')
	# TD docks its own default callbacks DAT to a new Script CHOP (here
	# 'level_out_callbacks1', the name is taken): drop it, ours is cb
	for d in list(out.docked):
		if d != cb:
			d.destroy()
	out.par.callbacks = 'level_out_callbacks'
	out.nodeX, out.nodeY = 400, 0
	cb.dock = out
	cb.nodeX, cb.nodeY = out.nodeX, out.nodeY - cb.nodeHeight - 30   # hug the host
	return comp


LEVEL_OUT_CALLBACKS = '''"""level_out -- one channel per unit attribute (unit<u>_<attr>, DMX order of
the unit's profile, see dmx_patch/group_logic). Intensity channels (dimmer*
and colour/output) at full scale (255): Level/Master/Strobe are applied in
dmx_patch/universe_build. 'fan' follows the Fan par; any other role
(strobe, mode, placeholder ch<N> of a catalog model with only its channel
count) is 0. Cooks on change only (tables + pars)."""
FULL = 255.0
INTENSITY = ('red', 'green', 'blue', 'white', 'amber', 'uv', 'output')


def onSetupParameters(scriptOp):
	return


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.numSamples = 1
	comp = parent()
	fl = comp.parent().op('dmx_patch/fixture_logic').module
	group = fl.group_of(comp)
	if group is None:
		return
	fan = float(comp.par.Fan.eval()) * FULL
	for u, prof in enumerate(fl.unit_profiles(comp, cached=False), 1):
		for attr in fl.profile_channels(group, prof) or []:
			c = scriptOp.appendChan('unit%d_%s' % (u, attr))
			c[0] = fan if attr == 'fan' else 				FULL if attr.startswith('dimmer') or attr in INTENSITY else 0.0
	return
'''


def _build_chase_rig(name):
	home = _home()
	master = home.op(CHASE_MASTER)
	comp = home.copy(master, name=name)
	comp.par.clone = CHASE_MASTER
	comp.par.externaltox = ''
	for t in list(comp.tags):
		comp.tags.remove(t)
	return comp


def add_group(group, kind='chase', profile=None, port_id=None, count=1, start=None, alias='',
		label='', source='td'):
	"""Create a group and its rig COMP, then `count` fixtures (0 = none:
	a group defined ahead of its lights, dmx_groups) at consecutive free
	addresses on port_id. Returns the group name."""
	fl = _fl()
	group = str(group or '').strip()
	kind = str(kind or 'chase').strip()
	alias = str(alias or '').strip()
	_ensure_columns()
	if not _NAME.match(group):
		raise ValueError('nome gruppo %r non valido (minuscole, cifre, _; max 24)' % group)
	if group in RESERVED:
		raise ValueError('nome gruppo %r riservato (%s)' % (group, ', '.join(RESERVED)))
	if kind not in KINDS:
		raise ValueError('kind %r non valido (%s)' % (kind, ', '.join(KINDS)))
	if fl.resolve_group(group) is not None or (alias and fl.resolve_group(alias) is not None):
		raise ValueError('gruppo %r esiste gia\'' % (alias or group))
	name = 'rig_' + group
	if _home().op(name) is not None:
		raise ValueError('esiste gia\' un operatore %s' % name)
	ports = _patch().op('ports')
	port_ids = [ports[r, 'port_id'].val for r in range(1, ports.numRows)]
	port_id = str(port_id or (port_ids[0] if port_ids else ''))
	if port_id not in port_ids:
		raise ValueError('porta %r sconosciuta (disponibili: %s)' % (port_id, ', '.join(port_ids)))
	count = max(0, int(1 if count is None else count))

	comp = _build_chase_rig(name) if kind == 'chase' else _build_level_rig(name)
	comp.nodeX, comp.nodeY = _free_slot(), ROW_Y
	try:
		comp.par.Outputport = port_id
		t = _groups_table()
		row = {'group': group, 'comp': name,
			'select': 'dmx_select' if kind == 'chase' else 'level_out',
			'profiles': 'fixture_profiles' if kind == 'chase' else 'level_profiles',
			'alias': alias, 'kind': kind, 'label': str(label or '').strip(), 'source': source}
		t.appendRow([row.get(t[0, c].val, '') for c in range(t.numCols)])
		if profile is None:
			profile = DEFAULT_LEVEL_PROFILE.get(group, fl.default_profile(group)) \
				if kind == 'level' else fl.default_profile(group)
		if fl.profile_channels(group, profile) is None:
			raise ValueError('profilo %r non esiste per %s (disponibili: %s)' % (
				profile, kind, ', '.join(fl.profile_names(group))))
		nch = len(fl.profile_channels(group, profile))
		if count == 0:
			return group
		addr = int(start) if start else fl.next_free_address(port_id, nch * count)
		if addr is None:
			raise ValueError('nessuno spazio libero su %s per %d canali' % (port_id, nch * count))
		for i in range(count):
			fl.add_fixture(group, profile=profile, port_id=port_id,
				address=addr + i * nch, unit=i + 1)
	except Exception:
		_drop(group, name)
		raise
	return group


def _drop(group, name):
	fl = _fl()
	t = fl.table()
	for r in range(t.numRows - 1, 0, -1):
		if t[r, 'group'].val == group:
			t.deleteRow(r)
	g = _groups_table()
	for r in range(g.numRows - 1, 0, -1):
		if g[r, 'group'].val == group:
			g.deleteRow(r)
	comp = _home().op(name)
	if comp is not None:
		comp.destroy()


def remove_group(group):
	"""Remove a group created by add_group: its fixtures, its groups row and
	its rig COMP. Built-in groups are refused."""
	fl = _fl()
	g = fl.resolve_group(group)
	if g is None:
		raise ValueError('gruppo %r non trovato' % group)
	if g in PROTECTED:
		raise ValueError('il gruppo %s e\' di base e non si rimuove da qui' % g)
	_drop(g, fl.group_info(g)['comp'])
	return g


# ---------------------------------------------------------------- Plancia groups
# The groups are Plancia's (GAIA_INTERFACE "TD/Win-PD, 21"): Plancia sends
# its list with dmx_groups. TD's three engines (rig_a, rig_b, heads) are
# BOUND to a Plancia name (their alias: front, back, mh); any other group is
# created here as a rig of its kind. Strict (dmx_patch Groupstrict, Gaia
# service dmx_groups_strict): TD no longer creates a group by itself from
# a fixture or a type -- an undefined group is an error.

GROUP_COLUMNS = ('label', 'source')
SET_KINDS = KINDS + ('heads', 'none')


def _ensure_columns():
	t = _groups_table()
	for c in GROUP_COLUMNS:
		if t[0, c] is None:
			t.appendCol([c] + [''] * (t.numRows - 1))
	return t


def is_strict():
	p = getattr(_patch().par, 'Groupstrict', None)
	return bool(p.eval()) if p is not None else False


def require_defined(group):
	"""Raise when strict and `group` is not defined (name or alias)."""
	if is_strict() and _fl().resolve_group(group) is None:
		raise ValueError('gruppo %r non definito: la Plancia deve mandarlo con dmx_groups '
			'(gruppi solo da Plancia attivo)' % group)


def groups_list():
	"""Groups as Plancia sees them: group = the Plancia name (alias, else
	the TD name), td_group = TD's name, kind, label, builtin, fixtures,
	source (builtin | td = created by TD from a fixture/type | plancia)."""
	fl = _fl()
	t = _ensure_columns()
	out = []
	for g in fl.groups():
		out.append({
			'group': g.get('alias') or g['group'], 'td_group': g['group'],
			'kind': g.get('kind') or 'chase', 'label': g.get('label') or '',
			'builtin': g['group'] in PROTECTED, 'fixtures': len(fl.rows(g['group'])),
			'source': g.get('source') or ('builtin' if g['group'] in PROTECTED else 'td')})
	return out


def _set_cells(group, **cells):
	t = _ensure_columns()
	for r in range(1, t.numRows):
		if t[r, 'group'].val == group:
			for k, v in cells.items():
				t[r, k] = v
			return


def set_groups(items, source='plancia'):
	"""Align TD's groups to Plancia's list (dmx_groups). Item: {group,
	kind: chase|level|heads|none, label?, bind?: rig_a|rig_b|heads}.
	Everything is validated before anything changes. Then: bind sets the
	alias of a built-in engine; an existing group (name or alias) gets its
	label; a missing chase/level group is created empty; kind none (LED
	wall) is only acknowledged. Created groups absent from the list are
	removed when empty, kept (and reported) when they still hold fixtures.
	Returns {created, bound, updated, removed, kept, ignored}."""
	fl = _fl()
	if not isinstance(items, (list, tuple)):
		raise ValueError('dmx_groups: serve una lista di gruppi')
	plan, seen, bound_targets = [], set(), {}
	for raw in items:
		d = dict(raw)
		name = str(d.get('group') or '').strip()
		kind = str(d.get('kind') or '').strip()
		bind = str(d.get('bind') or '').strip()
		label = str(d.get('label') or '').replace('\t', ' ').strip()
		if not _NAME.match(name):
			raise ValueError('gruppo %r: nome non valido (minuscole, cifre, _; max 24)' % name)
		if name in seen:
			raise ValueError('gruppo %s ripetuto' % name)
		seen.add(name)
		if kind and kind not in SET_KINDS:
			raise ValueError('gruppo %s: kind %r non valido (%s)' % (name, kind, ', '.join(SET_KINDS)))
		if kind == 'none':
			plan.append(('ignore', name, kind, label, None))
			continue
		if bind:
			if bind not in PROTECTED:
				raise ValueError('gruppo %s: bind %r non valido (motori TD: %s)' % (name, bind, ', '.join(PROTECTED)))
			bkind = fl.group_info(bind).get('kind') or 'chase'
			if kind and kind != bkind:
				raise ValueError('gruppo %s: il motore %s e\' %s, non %s' % (name, bind, bkind, kind))
			if bind in bound_targets:
				raise ValueError('motore %s legato a due gruppi (%s, %s)' % (bind, bound_targets[bind], name))
			other = fl.resolve_group(name)
			if other is not None and other != bind:
				raise ValueError('gruppo %s: il nome e\' gia\' di %s, non si lega a %s' % (name, other, bind))
			bound_targets[bind] = name
			plan.append(('bind', name, bkind, label, bind))
			continue
		g = fl.resolve_group(name)
		if g is not None:
			gkind = fl.group_info(g).get('kind') or 'chase'
			if kind and kind != gkind:
				raise ValueError('gruppo %s esiste gia\' come %s, non %s' % (name, gkind, kind))
			plan.append(('update', name, gkind, label, g))
			continue
		if kind == 'heads':
			raise ValueError('gruppo %s: le teste sono un motore solo, usare bind: heads' % name)
		if kind not in KINDS:
			raise ValueError('gruppo %s: serve kind (chase o level) per crearlo' % name)
		if name in RESERVED or _home().op('rig_' + name) is not None:
			raise ValueError('gruppo %s: nome riservato o operatore rig_%s gia\' esistente' % (name, name))
		plan.append(('create', name, kind, label, None))

	res = {'created': [], 'bound': [], 'updated': [], 'removed': [], 'kept': [], 'ignored': []}
	for action, name, kind, label, target in plan:
		if action == 'ignore':
			res['ignored'].append(name)
		elif action == 'bind':
			# the Plancia name moves to this engine: clear it elsewhere first
			for g in fl.groups():
				if g.get('alias') == name and g['group'] != target:
					_set_cells(g['group'], alias='')
			_set_cells(target, alias=name, label=label)
			res['bound'].append({'group': name, 'td_group': target})
		elif action == 'update':
			_set_cells(target, label=label)
			res['updated'].append(name)
		else:
			add_group(name, kind, count=0, label=label, source=source)
			res['created'].append(name)
	listed = {n for _a, n, _k, _l, _t in plan}
	for g in fl.groups():
		if g['group'] in PROTECTED or g['group'] in listed or (g.get('alias') or '') in listed:
			continue
		if fl.rows(g['group']):
			res['kept'].append({'group': g['group'], 'fixtures': len(fl.rows(g['group']))})
		else:
			remove_group(g['group'])
			res['removed'].append(g['group'])
	return res
