"""conflict_logic -- address planning of the patch, shared by TD and Plancia
(GAIA_INTERFACE "TD/Win-PD, 20"): who occupies which channels of which
universe, what overlaps, where a fixture fits.

Occupancy = every ENABLED fixture (fixtures table, enabled=1) with a known
footprint, also when its group is switched off: planned is planned.
footprint = channels of its profile (catalog model, see catalog_logic).

Conflict clusters (fixtures whose ranges touch, same port), by kind:
  duplicate  same range AND same group: the same light entered twice, e.g.
             the same Plancia stage sent from two devices (each browser
             keeps its own copy with its own ids)
  shared     same range, different groups: one lamp driven by two groups
             (allowed on purpose, e.g. the rig_a / rig_b test bars)
  overlap    anything else: partial overlap or different footprints. Always
             an error: the later rows of universe_build win channel by
             channel.

Suggestion = first free address that fits the footprint, from the
requested address on; then from 1 on the same port; then the other ports
in ports-table order. Universe = Plancia's 1-based universe: U1 = Art-Net
universe 0 (net 0, subnet 0), see fixture_logic.port_for_universe.

Called by gaia_services/dmx_services (dmx_universe_map,
dmx_patch_conflicts, dmx_patch_check, dmx_patch_resolve, address/universe
"auto" and on_conflict on dmx_fixture_add/update), the dmx_patch Check page
and the Config inspector (config/tab_fixtures/fixture_ui).
"""

ON_CONFLICT = ('accept', 'reject', 'auto')


def _patch():
	return me.parent()


def _fl():
	return _patch().op('fixture_logic').module


def _cat():
	return _patch().op('catalog_logic').module


def _int(v, d=0):
	try:
		return int(float(str(v)))
	except (TypeError, ValueError):
		return d


# ---------------------------------------------------------------- basics

def ports():
	"""[{port_id, label, universe (1-based, None outside net 0 / subnet 0),
	artnet "net:sub:uni", online}] in ports-table order."""
	t = _patch().op('ports')
	out = []
	for r in range(1, t.numRows if t is not None else 0):
		net, sub, uni = _int(t[r, 'net'].val), _int(t[r, 'subnet'].val), _int(t[r, 'universe'].val)
		out.append({
			'port_id': t[r, 'port_id'].val, 'label': t[r, 'label'].val,
			'universe': uni + 1 if net == 0 and sub == 0 else None,
			'artnet': '%d:%d:%d' % (net, sub, uni), 'online': t[r, 'online'].val == '1'})
	return out


def _port(port_id):
	for p in ports():
		if p['port_id'] == port_id:
			return p
	return None


def universe_of(port_id):
	p = _port(port_id)
	return p['universe'] if p else None


def footprint(group, profile):
	"""Channels of a profile: the group's library, else the catalog model
	(for a group not created yet); 0 when unknown."""
	fl = _fl()
	chans = fl.profile_channels(group, profile) if fl.group_info(group) else None
	if chans is None:
		m = _cat().model(profile)
		return m['footprint'] if m else 0
	return len(chans)


def _entry(f):
	n = footprint(f['group'], f['profile'])
	return {'id': f['id'], 'uid': f['uid'], 'name': f['name'], 'group': f['group'],
		'profile': f['profile'], 'port_id': f['port_id'], 'start': f['address'],
		'end': f['address'] + max(n, 1) - 1, 'footprint': n}


def occupancy(exclude=()):
	"""Entries of the enabled fixtures with a footprint (id in exclude
	skipped)."""
	return [e for e in (_entry(f) for f in _fl().rows() if f['enabled'] and f['id'] not in exclude)
		if e['footprint'] > 0]


def _public(e):
	return {k: e[k] for k in ('id', 'uid', 'name', 'group', 'profile', 'start', 'end')}


def _overlaps(a_start, a_end, b):
	return not (a_end < b['start'] or b['end'] < a_start)


