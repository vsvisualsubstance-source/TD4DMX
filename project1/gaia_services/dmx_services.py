"""
DMX Services -- project-specific registrar for gaia_client (the portable
Gaia Agent Universale). Registers the real controls of BOTH DMX rigs
(dmx_audio_chase / dmx_audio_chase_b) as Gaia services/params on the ONE
shared device identity (Deviceid on op.Gaia -- td-dmx-win on the MSI PC), and publishes the combined
control matrix so a Gaia-side UI builder doesn't have to decode parameter
names.

Replaces the old per-rig gaia_device_agent / gaia_device_agent_b pair (each
had its own device identity and its own dmx_services.py, operating on a
single Rigname). gaia_client is a single portable core shared with other
projects (see its own docstrings: those files stay identical across
projects) -- this file is the project-specific glue and lives ONLY here.

Both rigs now share one Gaia device identity, so registered names are
prefixed per rig ('dmx_a_...' for dmx_audio_chase, 'dmx_b_...' for
dmx_audio_chase_b) -- unprefixed names would collide.

Wired via gaia_device_agent.register_project_registrar() from
dmx_services_lifecycle.py, which also calls register_all() once directly
at onCreate. gaia_client's own self-heal (_self_check(), called every
frame from perf_tick()) retries register_all() automatically if the
registry is ever found empty (e.g. after this file hot-reloads and wipes
_services/_params).

Moved 2026-10-01 (TD/Win-PD) out of gaia_client into /project1/gaia_services,
same layout as PatchDeck's /PATCHDECK/gaia_services: gaia_client is now the
unmodified portable 1.2.1 .tox, reached via its global shortcut op.Gaia.

2026-10-01: also registers the shared audio engine (/project1/audio_engine,
one audio input for both rigs) as unprefixed 'audio_*' params/services, and
publishes it under a top-level 'audio' key of dmx_matrix (the 'rigs' key is
unchanged). dmx_{a,b}_use_file_input still work: each rig's Usefileinput is
bound to audio_engine.Usefile, so they now switch the SHARED source.
"""
import json
import time

RIGS = [
	('a', 'dmx_audio_chase'),
	('b', 'dmx_audio_chase_b'),
]

FLOAT_PARAMS = [
	('dmx_min_dimmer', 'Mindimmer'),
	('dmx_max_dimmer', 'Maxdimmer'),
	('dmx_dimmer_boost', 'Dimmerboost'),
	('dmx_dimmer_gamma', 'Dimmergamma'),
	('dmx_smooth_factor', 'Smoothfactor'),
	('dmx_color_curve', 'Colorcurve'),
	('dmx_color_fade', 'Colorsmooth'),
	('dmx_color_speed', 'Colorspeed'),
	('dmx_color_phase', 'Colorphase'),
	('dmx_bar_phase', 'Barphase'),
	('dmx_global_smooth', 'Globalsmooth'),
	('dmx_agc_release', 'Agcrelease'),
	('dmx_min_range', 'Minrange'),
	('dmx_kick_threshold', 'Kickthresh'),
	('dmx_kick_boost', 'Kickboost'),
	('dmx_kick_decay', 'Kickdecay'),
	('dmx_kick_cooldown', 'Kickcooldown'),
	('dmx_kick_smooth', 'Kicksmooth'),
]

INT_PARAMS = [
	('dmx_fixture_count', 'Nbars'),
	('dmx_start_address', 'Startaddress'),
]

MENU_PARAMS = [
	('dmx_palette', 'Palette'),
	('dmx_fixture_profile', 'Fixtureprofile'),
]

COLOR_PARAMS = [
	('dmx_custom_color1', 'Custompalette1'),
	('dmx_custom_color2', 'Custompalette2'),
	('dmx_custom_color3', 'Custompalette3'),
	('dmx_custom_color4', 'Custompalette4'),
	('dmx_custom_color5', 'Custompalette5'),
]

SERVICES = [
	('dmx_kick_enable', 'bool'),
	('dmx_use_file_input', 'bool'),
	('dmx_apply_fixture_profile', 'action'),
]


# Shared audio engine (/project1/audio_engine, one input for BOTH rigs) --
# registered once, unprefixed by rig: 'audio_*'.
AUDIO_FLOAT_PARAMS = [
	('audio_gain', 'Gain'),
	('audio_bass_cutoff', 'Basscutoff'),
	('audio_mid_low', 'Midlow'),
	('audio_mid_high', 'Midhigh'),
	('audio_high_cutoff', 'Highcutoff'),
	('audio_bass_gain', 'Bassgain'),
	('audio_mid_gain', 'Midgain'),
	('audio_high_gain', 'Highgain'),
]

