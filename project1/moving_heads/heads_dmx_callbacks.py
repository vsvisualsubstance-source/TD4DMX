"""heads_dmx -- DMX channels of all moving heads, in DMX address order:
head1_<attr> ... head1_<last>, head2_<attr> ... (attribute order = the
profile 'channels' column of head_profiles). This CHOP is the patch group
output read by /project1/dmx_patch (groups row 'heads').

Position (degrees from the head center):
- Control = manual: every head gets Pan/Tilt pars;
- Control = ptz: per-head targets from input 0 (channels head<n>_pan /
  head<n>_tilt in degrees, from the PTZ control); heads without a target
  channel fall back to Pan/Tilt.
Then per head (head_config): + offset, invert, clamp to [min, max] (blank =
the profile range), and 16-bit when the profile has pan_fine / tilt_fine.

Attributes not driven here use the profile 'defaults' (e.g. shutter=255,
the open value -- check the fixture manual) or 0.
"""


def _profile(comp):
	t = comp.op('head_profiles')
	name = str(comp.par.Profile.eval())
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
	chans, pan_range, tilt_range, defaults = _profile(comp)
	count = max(1, int(comp.par.Count.eval()))
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
	for n in range(1, count + 1):
		cfg = _head_cfg(comp, n, pan_range, tilt_range)
		pan, tilt = float(p.Pan.eval()), float(p.Tilt.eval())
		if targets is not None:
			tp, tt = targets['head%d_pan' % n], targets['head%d_tilt' % n]
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
		values['pan'] = (pan16 >> 8) if has_pan_fine else round(pan16 / 257.0)
		values['pan_fine'] = pan16 & 0xFF
		values['tilt'] = (tilt16 >> 8) if has_tilt_fine else round(tilt16 / 257.0)
		values['tilt_fine'] = tilt16 & 0xFF
		values['shutter'] = defaults.get('shutter', 255.0) if shutter_open else 0.0
		seen = {}
		for attr in chans:
			k = seen.get(attr, 0)
			seen[attr] = k + 1
			name = 'head%d_%s' % (n, attr) + ('_%d' % k if k else '')
			v = values.get(attr, defaults.get(attr, 0.0))
			scriptOp.appendChan(name)[0] = max(0.0, min(255.0, float(v)))
	return