def free_ranges(used):
	"""Free [start, end] gaps of 1..512 around the used entries."""
	out, a = [], 1
	for e in sorted(used, key=lambda e: e['start']):
		if e['start'] > a:
			out.append([a, e['start'] - 1])
		a = max(a, e['end'] + 1)
	if a <= 512:
		out.append([a, 512])
	return out


def _first_fit(used, n, frm=1):
	a = max(1, int(frm))
	for e in sorted(used, key=lambda e: e['start']):
		if e['end'] < a:
			continue
		if a + n - 1 < e['start']:
			break
		a = e['end'] + 1
	return a if a + n - 1 <= 512 else None


def suggest(n, port_id=None, address=None, exclude=(), extra=()):
	"""Where n channels fit: {port_id, universe, address, end, same_port}
	or None. exclude = fixture ids to ignore (the one being moved), extra =
	more entries to treat as used (a batch being planned)."""
	if n <= 0:
		return None
	return _suggest_in(occupancy(exclude) + list(extra), n, port_id, address)


def _suggest_in(used, n, port_id=None, address=None):
	"""suggest() on an explicit list of used entries."""
	order = [p['port_id'] for p in ports()]
	if port_id in order:
		order.remove(port_id)
		order.insert(0, port_id)
	for pid in order:
		u = [e for e in used if e['port_id'] == pid]
		a = None
		if pid == port_id and address:
			a = _first_fit(u, n, address)
		if a is None:
			a = _first_fit(u, n, 1)
		if a is not None:
			return {'port_id': pid, 'universe': universe_of(pid), 'address': a,
				'end': a + n - 1, 'same_port': pid == port_id}
	return None


# ---------------------------------------------------------------- analysis

def _clusters(entries):
	"""Overlap clusters (lists of >= 2 entries) per port."""
	out = []
	by_port = {}
	for e in entries:
		by_port.setdefault(e['port_id'], []).append(e)
	for pid, es in by_port.items():
		cur, end = [], 0
		for e in sorted(es, key=lambda e: (e['start'], e['id'])):
			if cur and e['start'] <= end:
				cur.append(e)
				end = max(end, e['end'])
			else:
				if len(cur) > 1:
					out.append(cur)
				cur, end = [e], e['end']
		if len(cur) > 1:
			out.append(cur)
	return out


def _kind(cluster):
	ranges = {(e['start'], e['end']) for e in cluster}
	if len(ranges) > 1:
		return 'overlap'
	groups = [e['group'] for e in cluster]
	return 'duplicate' if len(set(groups)) < len(groups) else 'shared'


def conflicts():
	"""[{port_id, universe, kind, start, end, fixtures: [...]}]."""
	out = []
	for c in _clusters(occupancy()):
		out.append({'port_id': c[0]['port_id'], 'universe': universe_of(c[0]['port_id']),
			'kind': _kind(c), 'start': min(e['start'] for e in c), 'end': max(e['end'] for e in c),
			'fixtures': [_public(e) for e in c]})
	return out


def universe_map():
	"""{universes: [{port_id, label, universe, artnet, online, used, free,
	free_channels, conflicts}], unassigned: [fixtures on no known port]}."""
	occ = occupancy()
	in_conflict = {e['id'] for c in _clusters(occ) for e in c}
	known = set()
	uni = []
	for p in ports():
		known.add(p['port_id'])
		used = sorted((e for e in occ if e['port_id'] == p['port_id']), key=lambda e: (e['start'], e['id']))
		free = free_ranges(used)
		uni.append(dict(p, used=[dict(_public(e), conflict=e['id'] in in_conflict) for e in used],
			free=free, free_channels=sum(b - a + 1 for a, b in free),
			conflicts=sum(1 for e in used if e['id'] in in_conflict)))
	return {'universes': uni, 'unassigned': [_public(e) for e in occ if e['port_id'] not in known]}


