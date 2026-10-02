"""fixture_logic -- the fixture patch. `fixtures` (sibling table) is the
source of truth: one row per physical light.

  id       unique int, never reused
  name     free label ("Bar 1", "Spot SX")
  group    patch group (groups table: rig_a, rig_b, heads)
  unit     which output unit of the group's generator drives it (bar<unit>_*,
           head<unit>_*). Two fixtures on the same unit = mirrored copies.
  profile  profile name in the group's library (groups 'profiles' column:
           fixture_profiles for the rigs, head_profiles for the heads)
  port_id  Art-Net output port (ports table, "<node ip>:<port>")
  address  DMX start address 1..512
  x, y     position on the stage plan (grid cells, y up)
  enabled  0 = kept in the patch but not sent

Mixed profiles: each unit is generated with the profile of its fixture, so a
group can mix 4CH and 8CH bars (or different heads).

The group COMP's own pars (Nbars/Count, Startaddress, Fixtureprofile/Profile,
Outputport) are the QUICK PATCH: changing them rewrites the group as a
uniform consecutive block (quick_patch). Editing the table goes the other
way: sync_quick_pars() reflects the table back on those pars (count = units,
first address/port/profile). Parameter Execute callbacks fire at the END of
the frame, so a simple 'syncing' flag would already be off by then: every
value written is remembered in _echo and the callback asks is_echo(par) to
skip exactly that change.

Called from: dmx_patch (patch_report, lifecycle), the rig/heads generators and
par callbacks, the config UI and gaia_services (dmx_fixtures param).
"""

COLUMNS = ['id', 'name', 'group', 'unit', 'profile', 'port_id', 'address', 'x', 'y', 'enabled']

# per group kind: names of the quick-patch pars on the group COMP
_COUNT_PARS = ('Nbars', 'Count')
_PROFILE_PARS = ('Fixtureprofile', 'Profile')

_syncing = False  # True while sync_quick_pars() writes the group pars
_echo = {}  # (comp path, par name) -> value written by sync_quick_pars


# ---------------------------------------------------------------- lookups

def _patch():
	return me.parent()


def _home():
	return me.parent().parent()


def table():
	t = _patch().op('fixtures')
	if t.numRows == 0 or t[0, 0] is None or t[0, 0].val != 'id':
		t.clear()
		t.appendRow(COLUMNS)
	return t


def groups():
	"""[{group, comp, select, profiles}] from the groups table."""
	g = _patch().op('groups')
	head = [c.val for c in g.row(0)]
	return [{h: g[r, h].val for h in head} for r in range(1, g.numRows)]


def group_info(group):
	for g in groups():
		if g['group'] == group:
			return g
	return None


def group_comp(group):
	g = group_info(group)
	return _home().op(g['comp']) if g else None


def group_of(comp):
	"""Group name of a group COMP (or of a clone: matched by name)."""
	for g in groups():
		if g['comp'] == comp.name:
			return g['group']
	return None


def _first_par(comp, names):
	for n in names:
		if hasattr(comp.par, n):
			return comp.par[n]
	return None


def profile_table(group):
	g = group_info(group)
	comp = group_comp(group)
	if g is None or comp is None:
		return None
	return comp.op(g.get('profiles') or 'fixture_profiles')


def profile_names(group):
	t = profile_table(group)
	if t is None:
		return []
	return [t[r, 0].val for r in range(1, t.numRows) if t[r, 0].val.strip()]


def profile_channels(group, profile):
	"""Channel list of a profile, None if the profile is unknown."""
	t = profile_table(group)
	if t is None or t[str(profile), 'channels'] is None:
		return None
	chans = str(t[str(profile), 'channels'].val).split()
	return chans or None


def default_profile(group):
	comp = group_comp(group)
	p = _first_par(comp, _PROFILE_PARS) if comp is not None else None
	if p is not None and str(p.eval()):
		return str(p.eval())
	names = profile_names(group)
	return names[0] if names else ''


# ---------------------------------------------------------------- reading

def _int(v, d=0):
	try:
		return int(float(str(v)))
	except (TypeError, ValueError):
		return d


def _float(v, d=0.0):
	try:
		return float(str(v))
	except (TypeError, ValueError):
		return d


