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

2026-10-01: also registers the audio engine (/project1/audio_engine). It has
TWO independent sources (source_a, source_b; source_b is a clone of
source_a) registered as 'audio_a_*' / 'audio_b_*', and each rig picks which
one drives it via its Audiobus par ('dmx_<rig>_audio_source', enum a|b):
both rigs on 'a' = one shared source, 'a' + 'b' = two different sources.
Published under a top-level 'audio' key of dmx_matrix ({'sources': {a, b}});
the 'rigs' key gains only dmx_audio_source. dmx_<rig>_use_file_input still
works: it switches the Type of the source THAT rig is listening to.

2026-10-01: DMX output is centralized in /project1/dmx_patch (scan of Art-Net
nodes/ports + one stream per universe, groups at their real start address).
Per rig: dmx_<rig>_output_port (enum of scanned port ids) and
dmx_<rig>_patch_enable; device-wide: dmx_scan, dmx_output, dmx_blackout.
dmx_matrix gains a top-level 'patch' key ({services, ports}).

2026-10-01: audio_<x>_type gains touch_audio (raw audio from another TD over
Touch Out, analyzed locally) and touch_bands (bands analyzed by the sender);
audio_<x>_sender picks the Touch sender, discovered by touch_discovery (this
COMP) from gaia/device/+/status -- see GAIA_INTERFACE "TD/Mac-Ctrl, 2".

2026-10-01: moving heads (/project1/moving_heads, a dmx_patch group) as
'heads_*' params/services; dmx_matrix gains a top-level 'heads' key.
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
	('dmx_audio_source', 'Audiobus'),
	# options = port ids found by the dmx_patch scan ("<node ip>:<port>")
	('dmx_output_port', 'Outputport'),
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
	('dmx_patch_enable', 'bool'),
]

# Centralized DMX output + network scan (/project1/dmx_patch), one per
# device, unprefixed: dmx_scan (action), dmx_output / dmx_blackout (bool).
PATCH_SERVICES = [
	('dmx_scan', 'action', 'Scan'),
	('dmx_output', 'bool', 'Output'),
	('dmx_blackout', 'bool', 'Blackout'),
]


def _patch():
	return me.parent().parent().op('dmx_patch')


# Moving heads (/project1/moving_heads): 'heads_*', one group per device.
HEADS_FLOAT_PARAMS = [
	('heads_pan', 'Pan'),
	('heads_tilt', 'Tilt'),
	('heads_speed', 'Speed'),
	('heads_dimmer', 'Dimmer'),
	('heads_white', 'White'),
	('heads_zoom', 'Zoom'),
	('heads_focus', 'Focus'),
]

HEADS_INT_PARAMS = [
	('heads_count', 'Count'),
	('heads_start_address', 'Startaddress'),
	('heads_color_wheel', 'Colorwheel'),
	('heads_gobo', 'Gobo'),
]

# enum options = menuNames (profile names, port ids, manual|ptz)
HEADS_MENU_PARAMS = [
	('heads_profile', 'Profile'),
	('heads_output_port', 'Outputport'),
	('heads_control', 'Control'),
]

HEADS_SERVICES = [
	('heads_patch_enable', 'bool', 'Patchenable'),
	('heads_shutter_open', 'bool', 'Shutteropen'),
	('heads_home', 'action', 'Home'),
]


def _heads():
	return me.parent().parent().op('moving_heads')


def _build_heads_matrix():
	h = _heads()
	params = {}
	for name, par_name in HEADS_FLOAT_PARAMS:
		par = h.par[par_name]
		params[name] = {'kind': 'param', 'type': 'float', 'range': _numeric_range(par), 'default': float(par.default)}
	for name, par_name in HEADS_INT_PARAMS:
		par = h.par[par_name]
		params[name] = {'kind': 'param', 'type': 'int', 'range': _numeric_range(par), 'default': int(par.default)}
	for name, par_name in HEADS_MENU_PARAMS:
		par = h.par[par_name]
		params[name] = {'kind': 'param', 'type': 'enum', 'options': list(par.menuNames), 'default': str(par.default)}
	params['heads_color'] = {'kind': 'param', 'type': 'color_rgb', 'range': [0.0, 1.0]}
	services = {name: {'kind': 'service', 'type': kind} for name, kind, _ in HEADS_SERVICES}
	return {'params': params, 'services': services}