def summary():
	"""One line for the TD pars: counts per conflict kind."""
	cs = conflicts()
	if not cs:
		return 'nessun conflitto (%d fixture in patch)' % len(occupancy())
	n = {}
	for c in cs:
		n[c['kind']] = n.get(c['kind'], 0) + 1
	return ', '.join('%s %d' % (k, v) for k, v in sorted(n.items())) + \
		' (%d fixture coinvolte)' % sum(len(c['fixtures']) for c in cs)


# ---------------------------------------------------------------- proposals

def split_auto(raw):
	"""(fixture dict without the planning keys, auto_universe, auto_address,
	on_conflict) -- 'auto' must go before fixture_logic.from_plancia, which
	would read it as a universe number."""
	d = dict(raw)
	auto_u = str(d.get('universe', '')).strip().lower() == 'auto' or \
		str(d.get('port_id', '')).strip().lower() == 'auto'
	auto_a = str(d.get('address', '')).strip().lower() == 'auto'
	if auto_u:
		d.pop('universe', None)
		d.pop('port_id', None)
	if auto_a:
		d.pop('address', None)
	oc = str(d.pop('on_conflict', 'accept') or 'accept').strip().lower()
	if oc not in ON_CONFLICT:
		raise ValueError('on_conflict %r non valido (%s)' % (oc, ', '.join(ON_CONFLICT)))
	return d, auto_u, auto_a, oc


def _existing(raw):
	"""The fixture row a proposal refers to (by numeric id or uid), or None."""
	fl = _fl()
	for key in ('uid', 'id'):
		v = raw.get(key)
		if v in (None, ''):
			continue
		try:
			fid = fl.fixture_id(v)
		except ValueError:
			continue
		for f in fl.rows():
			if f['id'] == fid:
				return f
	return None


def _proposal_footprint(d, raw):
	fl = _fl()
	group = d.get('group')
	profile = d.get('profile') or (fl.default_profile(group) if group and fl.group_info(group) else '')
	n = footprint(group, profile) if profile else 0
	if not n:
		n = _int(raw.get('footprint') or raw.get('ch'), 0)
	return n, profile


def place(d, raw, auto_u, auto_a, on_conflict, cur=None):
	"""Fill port_id/address of a normalised fixture dict (from_plancia
	output) for an add (cur None) or an update (cur = the current row):
	'auto' -> the suggestion; on_conflict reject -> ValueError naming the
	conflict and the suggestion; auto -> moved to the suggestion; accept ->
	as is (patch_report flags it). Returns d."""
	n, _profile = _proposal_footprint(dict(cur or {}, **d), raw)
	if not n:
		return d   # unknown profile: fixture_logic's own check reports it
	excl = (cur['id'],) if cur else ()
	port = d.get('port_id') or (cur['port_id'] if cur else '')
	if not port and not auto_u and d.get('group') and _fl().group_comp(d['group']) is not None:
		comp = _fl().group_comp(d['group'])
		port = str(comp.par.Outputport.eval()) if hasattr(comp.par, 'Outputport') else ''
	addr = d.get('address') if 'address' in d else (cur['address'] if cur else None)
	if auto_u or auto_a or (not cur and addr in (None, '')):
		s = suggest(n, None if auto_u else port, None if auto_a else addr, excl)
		if s is None:
			raise ValueError('nessuno spazio libero per %d canali%s' % (n, '' if auto_u else ' su %s' % port))
		d['port_id'], d['address'] = s['port_id'], s['address']
		return d
	addr = _int(addr, 0)
	if on_conflict == 'accept' or not port or not addr:
		return d
	hits = [e for e in occupancy(excl) if e['port_id'] == port and _overlaps(addr, addr + n - 1, e)]
	if not hits:
		return d
	s = suggest(n, port, addr, excl)
	if on_conflict == 'reject' or s is None:
		raise ValueError('U%s@%d-%d in conflitto con %s; libero: %s' % (
			universe_of(port), addr, addr + n - 1,
			', '.join('%s (%s %d-%d)' % (e['uid'] or e['id'], e['name'], e['start'], e['end']) for e in hits),
			'U%s@%d' % (s['universe'], s['address']) if s else 'nessuno spazio'))
	d['port_id'], d['address'] = s['port_id'], s['address']
	return d


