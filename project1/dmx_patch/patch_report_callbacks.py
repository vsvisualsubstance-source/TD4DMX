"""patch_report -- one row per FIXTURE (fixtures table, see fixture_logic):
which port / universe it goes to, its DMX address range and its status.
Read by universe_build (what to send where), routing (one Art-Net stream per
universe), the config UI and Gaia. A group (groups table) = any COMP with
Patchenable / Outputport / Startaddress pars and a CHOP whose channels are
named <prefix><unit>_<attr> (bar3_red, head2_pan) in DMX order per unit.

status: ok | off (fixture or group disabled) | missing (group COMP/CHOP not
found) | no_profile (profile unknown) | no_port (port not in ports table) |
offline (port known but node did not reply to the last scan; still sent) |
overflow (outside 1..512) | conflict (overlaps another enabled fixture on the
same port; still sent, later rows win).
"""

COLS = ['id', 'name', 'group', 'comp', 'select', 'unit', 'profile', 'enabled',
	'port_id', 'ip', 'net', 'subnet', 'universe', 'start', 'end', 'nchans',
	'status', 'summary']

SENDABLE = ('ok', 'offline', 'conflict')


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.appendRow(COLS)
	fl = op('fixture_logic').module
	ports = op('ports')
	home = parent().parent()
	port_rows = {}
	if ports is not None:
		for r in range(1, ports.numRows):
			port_rows[ports[r, 'port_id'].val] = r
	ginfo = {g['group']: g for g in fl.groups()}
	rows = []
	for f in fl.rows():
		g = ginfo.get(f['group'])
		comp = home.op(g['comp']) if g else None
		sel = comp.op(g['select']) if comp is not None else None
		chans = fl.profile_channels(f['group'], f['profile']) if g else None
		n = len(chans) if chans else 0
		start, end = f['address'], f['address'] + max(n, 1) - 1
		pid = f['port_id']
		pr = port_rows.get(pid)
		ip = net = sub = uni = ''
		group_on = bool(comp.par.Patchenable.eval()) if comp is not None else False
		enabled = 1 if (f['enabled'] and group_on) else 0
		if comp is None or sel is None:
			status = 'missing'
		elif not enabled:
			status = 'off'
		elif not chans:
			status = 'no_profile'
		elif pr is None:
			status = 'no_port'
		else:
			ip, net = ports[pr, 'ip'].val, ports[pr, 'net'].val
			sub, uni = ports[pr, 'subnet'].val, ports[pr, 'universe'].val
			status = 'ok' if ports[pr, 'online'].val == '1' else 'offline'
			if start < 1 or end > 512:
				status = 'overflow'
		rows.append([f['id'], f['name'], f['group'], g['comp'] if g else '',
			g['select'] if g else '', f['unit'], f['profile'], enabled, pid,
			ip, net, sub, uni, start, end, n, status])
	# overlaps between enabled fixtures on the same port
	live = [x for x in rows if x[16] in ('ok', 'offline', 'conflict')]
	for i, a in enumerate(live):
		for b in live[i + 1:]:
			if a[8] == b[8] and not (a[14] < b[13] or b[14] < a[13]):
				a[16] = b[16] = 'conflict'
	sent = sorted({x[2] for x in rows if x[16] in SENDABLE})
	nsent = sum(1 for x in rows if x[16] in SENDABLE)
	bad = ['%s=%s' % (x[1] or x[0], x[16]) for x in rows if x[16] not in ('ok', 'off')]
	summary = 'invio: %s (%d fixture)%s' % (', '.join(sent) or 'nessuno', nsent,
		('  |  ' + ', '.join(bad)) if bad else '')
	for x in rows:
		scriptOp.appendRow(x + [summary])
	return