def _build_patch_matrix():
	"""Services + the ports found by the last scan (read-only info for UIs)."""
	ports = _patch().op('ports')
	rows = []
	if ports is not None and ports.numRows > 1:
		head = [c.val for c in ports.row(0)]
		for r in range(1, ports.numRows):
			rows.append({h: ports[r, h].val for h in head})
	services = {name: {'kind': 'service', 'type': kind} for name, kind, _ in PATCH_SERVICES}
	return {'services': services, 'ports': rows}


# Audio engine sources (/project1/audio_engine/source_a|source_b): names are
# 'audio_<letter>_<suffix>', e.g. audio_a_gain, audio_b_type.
SOURCES = [
	('a', 'source_a'),
	('b', 'source_b'),
]

AUDIO_FLOAT_PARAMS = [
	('gain', 'Gain'),
	('bass_cutoff', 'Basscutoff'),
	('mid_low', 'Midlow'),
	('mid_high', 'Midhigh'),
	('high_cutoff', 'Highcutoff'),
	('bass_gain', 'Bassgain'),
	('mid_gain', 'Midgain'),
	('high_gain', 'Highgain'),
]

# (suffix, par, publish_labels): device menus publish the human LABELS
# (device names), not TD's internal GUID-style menuNames; 'type' publishes
# its names (scheda_audio / file_demo), as agreed in GAIA_INTERFACE "Core, 14".
AUDIO_MENU_PARAMS = [
	('type', 'Type', False),
	# Touch LAN sender (device_id) -- options = senders found by
	# touch_discovery for the current type (empty unless type is touch_*)
	('sender', 'Sender', False),
	('driver', 'Driver', True),
	('device', 'Device', True),
]

AUDIO_SERVICES = [
	('active', 'bool', 'Active'),
]


def _engine():
	return me.parent().parent().op('audio_engine')


def _source(src_name):
	return _engine().op(src_name)


def _source_for_rig(rig_name):
	"""The audio source COMP the rig is listening to (its Audiobus)."""
	return _source('source_' + str(_rig(rig_name).par.Audiobus.eval()))


def _register_source_menu(agent, name, src_name, par_name, labels_out):
	def get():
		par = _source(src_name).par[par_name]
		val = str(par.eval())
		names = list(par.menuNames)
		if labels_out and val in names:
			return par.menuLabels[names.index(val)]
		return val

	def set_(value):
		par = _source(src_name).par[par_name]
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


def _build_source_matrix(letter, src_name):
	src = _source(src_name)
	prefix = 'audio_%s_' % letter
	params = {}
	for suffix, par_name in AUDIO_FLOAT_PARAMS:
		par = src.par[par_name]
		params[prefix + suffix] = {
			'kind': 'param',
			'type': 'float',
			'range': _numeric_range(par),
			'default': float(par.default),
		}
	for suffix, par_name, labels_out in AUDIO_MENU_PARAMS:
		par = src.par[par_name]
		names = list(par.menuNames)
		default = str(par.default)
		if labels_out:
			options = list(par.menuLabels)
			default = par.menuLabels[names.index(default)] if default in names else default
		else:
			options = names
		params[prefix + suffix] = {
			'kind': 'param',
			'type': 'enum',
			'options': options,
			'default': default,
		}
	services = {prefix + suffix: {'kind': 'service', 'type': kind} for suffix, kind, _ in AUDIO_SERVICES}
	return {'params': params, 'services': services}


def _build_audio_matrix():
	return {'sources': {letter: _build_source_matrix(letter, src_name) for letter, src_name in SOURCES}}


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
	_register_menu_on(agent, name, lambda: _rig(rig_name), par_name)