# Device menus: options are the human LABELS (device names), not TD's
# internal GUID-style menuNames -- a remote UI shows/sends names.
AUDIO_MENU_PARAMS = [
	('audio_driver', 'Driver'),
	('audio_device', 'Device'),
]

AUDIO_SERVICES = [
	('audio_active', 'bool', 'Active'),
	('audio_use_file', 'bool', 'Usefile'),
]


def _engine():
	return me.parent().parent().op('audio_engine')


def _register_engine_menu(agent, name, par_name):
	def get():
		par = _engine().par[par_name]
		val = str(par.eval())
		names = list(par.menuNames)
		return par.menuLabels[names.index(val)] if val in names else val

	def set_(value):
		par = _engine().par[par_name]
		names, labels = list(par.menuNames), list(par.menuLabels)
		if isinstance(value, str) and value in labels:
			par.val = names[labels.index(value)]
			return
		if isinstance(value, str) and value in names:
			par.val = value
			return
		try:
			idx = int(value)
		except (TypeError, ValueError):
			idx = None
		if idx is not None and 0 <= idx < len(names):
			par.val = names[idx]
			return
		raise ValueError('%s: invalid value %r (options: %s)' % (
			par_name, value, ', '.join(labels)))

	agent.register_param(name, get=get, set=set_)


def _build_audio_matrix():
	eng = _engine()
	params = {}
	for name, par_name in AUDIO_FLOAT_PARAMS:
		par = eng.par[par_name]
		params[name] = {
			'kind': 'param',
			'type': 'float',
			'range': _numeric_range(par),
			'default': float(par.default),
		}
	for name, par_name in AUDIO_MENU_PARAMS:
		par = eng.par[par_name]
		names = list(par.menuNames)
		default = str(par.default)
		params[name] = {
			'kind': 'param',
			'type': 'enum',
			'options': list(par.menuLabels),
			'default': par.menuLabels[names.index(default)] if default in names else default,
		}
	services = {name: {'kind': 'service', 'type': kind} for name, kind, _ in AUDIO_SERVICES}
	return {'params': params, 'services': services}


def _rig(rig_name):
	# this DAT lives in /project1/gaia_services -- rig COMPs are siblings of
	# gaia_services (and of gaia_client) under /project1.
	return me.parent().parent().op(rig_name)


def _register_value(agent, name, rig_name, par_name, cast, comp=None):
	# comp: optional zero-arg resolver for a non-rig COMP (audio_engine);
	# resolved at call time, never cached (survives TD reinit/rebuild).
	target = comp or (lambda: _rig(rig_name))

	def get():
		return cast(target().par[par_name].eval())

	def set_(value):
		target().par[par_name] = cast(value)

	agent.register_param(name, get=get, set=set_)


def _register_menu(agent, name, rig_name, par_name):
	def get():
		return str(_rig(rig_name).par[par_name].eval())

	def set_(value):
		par = _rig(rig_name).par[par_name]
		names = list(par.menuNames)
		if isinstance(value, str) and value in names:
			par.val = value
			return
		# some generic UI enums send the selected INDEX instead of the label
		try:
			idx = int(value)
		except (TypeError, ValueError):
			idx = None
		if idx is not None and 0 <= idx < len(names):
			par.val = names[idx]
			return
		raise ValueError('%s: invalid value %r (options: %s)' % (
			par_name, value, ', '.join(names)))

	agent.register_param(name, get=get, set=set_)


def _register_color(agent, name, rig_name, base_par):
	def get():
		rig = _rig(rig_name)
		return [
			float(rig.par[base_par + 'r'].eval()),
			float(rig.par[base_par + 'g'].eval()),
			float(rig.par[base_par + 'b'].eval()),
		]

	def set_(value):
		rig = _rig(rig_name)
		r, g, b = value
		rig.par[base_par + 'r'] = float(r)
		rig.par[base_par + 'g'] = float(g)
		rig.par[base_par + 'b'] = float(b)

	agent.register_param(name, get=get, set=set_)


def _numeric_range(par):
	"""Real control range -- clamp if set, otherwise the slider range
	(normMin/normMax), never a made-up value."""
	lo = par.min if par.clampMin else par.normMin
	hi = par.max if par.clampMax else par.normMax
	return [round(float(lo), 6), round(float(hi), 6)]


