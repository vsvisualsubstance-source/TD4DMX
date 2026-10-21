"""heads_dmx -- DMX channels of all moving heads, in DMX address order:
head1_<attr> ... head1_<last>, head2_<attr> ... (attribute order = the
profile 'channels' column of head_profiles). This CHOP is the patch group
output read by /project1/dmx_patch (groups row 'heads'). One head per unit of
the fixture patch, each with its OWN profile (mixed head models are fine).

Position (degrees from the head center):
- Control = manual: every head gets Pan/Tilt pars;
- Control = ptz: per-head targets from input 0 (channels head<n>_pan /
  head<n>_tilt in degrees, from the PTZ control); heads without a target
  channel fall back to Pan/Tilt.
Then per head (head_config): + offset, invert, clamp to [min, max] (blank =
the profile range), and 16-bit when the profile has pan_fine / tilt_fine.

Per-head programmer (head_programmer, Plancia /mh/* and Gaia heads_*): a
head with a head_state row overrides the above -- manual = its own pan /
tilt / look (blank fields = global), follow = pan/tilt from its PTZ target
whatever Control says; strobe gates its shutter at dmx_patch Stroberate.

Attributes not driven here use the profile 'defaults' (e.g. shutter=255,
the open value -- check the fixture manual) or 0. A lamp command
(head_programmer.lamp) holds the model's lamp value on its channel for
its hold time.
"""


def _unit_profiles(comp):
	"""Profile name per head (index 0 = head 1) from the fixture patch
	(/project1/dmx_patch/fixtures); without it: Count x Profile."""
	fx = comp.parent().op('dmx_patch/fixture_logic')
	if fx is not None:
		try:
			names = fx.module.unit_profiles(comp, cached=False)
			if names:
				return names
		except Exception as e:
			debug('fixture_logic.unit_profiles:', e)
	return [str(comp.par.Profile.eval())] * max(1, int(comp.par.Count.eval()))


def _profile(comp, name):
	t = comp.op('head_profiles')
	if t is None or t[name, 'channels'] is None:
		return ['pan', 'tilt', 'dimmer'], 540.0, 270.0, {}
	chans = str(t[name, 'channels'].val).split()
	defaults = {}
	for kv in str(t[name, 'defaults'].val if t[name, 'defaults'] is not None else '').split():
		if '=' in kv:
			k, v = kv.split('=', 1)
			try:
				defaults[k] = float(v)
			except ValueError:
				pass
	def num(col, d):
		try:
			return float(t[name, col].val)
		except Exception:
			return d
	return chans, num('pan_range', 540.0), num('tilt_range', 270.0), defaults


def _head_cfg(comp, n, pan_range, tilt_range):
	t = comp.op('head_config')
	cfg = {'pan_offset': 0.0, 'tilt_offset': 0.0, 'invert_pan': 0.0, 'invert_tilt': 0.0,
		'pan_min': -pan_range / 2, 'pan_max': pan_range / 2, 'tilt_min': -tilt_range / 2, 'tilt_max': tilt_range / 2}
	if t is not None and t[str(n), 'head'] is not None:
		for k in cfg:
			c = t[str(n), k]
			if c is not None and str(c.val).strip() != '':
				try:
					cfg[k] = float(c.val)
				except ValueError:
					pass
	return cfg


def _to_dmx(deg, rng, lo, hi):
	"""degrees from center -> 0..65535 over the full range"""
	deg = max(lo, min(hi, deg))
	norm = (deg + rng / 2.0) / rng
	return int(round(max(0.0, min(1.0, norm)) * 65535))