def rows(group=None):
	"""Fixtures as dicts (typed), table order."""
	t = table()
	out = []
	for r in range(1, t.numRows):
		d = {c: t[r, c].val if t[r, c] is not None else '' for c in COLUMNS}
		if group is not None and d['group'] != group:
			continue
		d['id'] = _int(d['id'])
		d['unit'] = max(1, _int(d['unit'], 1))
		d['address'] = _int(d['address'], 1)
		d['x'] = _float(d['x'])
		d['y'] = _float(d['y'])
		d['enabled'] = 1 if _int(d['enabled'], 1) else 0
		out.append(d)
	return out


_frame_cache = {}  # (what, comp path) -> (frame, value): generators ask every frame


def _cached(what, comp, fn):
	f = absTime.frame
	key = (what, comp.path)
	hit = _frame_cache.get(key)
	if hit is not None and hit[0] == f:
		return hit[1]
	val = fn(comp)
	_frame_cache[key] = (f, val)
	return val


def unit_profiles(comp, cached=True):
	"""Profile name per output unit (index 0 = unit 1) for a group COMP.
	Unit count = highest unit used by the group (min 1); a unit with no
	fixture, or whose profile is unknown, uses the group's default profile.
	cached: once per frame (for ops that cook every frame anyway). An op
	that cooks only on change must pass cached=False, so it reads the tables
	itself and TD recooks it when the patch changes."""
	if not cached:
		return _unit_profiles(comp)
	return list(_cached('profiles', comp, _unit_profiles))


def _unit_profiles(comp):
	group = group_of(comp)
	if group is None:
		return []
	dflt = default_profile(group)
	fx = rows(group)
	known = {}
	by_unit = {}
	for f in fx:
		p = f['profile']
		if p not in known:
			known[p] = profile_channels(group, p) is not None
		if f['unit'] not in by_unit and known[p]:
			by_unit[f['unit']] = p
	n = max([1] + [f['unit'] for f in fx])
	return [by_unit.get(u, dflt) for u in range(1, n + 1)]


def unit_channels(comp):
	"""Channel list per output unit for a group COMP -- what the generator
	emits for bar<u>_* / head<u>_*. Cached per frame."""
	return [list(c) for c in _cached('channels', comp, _unit_channels)]


def _unit_channels(comp):
	group = group_of(comp)
	if group is None:
		return []
	chans = {}
	for p in unit_profiles(comp):
		if p not in chans:
			chans[p] = profile_channels(group, p) or ['red', 'green', 'blue']
	return [chans[p] for p in unit_profiles(comp)]


def addresses_text(comp):
	"""One-line summary of a group's addresses (for read-only pars/UI)."""
	group = group_of(comp)
	fx = sorted(rows(group), key=lambda f: (f['unit'], f['id'])) if group else []
	if not fx:
		return 'nessuna fixture'
	return ', '.join('%s: %d' % (f['name'] or f['unit'], f['address']) for f in fx)


# ---------------------------------------------------------------- writing

def _next_id():
	return max([0] + [f['id'] for f in rows()]) + 1


def _row_index(fid):
	t = table()
	for r in range(1, t.numRows):
		if _int(t[r, 'id'].val) == int(fid):
			return r
	return None


def _write(t, r, d):
	for c in COLUMNS:
		if c in d:
			v = d[c]
			if isinstance(v, float) and v.is_integer():
				v = int(v)
			t[r, c] = v


def _label(group, unit):
	return '%s %d' % ('Head' if group == 'heads' else 'Bar', unit)


def _default_y(group):
	names = [g['group'] for g in groups()]
	return float(-2 * names.index(group)) if group in names else 0.0