def _build_matrix_for_rig(rig_name):
	rig = _rig(rig_name)
	params = {}

	for name, par_name in FLOAT_PARAMS:
		par = rig.par[par_name]
		params[name] = {
			'kind': 'param',
			'type': 'float',
			'range': _numeric_range(par),
			'default': float(par.default),
		}

	for name, par_name in INT_PARAMS:
		par = rig.par[par_name]
		params[name] = {
			'kind': 'param',
			'type': 'int',
			'range': _numeric_range(par),
			'default': int(par.default),
		}

	for name, par_name in MENU_PARAMS:
		par = rig.par[par_name]
		params[name] = {
			'kind': 'param',
			'type': 'enum',
			'options': list(par.menuNames),
			'default': str(par.default),
		}

	for name, base_par in COLOR_PARAMS:
		params[name] = {
			'kind': 'param',
			'type': 'color_rgb',
			'range': [0.0, 1.0],
		}

	services = {name: {'kind': 'service', 'type': kind} for name, kind in SERVICES}

	return {'params': params, 'services': services}


def publish_matrix():
	"""Publishes the combined per-rig matrix on MQTT, retained -- survives
	device reconnects, stays on the broker until overwritten by a future
	republish."""
	dat = op.Gaia.op('mqtt_device')
	if not dat or not dat.isConnected:
		print('[DMX Services] mqtt_device not connected, matrix not published')
		return False
	cfg_op = op.Gaia
	device_id = cfg_op.par.Deviceid.eval() if cfg_op else 'unknown'
	family = (cfg_op.par.Family.eval() if cfg_op else '') or 'dmx'
	payload = {
		'device_id': device_id,
		'rigs': {letter: _build_matrix_for_rig(rig_name) for letter, rig_name in RIGS},
		'audio': _build_audio_matrix(),
		'ts': int(time.time() * 1000),
	}
	topic = 'gaia/devices/%s/%s_matrix' % (device_id, family.lower())
	dat.publish(topic, json.dumps(payload).encode('utf-8'), retain=True)
	print('[DMX Services] Matrix published to %s' % topic)
	return True


def register_all():
	agent = op.Gaia.op('gaia_device_agent').module

	for letter, rig_name in RIGS:
		prefix = 'dmx_%s_' % letter

		for name, par_name in FLOAT_PARAMS:
			_register_value(agent, prefix + name[4:], rig_name, par_name, float)
		for name, par_name in INT_PARAMS:
			_register_value(agent, prefix + name[4:], rig_name, par_name, int)
		for name, par_name in MENU_PARAMS:
			_register_menu(agent, prefix + name[4:], rig_name, par_name)
		for name, base_par in COLOR_PARAMS:
			_register_color(agent, prefix + name[4:], rig_name, base_par)

		agent.register_service(
			prefix + 'kick_enable',
			start=lambda rn=rig_name: setattr(_rig(rn).par, 'Kickenable', 1),
			stop=lambda rn=rig_name: setattr(_rig(rn).par, 'Kickenable', 0),
			status=lambda rn=rig_name: bool(_rig(rn).par.Kickenable.eval()))

		agent.register_service(
			prefix + 'use_file_input',
			start=lambda rn=rig_name: setattr(_rig(rn).par, 'Usefileinput', 1),
			stop=lambda rn=rig_name: setattr(_rig(rn).par, 'Usefileinput', 0),
			status=lambda rn=rig_name: bool(_rig(rn).par.Usefileinput.eval()))

		agent.register_service(
			prefix + 'apply_fixture_profile',
			start=lambda rn=rig_name: _rig(rn).par.Applyfixture.pulse())

	for name, par_name in AUDIO_FLOAT_PARAMS:
		_register_value(agent, name, None, par_name, float, comp=_engine)
	for name, par_name in AUDIO_MENU_PARAMS:
		_register_engine_menu(agent, name, par_name)
	for name, _kind, par_name in AUDIO_SERVICES:
		agent.register_service(
			name,
			start=lambda pn=par_name: setattr(_engine().par, pn, 1),
			stop=lambda pn=par_name: setattr(_engine().par, pn, 0),
			status=lambda pn=par_name: bool(_engine().par[pn].eval()))

	print('[DMX Services] %d services/params registered' % (
		len(agent._services) + len(agent._params)))

	publish_matrix()