def _register_menu_on(agent, name, comp, par_name):
	"""Enum param on any COMP (comp = zero-arg resolver, called at use time):
	accepts the menu name or its index."""
	def get():
		return str(comp().par[par_name].eval())

	def set_(value):
		par = comp().par[par_name]
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


def _register_color(agent, name, rig_name, base_par, comp=None):
	target = comp or (lambda: _rig(rig_name))

	def get():
		rig = target()
		return [
			float(rig.par[base_par + 'r'].eval()),
			float(rig.par[base_par + 'g'].eval()),
			float(rig.par[base_par + 'b'].eval()),
		]

	def set_(value):
		rig = target()
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
		'patch': _build_patch_matrix(),
		'heads': _build_heads_matrix(),
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
			start=lambda rn=rig_name: setattr(_source_for_rig(rn).par, 'Type', 'file_demo'),
			stop=lambda rn=rig_name: setattr(_source_for_rig(rn).par, 'Type', 'scheda_audio'),
			status=lambda rn=rig_name: _source_for_rig(rn).par.Type.eval() == 'file_demo')

		agent.register_service(
			prefix + 'apply_fixture_profile',
			start=lambda rn=rig_name: _rig(rn).par.Applyfixture.pulse())

		agent.register_service(
			prefix + 'patch_enable',
			start=lambda rn=rig_name: setattr(_rig(rn).par, 'Patchenable', 1),
			stop=lambda rn=rig_name: setattr(_rig(rn).par, 'Patchenable', 0),
			status=lambda rn=rig_name: bool(_rig(rn).par.Patchenable.eval()))

	for name, par_name in HEADS_FLOAT_PARAMS:
		_register_value(agent, name, None, par_name, float, comp=_heads)
	for name, par_name in HEADS_INT_PARAMS:
		_register_value(agent, name, None, par_name, int, comp=_heads)
	for name, par_name in HEADS_MENU_PARAMS:
		_register_menu_on(agent, name, _heads, par_name)
	_register_color(agent, 'heads_color', None, 'Color', comp=_heads)
	for name, kind, par_name in HEADS_SERVICES:
		if kind == 'action':
			agent.register_service(name, start=lambda pn=par_name: _heads().par[pn].pulse())
		else:
			agent.register_service(
				name,
				start=lambda pn=par_name: setattr(_heads().par, pn, 1),
				stop=lambda pn=par_name: setattr(_heads().par, pn, 0),
				status=lambda pn=par_name: bool(_heads().par[pn].eval()))

	agent.register_service(
		'dmx_scan',
		start=lambda: _patch().par.Scan.pulse())
	for name, kind, par_name in PATCH_SERVICES[1:]:
		agent.register_service(
			name,
			start=lambda pn=par_name: setattr(_patch().par, pn, 1),
			stop=lambda pn=par_name: setattr(_patch().par, pn, 0),
			status=lambda pn=par_name: bool(_patch().par[pn].eval()))

	for letter, src_name in SOURCES:
		prefix = 'audio_%s_' % letter
		for suffix, par_name in AUDIO_FLOAT_PARAMS:
			_register_value(agent, prefix + suffix, None, par_name, float,
				comp=lambda sn=src_name: _source(sn))
		for suffix, par_name, labels_out in AUDIO_MENU_PARAMS:
			_register_source_menu(agent, prefix + suffix, src_name, par_name, labels_out)
		for suffix, _kind, par_name in AUDIO_SERVICES:
			agent.register_service(
				prefix + suffix,
				start=lambda sn=src_name, pn=par_name: setattr(_source(sn).par, pn, 1),
				stop=lambda sn=src_name, pn=par_name: setattr(_source(sn).par, pn, 0),
				status=lambda sn=src_name, pn=par_name: bool(_source(sn).par[pn].eval()))

	print('[DMX Services] %d services/params registered' % (
		len(agent._services) + len(agent._params)))

	publish_matrix()
