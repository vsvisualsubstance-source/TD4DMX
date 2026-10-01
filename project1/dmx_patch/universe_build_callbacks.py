"""universe_build -- composes one 512-sample channel per Art-Net universe
(DMX Out CHOP 'Packet Per Channel' format): every sendable group from
patch_report is written at its real start address. Channel name encodes the
destination, u_<net>_<subnet>_<universe>_<ip>; the routing table maps it.
"""


def chan_name(net, sub, uni, ip):
	return 'u_%s_%s_%s_%s' % (net, sub, uni, ip.replace('.', '_'))


def onSetupParameters(scriptOp):
	return


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.isTimeSlice = False
	scriptOp.numSamples = 512
	rep = op('patch_report')
	home = parent().parent()
	blackout = bool(parent().par.Blackout.eval())
	universes = {}
	for r in range(1, rep.numRows):
		if rep[r, 'status'].val not in ('ok', 'offline', 'conflict'):
			continue
		name = chan_name(rep[r, 'net'].val, rep[r, 'subnet'].val, rep[r, 'universe'].val, rep[r, 'ip'].val)
		buf = universes.setdefault(name, [0.0] * 512)
		if blackout:
			continue
		comp = home.op(rep[r, 'comp'].val)
		sel = comp.op(rep[r, 'select'].val) if comp is not None else None
		if sel is None:
			continue
		start = int(rep[r, 'start'].val) - 1
		for i, ch in enumerate(sel.chans()):
			addr = start + i
			if 0 <= addr < 512:
				buf[addr] = max(0.0, min(255.0, float(ch[0])))
	for name in sorted(universes):
		c = scriptOp.appendChan(name)
		c.vals = universes[name]
	return