def quick_patch(comp):
	"""Rewrite a group as a uniform consecutive block from its quick-patch
	pars (count, start, profile, port). Keeps id/name/x/y/enabled of the
	units that already exist; extra fixtures of the group are removed."""
	if _syncing:
		return
	group = group_of(comp)
	if group is None:
		return
	cnt = _first_par(comp, _COUNT_PARS)
	n = max(1, int(cnt.eval())) if cnt is not None else 1
	start = int(comp.par.Startaddress.eval())
	port = str(comp.par.Outputport.eval())
	profile = default_profile(group)
	nch = len(profile_channels(group, profile) or [])
	t = table()
	existing = {}
	for f in rows(group):
		existing.setdefault(f['unit'], f)
	# drop the group's rows, then rewrite them unit by unit
	for r in range(t.numRows - 1, 0, -1):
		if t[r, 'group'].val == group:
			t.deleteRow(r)
	nid = _next_id()
	for i in range(n):
		u = i + 1
		old = existing.get(u)
		d = {
			'id': old['id'] if old else nid,
			'name': old['name'] if old and old['name'] else _label(group, u),
			'group': group, 'unit': u, 'profile': profile, 'port_id': port,
			'address': start + i * nch,
			'x': old['x'] if old else float(i),
			'y': old['y'] if old else _default_y(group),
			'enabled': old['enabled'] if old else 1,
		}
		if not old:
			nid += 1
		t.appendRow([''] * len(COLUMNS))
		_write(t, t.numRows - 1, d)


def sync_quick_pars(group):
	"""Reflect the table on the group's quick-patch pars (count = units,
	first fixture's address/port/profile) without triggering quick_patch."""
	global _syncing
	comp = group_comp(group)
	fx = sorted(rows(group), key=lambda f: (f['unit'], f['id']))
	if comp is None or not fx:
		return
	first = fx[0]

	def put(par, value):
		_echo[(comp.path, par.name)] = (str(value), absTime.seconds)
		par.val = value

	_syncing = True
	try:
		cnt = _first_par(comp, _COUNT_PARS)
		n = max(f['unit'] for f in fx)
		if cnt is not None and int(cnt.eval()) != n:
			put(cnt, n)
		if int(comp.par.Startaddress.eval()) != first['address']:
			put(comp.par.Startaddress, first['address'])
		if first['port_id'] and str(comp.par.Outputport.eval()) != first['port_id'] \
				and first['port_id'] in comp.par.Outputport.menuNames:
			put(comp.par.Outputport, first['port_id'])
		prof = _first_par(comp, _PROFILE_PARS)
		if prof is not None and str(prof.eval()) != first['profile'] \
				and first['profile'] in prof.menuNames:
			put(prof, first['profile'])
	finally:
		_syncing = False


def is_syncing():
	return _syncing


def is_echo(par):
	"""True when par's current value was written by sync_quick_pars (the
	end-of-frame callback of our own write): consumes the record. A user or
	Gaia change to any other value is not an echo; records older than a
	second are stale (the callback they waited for never came). Seconds, not
	frames: with realtime on and fps below the cook rate absTime.frame skips."""
	if _syncing:
		return True
	rec = _echo.pop((par.owner.path, par.name), None)
	return rec is not None and rec[0] == str(par.eval()) and absTime.seconds - rec[1] <= 1.0


def _check(d):
	"""Validate/normalise one fixture dict for writing; raises ValueError."""
	group = d.get('group')
	if group_info(group) is None:
		raise ValueError('gruppo sconosciuto: %r' % group)
	if 'profile' in d and profile_channels(group, d['profile']) is None:
		raise ValueError('profilo %r non esiste per %s (disponibili: %s)' % (
			d['profile'], group, ', '.join(profile_names(group))))
	if 'address' in d:
		d['address'] = _int(d['address'], 0)
		if not 1 <= d['address'] <= 512:
			raise ValueError('indirizzo fuori range 1..512: %r' % d['address'])
		nch = len(profile_channels(group, d.get('profile')) or [])
		if nch and d['address'] + nch - 1 > 512:
			raise ValueError('%d canali da %d finiscono a %d: oltre 512 (max %d)' % (
				nch, d['address'], d['address'] + nch - 1, 513 - nch))
	if 'unit' in d:
		d['unit'] = max(1, _int(d['unit'], 1))
	for k in ('x', 'y'):
		if k in d:
			d[k] = round(_float(d[k]), 3)
	if 'enabled' in d:
		d['enabled'] = 1 if _int(d['enabled'], 1) else 0
	return d


def next_free_address(port_id, nch, exclude_id=None):
	"""Lowest address on port_id where nch channels fit without overlap."""
	used = []
	for f in rows():
		if f['port_id'] != port_id or f['id'] == exclude_id:
			continue
		n = len(profile_channels(f['group'], f['profile']) or [])
		used.append((f['address'], f['address'] + n - 1))
	a = 1
	for lo, hi in sorted(used):
		if a + nch - 1 < lo:
			break
		a = max(a, hi + 1)
	return a if a + nch - 1 <= 512 else None


