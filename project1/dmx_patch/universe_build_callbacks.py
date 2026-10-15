"""universe_build -- composes one 512-sample channel per Art-Net universe
(DMX Out CHOP 'Packet Per Channel' format): every sendable FIXTURE of
patch_report gets the channels of its unit (<prefix><unit>_*, in the
generator's order = the profile's order) written at its own start address.
Channel name encodes the destination, u_<net>_<subnet>_<universe>_<ip>; the
routing table maps it.

Levels (Plancia channel 5): the INTENSITY channels of a fixture are scaled
by its group COMP's Level par (if it has one), dmx_patch Master, and the
Strobe gate (on 22% of each 1/Stroberate period). A profile with a dimmer
channel is scaled on dimmer* only (colour kept); without one, on its colour
and output channels. Pan/tilt/strobe/mode/fan/... are never scaled.
"""
import re

_UNIT = re.compile(r'^[A-Za-z]+(\d+)_')
SENDABLE = ('ok', 'offline', 'conflict')
COLOUR = ('red', 'green', 'blue', 'white', 'amber', 'uv', 'output')


def _intensity_idx(chans):
	"""Indices of the channels the group level acts on."""
	dim = [i for i, c in enumerate(chans) if c.startswith('dimmer')]
	return dim or [i for i, c in enumerate(chans) if c in COLOUR]


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
	pp = parent().par
	blackout = bool(pp.Blackout.eval())
	gain = float(pp.Master.eval())
	if pp.Strobe.eval():
		rate = max(0.5, float(pp.Stroberate.eval()))
		if (absTime.seconds * rate) % 1.0 >= 0.22:
			gain = 0.0
	fl = op('fixture_logic').module
	universes = {}
	cache = {}
	levels = {}
	idx_cache = {}
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
		if key[0] not in levels:
			comp = home.op(key[0])
			lp = comp.par['Level'] if comp is not None else None
			levels[key[0]] = float(lp.eval()) if lp is not None else 1.0
		k = levels[key[0]] * gain
		scaled = ()
		if k < 1.0:
			pk = (rep[r, 'group'].val, rep[r, 'profile'].val)
			if pk not in idx_cache:
				idx_cache[pk] = set(_intensity_idx(fl.profile_channels(*pk) or []))
			scaled = idx_cache[pk]
		start = int(rep[r, 'start'].val) - 1
		n = int(rep[r, 'nchans'].val)
		for i, v in enumerate(vals[:n]):
			addr = start + i
			if 0 <= addr < 512:
				if i in scaled:
					v *= k
				buf[addr] = max(0.0, min(255.0, v))
	for name in sorted(universes):
		c = scriptOp.appendChan(name)
		c.vals = universes[name]
	return
