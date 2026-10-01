"""patch_report -- one row per patch group (groups table): which port /
universe it goes to, its DMX address range and its status. Read by
universe_build (what to send where), routing (one Art-Net stream per universe)
and the panel. A group = any COMP with Patchenable / Outputport /
Startaddress pars and a CHOP whose channels are in DMX address order.

status: ok | off (Patchenable 0) | no_port (port not in ports table) |
offline (port known but node did not reply to the last scan; still sent) |
overflow (past channel 512) | conflict (overlaps another enabled group).
"""

COLS = ['group', 'comp', 'select', 'enabled', 'port_id', 'ip', 'net', 'subnet',
	'universe', 'start', 'end', 'nchans', 'status', 'summary']


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.appendRow(COLS)
	groups = scriptOp.inputs[0] if scriptOp.inputs else None
	ports = op('ports')
	home = parent().parent()
	port_rows = {}
	if ports is not None:
		for r in range(1, ports.numRows):
			port_rows[ports[r, 'port_id'].val] = r
	rows = []
	if groups is not None:
		for r in range(1, groups.numRows):
			g, cname, sname = groups[r, 'group'].val, groups[r, 'comp'].val, groups[r, 'select'].val
			comp = home.op(cname)
			sel = comp.op(sname) if comp is not None else None
			if comp is None or sel is None:
				rows.append([g, cname, sname, 0, '', '', '', '', '', '', '', 0, 'missing'])
				continue
			enabled = 1 if comp.par.Patchenable.eval() else 0
			pid = str(comp.par.Outputport.eval())
			start = int(comp.par.Startaddress.eval())
			n = sel.numChans
			end = start + n - 1
			pr = port_rows.get(pid)
			if not enabled:
				status = 'off'
				ip = net = sub = uni = ''
			elif pr is None:
				status = 'no_port'
				ip = net = sub = uni = ''
			else:
				ip, net = ports[pr, 'ip'].val, ports[pr, 'net'].val
				sub, uni = ports[pr, 'subnet'].val, ports[pr, 'universe'].val
				status = 'ok' if ports[pr, 'online'].val == '1' else 'offline'
				if end > 512 or start < 1:
					status = 'overflow'
			rows.append([g, cname, sname, enabled, pid, ip, net, sub, uni, start, end, n, status])
	# overlaps between enabled groups on the same port
	for i, a in enumerate(rows):
		for b in rows[i + 1:]:
			if a[3] and b[3] and a[4] == b[4] and a[12] in ('ok', 'offline') and b[12] in ('ok', 'offline'):
				if not (int(a[10]) < int(b[9]) or int(b[10]) < int(a[9])):
					a[12] = b[12] = 'conflict'
	sent = [x[0] for x in rows if x[12] in ('ok', 'offline', 'conflict')]
	bad = ['%s=%s' % (x[0], x[12]) for x in rows if x[12] not in ('ok', 'off')]
	summary = 'invio: %s%s' % (', '.join(sent) or 'nessuno', ('  |  ' + ', '.join(bad)) if bad else '')
	for x in rows:
		scriptOp.appendRow(x + [summary])
	return
