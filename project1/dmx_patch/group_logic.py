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
	'model', 'models', 'type', 'types', 'universe')
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
	out.par.callbacks = 'level_out_callbacks'
	out.nodeX, out.nodeY = 400, 0
	cb.dock = out
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


def add_group(group, kind='chase', profile=None, port_id=None, count=1, start=None, alias=''):
	"""Create a group and its rig COMP, then `count` fixtures at consecutive
	free addresses on port_id. Returns the group name."""
	fl = _fl()
	group = str(group or '').strip()
	kind = str(kind or 'chase').strip()
	alias = str(alias or '').strip()
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
	count = max(1, int(count or 1))

	comp = _build_chase_rig(name) if kind == 'chase' else _build_level_rig(name)
	comp.nodeX, comp.nodeY = _free_slot(), ROW_Y
	try:
		comp.par.Outputport = port_id
		t = _groups_table()
		row = {'group': group, 'comp': name,
			'select': 'dmx_select' if kind == 'chase' else 'level_out',
			'profiles': 'fixture_profiles' if kind == 'chase' else 'level_profiles',
			'alias': alias, 'kind': kind}
		t.appendRow([row.get(t[0, c].val, '') for c in range(t.numCols)])
		if profile is None:
			profile = DEFAULT_LEVEL_PROFILE.get(group, fl.default_profile(group)) \
				if kind == 'level' else fl.default_profile(group)
		if fl.profile_channels(group, profile) is None:
			raise ValueError('profilo %r non esiste per %s (disponibili: %s)' % (
				profile, kind, ', '.join(fl.profile_names(group))))
		nch = len(fl.profile_channels(group, profile))
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