def place_all(items):
	"""place() for a whole new patch (dmx_fixtures replaces everything):
	items = [(d, raw, auto_u, auto_a)]. Occupancy is the new list itself,
	not the current table: explicit addresses first, then each 'auto' item
	at the first free place. Conflicts between explicit items are accepted
	(patch_report flags them). Returns the dicts."""
	used = []
	for d, raw, auto_u, auto_a in items:
		if not (auto_u or auto_a) and d.get('port_id') and d.get('address') not in (None, ''):
			n, _p = _proposal_footprint(d, raw)
			a = _int(d['address'], 0)
			used.append({'id': 0, 'port_id': d['port_id'], 'start': a, 'end': a + max(n, 1) - 1})
	for d, raw, auto_u, auto_a in items:
		if not (auto_u or auto_a):
			continue
		n, _p = _proposal_footprint(d, raw)
		if not n:
			continue
		s = _suggest_in(used, n, None if auto_u else d.get('port_id'), None if auto_a else d.get('address'))
		if s is None:
			raise ValueError('nessuno spazio libero per %d canali (%s)' % (n, raw.get('name') or raw.get('id')))
		d['port_id'], d['address'] = s['port_id'], s['address']
		used.append({'id': 0, 'port_id': s['port_id'], 'start': s['address'], 'end': s['end']})
	return [it[0] for it in items]


def check(items):
	"""Evaluate proposed fixtures WITHOUT writing: Plancia shape or ours,
	address/universe may be 'auto'. Items are planned in order: an item
	sees the ones before it (at their own range if ok, at their suggestion
	if not). Returns one result per item."""
	fl = _fl()
	extra, out = [], []
	for i, raw in enumerate(items or []):
		raw = dict(raw)
		res = {'index': i, 'ref': raw.get('uid') or raw.get('id') or i, 'status': 'ok',
			'conflicts': [], 'suggestion': None, 'message': ''}
		try:
			d, auto_u, auto_a, _oc = split_auto(raw)
			d = fl.from_plancia(d, missing_ok=True)
			if d is None:
				res['status'] = 'no_dmx'
				out.append(res)
				continue
			cur = _existing(raw)
			full = dict(cur or {}, **d)
			n, profile = _proposal_footprint(full, raw)
			port = full.get('port_id', '')
			addr = full.get('address')
			res.update({'group': full.get('group', ''), 'profile': profile, 'footprint': n,
				'update_of': cur['id'] if cur else None})
			excl = (cur['id'],) if cur else ()
			if not n:
				res['status'] = 'no_profile'
				res['message'] = 'profilo/modello sconosciuto: serve model o footprint'
				out.append(res)
				continue
			if auto_u or auto_a or addr in (None, ''):
				s = suggest(n, None if auto_u else port, None if auto_a else addr, excl, extra)
				res['suggestion'] = s
				res['status'] = 'auto' if s else 'full'
				if s:
					extra.append({'id': -1 - i, 'uid': '', 'name': '', 'group': res['group'], 'profile': profile,
						'port_id': s['port_id'], 'start': s['address'], 'end': s['end'], 'footprint': n})
				out.append(res)
				continue
			addr = _int(addr, 0)
			res.update({'port_id': port, 'universe': universe_of(port), 'start': addr, 'end': addr + n - 1})
			if _port(port) is None:
				res['status'] = 'no_port'
			elif addr < 1 or addr + n - 1 > 512:
				res['status'] = 'overflow'
			hits = [e for e in occupancy(excl) + extra if e['port_id'] == port and _overlaps(addr, addr + n - 1, e)]
			if hits and res['status'] == 'ok':
				res['status'] = 'conflict'
				res['conflicts'] = [dict(_public(e), batch=e['id'] < 0) for e in hits]
			if res['status'] != 'ok':
				res['suggestion'] = suggest(n, port if _port(port) else None, addr if addr >= 1 else None, excl, extra)
			placed = res['suggestion'] if res['status'] != 'ok' else {'port_id': port, 'address': addr, 'end': addr + n - 1}
			if placed:
				extra.append({'id': -1 - i, 'uid': '', 'name': '', 'group': res['group'], 'profile': profile,
					'port_id': placed['port_id'], 'start': placed['address'], 'end': placed['end'], 'footprint': n})
		except Exception as e:
			res['status'] = 'error'
			res['message'] = str(e)
		out.append(res)
	return out


