"""universe_build -- composes one 512-sample channel per Art-Net universe
(DMX Out CHOP 'Packet Per Channel' format): every sendable FIXTURE of
patch_report gets the channels of its unit (<prefix><unit>_*, in the
generator's order = the profile's order) written at its own start address.
Channel name encodes the destination, u_<net>_<subnet>_<universe>_<ip>; the
routing table maps it.
"""
import re

_UNIT = re.compile(r'^[A-Za-z]+(\d+)_')
SENDABLE = ('ok', 'offline', 'conflict')


def chan_name(net, sub, uni, ip):
	return 'u_%s_%s_%s_%s' % (net, sub, uni, ip.replace('.', '_'))


def _units(sel):
	"""{unit: [values in channel order]} of a group CHOP."""
	out = {}
	for ch in sel.chans():
		m = _UNIT.match(ch.name)
		if m:
			out.setdefault(int(m.group(1)), []).append(float(ch[0]))
	return out


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
	cache = {}
	for r in range(1, rep.numRows):
		if rep[r, 'status'].val not in SENDABLE:
			continue
		name = chan_name(rep[r, 'net'].val, rep[r, 'subnet'].val, rep[r, 'universe'].val, rep[r, 'ip'].val)
		buf = universes.setdefault(name, [0.0] * 512)
		if blackout:
			continue
		key = (rep[r, 'comp'].val, rep[r, 'select'].val)
		if key not in cache:
			comp = home.op(key[0])
			sel = comp.op(key[1]) if comp is not None else None
			cache[key] = _units(sel) if sel is not None else {}
		vals = cache[key].get(int(rep[r, 'unit'].val), [])
		start = int(rep[r, 'start'].val) - 1
		n = int(rep[r, 'nchans'].val)
		for i, v in enumerate(vals[:n]):
			addr = start + i
			if 0 <= addr < 512:
				buf[addr] = max(0.0, min(255.0, v))
	for name in sorted(universes):
		c = scriptOp.appendChan(name)
		c.vals = universes[name]
	return