def add_fixture(group, profile=None, port_id=None, address=None, unit=None, name=None, x=None, y=None):
	"""Append a fixture; missing fields get sensible defaults (next unit,
	group port, first free address). Returns the new id."""
	fx = rows(group)
	comp = group_comp(group)
	profile = profile or (fx[-1]['profile'] if fx else default_profile(group))
	port_id = port_id or (fx[-1]['port_id'] if fx else (str(comp.par.Outputport.eval()) if comp else ''))
	unit = unit or (max([0] + [f['unit'] for f in fx]) + 1)
	nch = len(profile_channels(group, profile) or [])
	if address is None:
		address = next_free_address(port_id, nch)
		if address is None:
			raise ValueError('nessuno spazio libero su %s per %d canali' % (port_id, nch))
	d = _check({
		'id': _next_id(), 'name': name or _label(group, unit), 'group': group,
		'unit': unit, 'profile': profile, 'port_id': port_id, 'address': address,
		'x': x if x is not None else (max([f['x'] for f in fx]) + 1 if fx else 0.0),
		'y': y if y is not None else (fx[-1]['y'] if fx else _default_y(group)),
		'enabled': 1,
	})
	t = table()
	t.appendRow([''] * len(COLUMNS))
	_write(t, t.numRows - 1, d)
	sync_quick_pars(group)
	return d['id']


def update_fixture(fid, **fields):
	r = _row_index(fid)
	if r is None:
		raise ValueError('fixture %s non trovata' % fid)
	t = table()
	cur = {c: t[r, c].val for c in COLUMNS}
	fields.pop('id', None)
	d = _check(dict(cur, **fields))
	_write(t, r, {k: d[k] for k in fields if k in COLUMNS})
	for g in {cur['group'], d['group']}:
		sync_quick_pars(g)


def remove_fixture(fid):
	r = _row_index(fid)
	if r is None:
		return
	t = table()
	group = t[r, 'group'].val
	t.deleteRow(r)
	sync_quick_pars(group)


def auto_address(group, start=1, port_id=None):
	"""Re-address a group consecutively in unit order from `start`
	(optionally moving it to port_id). Mixed profiles pack tightly."""
	fx = sorted(rows(group), key=lambda f: (f['unit'], f['id']))
	t = table()
	a = int(start)
	for f in fx:
		nch = len(profile_channels(group, f['profile']) or [])
		d = {'address': a}
		if port_id:
			d['port_id'] = port_id
		_write(t, _row_index(f['id']), d)
		a += nch
	sync_quick_pars(group)


def to_list():
	"""JSON-friendly list (Gaia / UI)."""
	return rows()


def set_all(items):
	"""Replace the whole patch with `items` (list of dicts, same keys as
	to_list(); id optional). Validates everything before writing anything."""
	clean = []
	nid = _next_id()
	seen = set()
	for it in items:
		d = dict(it)
		if not d.get('id') or _int(d['id']) in seen:
			d['id'] = nid
			nid += 1
		d['id'] = _int(d['id'])
		seen.add(d['id'])
		d.setdefault('profile', default_profile(d.get('group')))
		d.setdefault('unit', 1)
		d.setdefault('address', 1)
		d.setdefault('enabled', 1)
		d.setdefault('x', 0)
		d.setdefault('y', 0)
		d.setdefault('name', _label(d.get('group'), _int(d['unit'], 1)))
		d.setdefault('port_id', '')
		clean.append(_check(d))
	t = table()
	t.clear()
	t.appendRow(COLUMNS)
	for d in clean:
		t.appendRow([''] * len(COLUMNS))
		_write(t, t.numRows - 1, d)
	for g in {d['group'] for d in clean}:
		sync_quick_pars(g)


def ensure_migrated():
	"""First run: an empty fixtures table is filled from every group's
	quick-patch pars, so the output is exactly the pre-fixture patch."""
	if len(rows()) > 0:
		return False
	for g in groups():
		comp = _home().op(g['comp'])
		if comp is not None:
			quick_patch(comp)
	return True