def onSetupParameters(scriptOp):
	return


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.isTimeSlice = False
	scriptOp.numSamples = 1
	comp = parent()
	profiles = _unit_profiles(comp)
	ptz = str(comp.par.Control.eval()) == 'ptz' and len(scriptOp.inputs) > 0
	targets = scriptOp.inputs[0] if ptz else None
	p = comp.par
	look = {
		'dimmer': float(p.Dimmer.eval()) * 255.0,
		'red': float(p.Colorr.eval()) * 255.0,
		'green': float(p.Colorg.eval()) * 255.0,
		'blue': float(p.Colorb.eval()) * 255.0,
		'white': float(p.White.eval()) * 255.0,
		'color': float(p.Colorwheel.eval()),
		'gobo': float(p.Gobo.eval()),
		'zoom': float(p.Zoom.eval()) * 255.0,
		'focus': float(p.Focus.eval()) * 255.0,
		'speed': (1.0 - float(p.Speed.eval())) * 255.0,
	}
	shutter_open = bool(p.Shutteropen.eval())
	# per-head programmer (head_programmer: Plancia /mh/*, Gaia heads_*):
	# a head with a state row overrides the global look / position
	ustate, lamps = {}, {}
	hp = comp.op('head_programmer')
	if hp is not None:
		try:
			ku = hp.module.keys_by_unit()
			ustate = hp.module.unit_state(ku)
			lamps = hp.module.lamp_values(ku)
		except Exception as e:
			debug('head_programmer.unit_state:', e)
	follow_src = scriptOp.inputs[0] if len(scriptOp.inputs) > 0 else None
	strobing = any(s and s.get('strobe') for s in ustate.values())
	strobe_on = hp.module.strobe_open() if strobing else True
	for n in range(1, len(profiles) + 1):
		chans, pan_range, tilt_range, defaults = _profile(comp, profiles[n - 1])
		cfg = _head_cfg(comp, n, pan_range, tilt_range)
		st = ustate.get(n)
		pan, tilt = float(p.Pan.eval()), float(p.Tilt.eval())
		src = targets
		if st is not None:
			src = follow_src if st['mode'] == 'follow' else None
			if st['mode'] == 'manual':
				pan = st['pan'] if st['pan'] is not None else pan
				tilt = st['tilt'] if st['tilt'] is not None else tilt
		if src is not None:
			tp, tt = src['head%d_pan' % n], src['head%d_tilt' % n]
			if tp is not None:
				pan = float(tp[0])
			if tt is not None:
				tilt = float(tt[0])
		pan = (-pan if cfg['invert_pan'] else pan) + cfg['pan_offset']
		tilt = (-tilt if cfg['invert_tilt'] else tilt) + cfg['tilt_offset']
		pan16 = _to_dmx(pan, pan_range, cfg['pan_min'], cfg['pan_max'])
		tilt16 = _to_dmx(tilt, tilt_range, cfg['tilt_min'], cfg['tilt_max'])
		has_pan_fine, has_tilt_fine = 'pan_fine' in chans, 'tilt_fine' in chans
		values = dict(look)
		if st is not None:
			for f in ('dimmer', 'red', 'green', 'blue', 'white', 'zoom', 'focus'):
				if st[f] is not None:
					values[f] = st[f] * 255.0
			for f in ('color', 'gobo'):
				if st[f] is not None:
					values[f] = st[f]
		# CMY heads: the requested colour as subtractive filters
		for c, k in (('red', 'cyan'), ('green', 'magenta'), ('blue', 'yellow')):
			if k in chans:
				values[k] = 255.0 - float(values.get(c, 255.0))
		values['pan'] = (pan16 >> 8) if has_pan_fine else round(pan16 / 257.0)
		values['pan_fine'] = pan16 & 0xFF
		values['tilt'] = (tilt16 >> 8) if has_tilt_fine else round(tilt16 / 257.0)
		values['tilt_fine'] = tilt16 & 0xFF
		open_now = shutter_open and (strobe_on if st is not None and st['strobe'] else True)
		values['shutter'] = defaults.get('shutter', 255.0) if open_now else 0.0
		lamp = lamps.get(n)
		if lamp is not None:
			values[lamp[0]] = lamp[1]
		seen = {}
		for attr in chans:
			k = seen.get(attr, 0)
			seen[attr] = k + 1
			name = 'head%d_%s' % (n, attr) + ('_%d' % k if k else '')
			v = values.get(attr, defaults.get(attr, 0.0))
			scriptOp.appendChan(name)[0] = max(0.0, min(255.0, float(v)))
	return