# ---------------------------------------------------------------- resolve

def _priority(e):
	"""Who stays: fixtures created in TD (no uid) first, then the oldest."""
	return (1 if e['uid'] else 0, e['id'])


def resolve(apply=False, include_shared=False, remove_duplicates=True):
	"""Plan (and with apply=True, carry out) the end of every conflict:
	duplicates removed (one kept per light), overlapping fixtures moved to
	their suggestion, shared ranges left alone unless include_shared.
	Returns {applied, actions: [{action: remove|move, id, uid, name, group,
	from: {port_id, universe, address}, to?: {...}, duplicate_of?}],
	unresolved: [...]}."""
	fl = _fl()
	sim = occupancy()
	actions, unresolved = [], []

	def frm(e):
		return {'port_id': e['port_id'], 'universe': universe_of(e['port_id']), 'address': e['start']}

	if remove_duplicates:
		seen = {}
		for e in sorted(sim, key=_priority):
			key = (e['port_id'], e['start'], e['end'], e['group'])
			if key in seen:
				actions.append({'action': 'remove', 'id': e['id'], 'uid': e['uid'], 'name': e['name'],
					'group': e['group'], 'from': frm(e), 'duplicate_of': seen[key]['id']})
			else:
				seen[key] = e
		gone = {a['id'] for a in actions}
		sim = [e for e in sim if e['id'] not in gone]

	def clashes(e, members):
		"""Members e really conflicts with (a shared pair -- same range,
		different group -- does not count unless include_shared)."""
		out = []
		for o in members:
			if o is e or o['port_id'] != e['port_id'] or not _overlaps(e['start'], e['end'], o):
				continue
			if not include_shared and (o['start'], o['end']) == (e['start'], e['end']) and o['group'] != e['group']:
				continue
			out.append(o)
		return out

	for c in _clusters(sim):
		# greedy: move the fixture that clashes with the most others first
		# (ties: Plancia before TD, newest first) -- one big intruder moves
		# instead of every small light it covers
		members = list(c)
		for _ in range(len(c)):
			worst = max(members, key=lambda e: (len(clashes(e, members)), _priority(e)))
			if not clashes(worst, members):
				break
			others = [o for o in sim if o is not worst]
			s = _suggest_in(others, worst['footprint'], worst['port_id'], worst['start'])
			members.remove(worst)
			if s is None:
				unresolved.append(dict(_public(worst), reason='nessuno spazio libero'))
				continue
			actions.append({'action': 'move', 'id': worst['id'], 'uid': worst['uid'], 'name': worst['name'],
				'group': worst['group'], 'from': frm(worst),
				'to': {'port_id': s['port_id'], 'universe': s['universe'], 'address': s['address']}})
			worst.update(port_id=s['port_id'], start=s['address'], end=s['end'])

	if apply:
		for a in actions:
			if a['action'] == 'remove':
				fl.remove_fixture(a['id'])
		for a in actions:
			if a['action'] == 'move':
				fl.update_fixture(a['id'], port_id=a['to']['port_id'], address=a['to']['address'])
	return {'applied': bool(apply), 'actions': actions, 'unresolved': unresolved}
