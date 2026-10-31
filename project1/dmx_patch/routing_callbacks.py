"""routing -- DMX Out routing table: one row per universe channel of
universe_build -> Art-Net net / subnet / universe / node IP. Art-Net ports
only (USB ports have no ip; they go out through dmxout_<id>, see
interface_logic)."""


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.appendRow(['channel', 'net', 'subnet', 'universe', 'netaddress'])
	rep = scriptOp.inputs[0]
	seen = set()
	for r in range(1, rep.numRows):
		if rep[r, 'status'].val not in ('ok', 'offline', 'conflict'):
			continue
		net, sub, uni, ip = (rep[r, c].val for c in ('net', 'subnet', 'universe', 'ip'))
		if not ip:
			continue
		name = 'u_%s_%s_%s_%s' % (net, sub, uni, ip.replace('.', '_'))
		if name not in seen:
			seen.add(name)
			scriptOp.appendRow([name, net, sub, uni, ip])
	return
