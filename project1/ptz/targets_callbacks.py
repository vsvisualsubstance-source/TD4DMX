"""targets -- per-head pan/tilt aim (degrees from the head center) for
moving_heads (heads_dmx input, channels head<n>_pan / head<n>_tilt), plus
pan / tilt / u / v / tracking for monitoring.

uv (0-1, v up) comes from the XY pad (Mode = pad) or from the tracked body
landmark (Mode = mocap, or the simulator). It is smoothed (one-pole, Smooth
seconds), deadzoned, then mapped through the stage calibration:
  pan  = Pancenter  + (u - 0.5) * Panspan  (x -1 if Invertpan)
  tilt = Tiltcenter + (v - 0.5) * Tiltspan (x -1 if Inverttilt)
Per-head offsets / inversion / limits are applied later by heads_dmx
(moving_heads head_config).
"""
import math

_state = {'u': 0.5, 'v': 0.5, 't': None, 'last_valid': 0.0, 'tracking': 0}


def onSetupParameters(scriptOp):
	return


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.isTimeSlice = False
	scriptOp.numSamples = 1
	comp = parent()
	logic = op('ptz_logic').module
	now = absTime.seconds          # also makes this CHOP cook every frame
	st = _state
	dt = 0.0 if st['t'] is None else max(0.0, now - st['t'])
	st['t'] = now

	mode = str(comp.par.Mode.eval())
	target = None
	if mode == 'mocap':
		target = logic.simulated_uv(now) if comp.par.Simulate.eval() else logic.landmark_uv()
		if target is not None:
			st['last_valid'] = now
			st['tracking'] = 1
		else:
			st['tracking'] = 0
			if now - st['last_valid'] > float(comp.par.Losttimeout.eval()) and str(comp.par.Lost.eval()) == 'home':
				target = (0.5, 0.5)
	else:
		target = (float(comp.par.Padu.eval()), float(comp.par.Padv.eval()))
		st['tracking'] = 0

	if target is not None:
		dz = float(comp.par.Deadzone.eval())
		if mode == 'pad' or abs(target[0] - st['u']) > dz or abs(target[1] - st['v']) > dz or st['tracking'] == 0:
			tau = float(comp.par.Smooth.eval())
			k = 1.0 if tau <= 0.0 or dt <= 0.0 else 1.0 - math.exp(-dt / tau)
			st['u'] += (target[0] - st['u']) * k
			st['v'] += (target[1] - st['v']) * k

	u, v = st['u'], st['v']
	pan = (u - 0.5) * float(comp.par.Panspan.eval()) * (-1.0 if comp.par.Invertpan.eval() else 1.0) + float(comp.par.Pancenter.eval())
	tilt = (v - 0.5) * float(comp.par.Tiltspan.eval()) * (-1.0 if comp.par.Inverttilt.eval() else 1.0) + float(comp.par.Tiltcenter.eval())

	heads = comp.parent().op('moving_heads')
	count = max(1, int(heads.par.Count.eval())) if heads is not None else 1
	for n in range(1, count + 1):
		scriptOp.appendChan('head%d_pan' % n)[0] = pan
		scriptOp.appendChan('head%d_tilt' % n)[0] = tilt
	for name, val in (('pan', pan), ('tilt', tilt), ('u', u), ('v', v), ('tracking', st['tracking'])):
		scriptOp.appendChan(name)[0] = val
	return
