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

2026-10-01: PTZ (/project1/ptz) as 'ptz_*' -- XY pad, mocap follow (pose
landmark from Gaia channel 7), calibration, presets; dmx_matrix gains 'ptz'.

2026-10-02: fixture patch (/project1/dmx_patch/fixtures, one row per light,
mixed profiles per group) as 'dmx_fixture*' params, all JSON values:
  dmx_fixtures              rw  full list [{id,name,group,unit,profile,
                                port_id,address,x,y,enabled,palette}] (palette
                                '' = the rig's); set = replace
                                the whole patch (validated before writing)
  dmx_fixture_add           w   {group, profile?, port_id?, address?, unit?,
                                name?, x?, y?} -- missing = sensible defaults
  dmx_fixture_update        w   {id, <any field>...}
  dmx_fixture_remove        w   id
  dmx_fixture_auto_address  w   {group, start?, port_id?} -- consecutive
  dmx_patch_report          r   [{id,status,port_id,universe,start,end}]
Invalid values raise -> reported in the status 'last_error'. dmx_matrix gains
'fixtures' ({params, columns, groups: [{group, profiles: [{name, channels}]}]}).
The per-rig dmx_<rig>_fixture_count / start_address / fixture_profile /
output_port are the QUICK PATCH of that group (rewrite it as a uniform block).

2026-10-02: show timeline (/project1/show: scenes, cues with crossfade,
automation lanes, internal clock) as 'show_*':
  services  show_play, show_loop, show_active (timeline drives the output;
            off = live), show_rewind (action)
  params    show_time / show_length (float s), show_status (r),
            show_scene_recall (enum = scene names; set = apply now),
            show_scene_capture (w: name -> scene from the live values),
            show_scenes (r json), show_cues / show_keys (rw json, set =
            replace all; cue {time, scene, fade?, label?}, key {lane, time,
            value, interp?})
dmx_matrix gains 'show' ({params, services, scenes, lanes}).

2026-10-15: Plancia (gaia plancia/GAIA_PLANCIA_INTEGRATION.md, channel 1b).
Groups carry an alias (rig_a = front, rig_b = back, heads = mh) and a kind;
new groups are created at runtime by dmx_patch/group_logic:
  dmx_group_add     w  {group, kind: chase|level, profile?, port_id? |
                        universe?, count?, start?, alias?}
  dmx_group_remove  w  group name or alias (built-in groups refused)
Every rig gets dmx_<key>_level (0-1, the Plancia /dmx/group fader): key =
a / b for the two built-in rigs, the group name for created ones. Created
chase rigs get the full dmx_<group>_* set like a/b; level rigs get
dmx_<group>_level, _fan, _patch_enable. dmx_fixture_add/update/remove also
accept the Plancia shape: string id (stored as uid), universe (1-based),
group alias. dmx_matrix 'rigs' gains the created rigs, 'fixtures.groups'
gains alias/kind.
Also the raw Plancia fixture {id, type, name, group, universe, address, x, y,
enabled}: type/ch are dropped, wall/speaker (no DMX) are skipped, and a group
that does not exist yet is created from the type (par/bar -> chase rig,
blinder/haze -> level rig; fixture_logic.PLANCIA_TYPES) in dmx_fixture_add and
dmx_fixtures.

2026-10-16: fixture CATALOG (dmx_patch/catalog_logic, GAIA_INTERFACE
"TD/Win-PD, 19"). Models = what a light is (kind chase|level|heads, DMX
roles in order, footprint), types = the stage taxonomy Plancia defines
(type -> group, kind, default model). The group profile tables are derived
from the models. All JSON:
  dmx_models        r   [{model, kind, channels: [roles], footprint,
                          complete, manufacturer, source, notes, (heads:)
                          pan_range, tilt_range, defaults}]
  dmx_model_add     w   {model, kind, channels: [roles] | "r g b" | N,
                          footprint?: N, manufacturer?, notes?, ...}
  dmx_model_update  w   {model, <any field>} (kind fixed while in use)
  dmx_model_remove  w   model name (refused while in use)
  dmx_types         rw  [{type, label, group, kind, model, source}];
                        set = replace the whole taxonomy. A type naming a
                        model not in the catalog creates it when it carries
                        channels or footprint.
  dmx_type_set      w   {type, label?, group, kind?, model?} (upsert)
  dmx_type_remove   w   type
A Plancia fixture may carry `model` (= profile); without it the type's
model is used. dmx_matrix gains 'catalog' ({params, models, types, kinds:
{kind: {roles, groups}}, type_kinds, sources}).

2026-10-16: address planning (dmx_patch/conflict_logic, GAIA_INTERFACE
"TD/Win-PD, 20"): occupancy per universe, conflicts by kind (duplicate /
shared / overlap), suggestions, check before writing, resolve. All JSON:
  dmx_universe_map          r  {universes: [{port_id, universe, label,
                                online, used: [{id, uid, name, group,
                                profile, start, end, conflict}], free:
                                [[a, b]], free_channels, conflicts}],
                                unassigned: [...]}
  dmx_patch_conflicts       r  [{port_id, universe, kind, start, end,
                                fixtures: [...]}]
  dmx_patch_check           w  [fixture, ...] or {request_id?, fixtures}:
                                evaluates WITHOUT writing ->
  dmx_patch_check_result    r  {request_id, ts, results: [{index, ref,
                                status, group, profile, footprint, port_id,
                                universe, start, end, conflicts,
                                suggestion, update_of, message}]}
  dmx_patch_resolve         w  {request_id?, apply?, include_shared?,
                                remove_duplicates?} ->
  dmx_patch_resolve_result  r  {request_id, ts, applied, actions,
                                unresolved}
dmx_fixture_add / dmx_fixture_update / dmx_fixtures accept universe "auto"
and address "auto" (first free place for the footprint), and
dmx_fixture_add / update accept on_conflict: accept (default, as before:
written, flagged in dmx_patch_report) | reject (error with the suggestion
in last_error) | auto (moved to the suggestion).

2026-10-16: groups come from Plancia (GAIA_INTERFACE "TD/Win-PD, 21"):
  dmx_groups          rw  [{group, kind: chase|level|heads|none, label?,
                          bind?: rig_a|rig_b|heads}]; get = [{group (the
                          Plancia name), td_group, kind, label, builtin,
                          fixtures, source}]; set = align TD to the list
                          (dmx_patch/group_logic.set_groups) ->
  dmx_groups_result   r   {ts, created, bound, updated, removed, kept,
                          ignored}
  dmx_groups_strict   service (bool): on = TD never creates a group from a
                          fixture or a type; an undefined group is an error.
                          Off by default until Plancia sends dmx_groups.
  dmx_patch_optimize  w   {request_id?, apply?, mode?: keep|fill, align?}
                          pack the patch without holes (conflict_logic.
                          optimize) ->
  dmx_patch_optimize_result  r  {request_id, ts, applied, mode, align,
                          moves, unresolved, before, after, spacing_waste}
                          Also computed by itself (preview, request_id
                          "auto") every time dmx_fixtures replaces the
                          whole patch: the proposal is there when Plancia
                          reads the status after sending its stage.

2026-10-16: selective moving heads (moving_heads/head_programmer,
GAIA_INTERFACE "TD/Win-PD, 23"): selection by uid / named selection,
per-head state (global | manual | follow), positions per head, presets.
heads_list, heads_select, heads_program, heads_mode, heads_selections,
heads_positions, heads_position_recall / _store, heads_presets,
heads_preset_store / _recall / _remove (see PROGRAMMER_PARAMS); dmx_matrix
'heads' gains 'programmer' (order, modes, fields, selections, positions,
presets). Same commands as Plancia OSC /mh/* (plancia_in).
"""
import json
import time

RIGS = [
	('a', 'dmx_audio_chase'),
	('b', 'dmx_audio_chase_b'),
]

FLOAT_PARAMS = [
	('dmx_level', 'Level'),
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


def _fixtures():
	"""fixture_logic module of dmx_patch (resolved at call time)."""
	return _patch().op('fixture_logic').module


def _json_arg(value):
	"""Gaia UIs may send JSON as an object or as a string."""
	if isinstance(value, (bytes, str)):
		return json.loads(value)
	return value


def _patch_report():
	rep = _patch().op('patch_report')
	out = []
	for r in range(1, rep.numRows):
		out.append({
			'id': int(rep[r, 'id'].val),
			'status': rep[r, 'status'].val,
			'port_id': rep[r, 'port_id'].val,
			'universe': rep[r, 'universe'].val,
			'start': int(rep[r, 'start'].val),
			'end': int(rep[r, 'end'].val),
		})
	return out


def _groups():
	"""group_logic module of dmx_patch (resolved at call time)."""
	return _patch().op('group_logic').module


def _created_rigs():
	"""[(group, comp name, kind)] of the groups created at runtime
	(dmx_group_add) -- the built-in rigs/heads are registered separately."""
	builtin = {comp for _, comp in RIGS} | {'moving_heads'}
	return [(g['group'], g['comp'], g.get('kind') or 'chase') for g in _fixtures().groups()
		if g['comp'] not in builtin and (g.get('kind') or 'chase') in ('chase', 'level')]


def _fixture_ref(v):
	"""A fixture reference sent as id, uid or {"id": ...}."""
	v = _json_arg(v) if isinstance(v, (bytes, str)) and str(v).strip()[:1] in '{["' else v
	if isinstance(v, dict):
		v = v.get('id', v.get('uid'))
	return _fixtures().fixture_id(v)


def _refresh_registry():
	"""Re-register everything and republish the matrix a frame later (the
	groups table has to cook first); also drops names of removed groups."""
	run("op('%s').module.register_all()" % me.path, delayFrames=1)


def _conflicts():
	"""conflict_logic module of dmx_patch (resolved at call time)."""
	return _patch().op('conflict_logic').module


def _plancia_items(items, whole=False):
	"""Plancia-shape fixtures -> patch dicts; types without DMX dropped,
	universe/address 'auto' and on_conflict applied (conflict_logic: place,
	or place_all when the list is the WHOLE new patch), missing groups
	created (see _create_plancia_group). Returns (dicts, groups created) so
	a failing caller can remove them again."""
	fl = _fixtures()
	cl = _conflicts()
	out, created, staged = [], [], []
	try:
		for raw in items:
			d0, auto_u, auto_a, oc = cl.split_auto(raw)
			d = fl.from_plancia(d0, missing_ok=True)
			if d is None:
				continue
			staged.append((d, raw, auto_u, auto_a, oc))
		if whole:
			cl.place_all([(d, raw, u, a) for d, raw, u, a, _oc in staged])
		else:
			for d, raw, u, a, oc in staged:
				cl.place(d, raw, u, a, oc)
		for d, raw, _u, _a, _oc in staged:
			if d.get('group') and fl.resolve_group(d['group']) is None:
				_groups().require_defined(d['group'])
				created.append(_create_plancia_group(raw, d))
			out.append(d)
	except Exception:
		_drop_groups(created)
		raise
	return out, created


def _create_plancia_group(raw, d):
	"""Create the group a Plancia fixture names, with one fixture at its
	profile/port/address (the rigs need at least one unit). Returns the
	group name; the fixture created is the group's only row."""
	fl = _fixtures()
	group, kind = d['group'], fl.plancia_group(raw)[1]
	if kind is None:
		raise ValueError('gruppo sconosciuto: %r (tipo %r non crea gruppi)' % (group, raw.get('type')))
	return _groups().add_group(group, kind, profile=d.get('profile'), port_id=d.get('port_id'),
		count=1, start=d.get('address'))


def _drop_groups(groups):
	for g in groups:
		try:
			_groups().remove_group(g)
		except Exception as e:
			debug('rollback gruppo %s: %s' % (g, e))


def _register_fixtures(agent):
	fl = _fixtures

	def set_all(v):
		items, created = _plancia_items(_json_arg(v), whole=True)
		try:
			fl().set_all(items)
		except Exception:
			_drop_groups(created)
			raise
		try:   # the packing proposal for the stage just received
			_planning['optimize'] = dict(_conflicts().optimize(apply=False),
				request_id='auto', ts=int(time.time() * 1000))
		except Exception as e:
			debug('optimize preview:', e)
		if created:
			_refresh_registry()

	agent.register_param('dmx_fixtures', get=lambda: fl().to_list(), set=set_all)

	def add(v):
		items, created = _plancia_items([_json_arg(v)])
		if not items:
			raise ValueError('fixture senza DMX (tipo %r): ignorata' % _json_arg(v).get('type'))
		d = items[0]
		if not created:
			fl().add_fixture(d.pop('group'), **d)
			return
		# the new group already holds this fixture: give it the other fields
		fid = fl().rows(created[0])[0]['id']
		rest = {k: d[k] for k in ('name', 'x', 'y', 'enabled', 'palette', 'uid', 'unit') if k in d}
		try:
			if rest:
				fl().update_fixture(fid, **rest)
		except Exception:
			_drop_groups(created)
			raise
		_refresh_registry()

	def update(v):
		d = dict(_json_arg(v))
		fid = _fixture_ref(d.pop('id', None) if 'id' in d else d.pop('uid'))
		d.pop('type', None)  # an update never moves a fixture to its type's group
		d0, auto_u, auto_a, oc = _conflicts().split_auto(d)
		nd = fl().from_plancia(d0)
		cur = [f for f in fl().rows() if f['id'] == fid][0]
		_conflicts().place(nd, d, auto_u, auto_a, oc, cur=cur)
		fl().update_fixture(fid, **nd)

	def auto(v):
		d = fl().from_plancia(_json_arg(v))
		fl().auto_address(d['group'], int(d.get('start', 1)), d.get('port_id'))

	def group_add(v):
		d = dict(_json_arg(v))
		if 'universe' in d:
			d.setdefault('port_id', fl().port_for_universe(d.pop('universe')))
		_groups().add_group(d.pop('group'), **d)
		_refresh_registry()

	def group_remove(v):
		v = _json_arg(v) if isinstance(v, (bytes, str)) and str(v).strip()[:1] == '{' else v
		if isinstance(v, dict):
			v = v.get('group')
		g = _groups().remove_group(str(v))
		# unregister NOW: the status published right after this command
		# would otherwise poll getters of a COMP that no longer exists
		ag = op.Gaia.op('gaia_device_agent').module
		for reg in (ag._params, ag._services):
			for name in [n for n in reg if n.startswith('dmx_%s_' % g)]:
				reg.pop(name, None)
		_refresh_registry()

	agent.register_param('dmx_fixture_add', get=lambda: None, set=add)
	agent.register_param('dmx_fixture_update', get=lambda: None, set=update)
	agent.register_param('dmx_fixture_remove', get=lambda: None,
		set=lambda v: fl().remove_fixture(_fixture_ref(v)))
	agent.register_param('dmx_fixture_auto_address', get=lambda: None, set=auto)
	agent.register_param('dmx_patch_report', get=_patch_report)
	agent.register_param('dmx_group_add', get=lambda: None, set=group_add)
	agent.register_param('dmx_group_remove', get=lambda: None, set=group_remove)

	def groups_set(v):
		res = _groups().set_groups(_json_arg(v), source='plancia')
		_planning['groups'] = dict(res, ts=int(time.time() * 1000))
		ag = op.Gaia.op('gaia_device_agent').module
		for g in res['removed']:   # unregister now, like group_remove
			for reg in (ag._params, ag._services):
				for name in [n for n in reg if n.startswith('dmx_%s_' % g)]:
					reg.pop(name, None)
		_refresh_registry()

	agent.register_param('dmx_groups', get=lambda: _groups().groups_list(), set=groups_set)
	agent.register_param('dmx_groups_result', get=lambda: _planning.get('groups'))
	agent.register_service(
		'dmx_groups_strict',
		start=lambda: setattr(_patch().par, 'Groupstrict', 1),
		stop=lambda: setattr(_patch().par, 'Groupstrict', 0),
		status=lambda: bool(_groups().is_strict()))


_planning = {'check': None, 'resolve': None, 'groups': None, 'optimize': None}   # last results (read via status)


def _register_planning(agent):
	"""dmx_universe_map / dmx_patch_conflicts (r), dmx_patch_check /
	dmx_patch_resolve (w) with their *_result (r). The agent publishes the
	status right after each command, so the result is there at once."""
	cl = _conflicts

	def request(v):
		v = _json_arg(v) if isinstance(v, (bytes, str)) and str(v).strip()[:1] in '{["' else v
		if isinstance(v, list):
			return {'fixtures': v}
		return dict(v) if isinstance(v, dict) else {}

	def check(v):
		r = request(v)
		_planning['check'] = {'request_id': r.get('request_id'), 'ts': int(time.time() * 1000),
			'results': cl().check(r.get('fixtures') or [])}

	def resolve(v):
		r = request(v)
		res = cl().resolve(apply=bool(r.get('apply')), include_shared=bool(r.get('include_shared')),
			remove_duplicates=bool(r.get('remove_duplicates', True)))
		_planning['resolve'] = dict(res, request_id=r.get('request_id'), ts=int(time.time() * 1000))

	agent.register_param('dmx_universe_map', get=lambda: cl().universe_map())
	agent.register_param('dmx_patch_conflicts', get=lambda: cl().conflicts())
	agent.register_param('dmx_patch_check', get=lambda: None, set=check)
	agent.register_param('dmx_patch_check_result', get=lambda: _planning['check'])
	agent.register_param('dmx_patch_resolve', get=lambda: None, set=resolve)
	agent.register_param('dmx_patch_resolve_result', get=lambda: _planning['resolve'])

	def optimize(v):
		r = request(v)
		res = cl().optimize(apply=bool(r.get('apply')), mode=r.get('mode') or 'keep',
			align=r.get('align') or 1)
		_planning['optimize'] = dict(res, request_id=r.get('request_id'), ts=int(time.time() * 1000))

	agent.register_param('dmx_patch_optimize', get=lambda: None, set=optimize)
	agent.register_param('dmx_patch_optimize_result', get=lambda: _planning['optimize'])


def _catalog():
	"""catalog_logic module of dmx_patch (resolved at call time)."""
	return _patch().op('catalog_logic').module


def _register_catalog(agent):
	"""dmx_model* / dmx_type* params. Every change rewrites the catalog
	tables; dmx_patch/catalog_watch then republishes the matrix."""
	cat = _catalog

	def name_of(v, key):
		v = _json_arg(v) if isinstance(v, (bytes, str)) and str(v).strip()[:1] == '{' else v
		return v.get(key) if isinstance(v, dict) else v

	agent.register_param('dmx_models', get=lambda: cat().models())
	agent.register_param('dmx_model_add', get=lambda: None,
		set=lambda v: cat().add_model(_json_arg(v), source='plancia'))
	agent.register_param('dmx_model_update', get=lambda: None,
		set=lambda v: cat().update_model(_json_arg(v), source='plancia'))
	agent.register_param('dmx_model_remove', get=lambda: None,
		set=lambda v: cat().remove_model(name_of(v, 'model')))
	agent.register_param('dmx_types', get=lambda: cat().types(),
		set=lambda v: cat().set_types(_json_arg(v), source='plancia'))
	agent.register_param('dmx_type_set', get=lambda: None,
		set=lambda v: cat().set_type(_json_arg(v), source='plancia'))
	agent.register_param('dmx_type_remove', get=lambda: None,
		set=lambda v: cat().remove_type(name_of(v, 'type')))


def _build_catalog_matrix():
	out = _catalog().to_matrix()
	out['params'] = {
		'dmx_models': {'kind': 'param', 'type': 'json', 'access': 'r'},
		'dmx_model_add': {'kind': 'param', 'type': 'json', 'access': 'w'},
		'dmx_model_update': {'kind': 'param', 'type': 'json', 'access': 'w'},
		'dmx_model_remove': {'kind': 'param', 'type': 'str', 'access': 'w'},
		'dmx_types': {'kind': 'param', 'type': 'json', 'access': 'rw'},
		'dmx_type_set': {'kind': 'param', 'type': 'json', 'access': 'w'},
		'dmx_type_remove': {'kind': 'param', 'type': 'str', 'access': 'w'},
	}
	return out


def _show():
	return me.parent().parent().op('show')


def _show_logic():
	return _show().op('show_logic').module


SHOW_SERVICES = [
	('show_play', 'bool', 'Play'),
	('show_loop', 'bool', 'Loop'),
	('show_active', 'bool', 'Active'),
]


def _register_show(agent):
	sl = _show_logic
	for name, kind, par_name in SHOW_SERVICES:
		agent.register_service(
			name,
			start=lambda pn=par_name: setattr(_show().par, pn, 1),
			stop=lambda pn=par_name: setattr(_show().par, pn, 0),
			status=lambda pn=par_name: bool(_show().par[pn].eval()))
	agent.register_service('show_rewind', start=lambda: _show().par.Rewind.pulse())
	_register_value(agent, 'show_time', None, 'Time', float, comp=_show)
	_register_value(agent, 'show_length', None, 'Length', float, comp=_show)
	agent.register_param('show_status', get=lambda: str(_show().par.Status.eval()))

	def recall(v):
		sl().recall(str(v))

	agent.register_param('show_scene_recall', get=lambda: None, set=recall)
	agent.register_param('show_scene_capture', get=lambda: None, set=lambda v: sl().capture(str(v)))
	agent.register_param('show_scenes', get=lambda: sl().scenes())
	# catalog with stable id (= name) / index (= /dmx/scene i), categories,
	# per-head state, cues using it; active = last scene applied (recall/cue)
	agent.register_param('show_scene_catalog', get=lambda: sl().scene_catalog())
	agent.register_param('show_active_scene', get=lambda: sl().active_scene())
	agent.register_param('show_cues', get=lambda: sl().cues(), set=lambda v: sl().set_cues(_json_arg(v)))
	agent.register_param('show_keys', get=lambda: sl().keys(), set=lambda v: sl().set_keys(_json_arg(v)))


def _build_show_matrix():
	sl = _show_logic()
	s = _show()
	params = {
		'show_time': {'kind': 'param', 'type': 'float', 'range': _numeric_range(s.par.Time), 'default': 0.0},
		'show_length': {'kind': 'param', 'type': 'float', 'range': _numeric_range(s.par.Length), 'default': float(s.par.Length.default)},
		'show_status': {'kind': 'param', 'type': 'str', 'access': 'r'},
		'show_scene_recall': {'kind': 'param', 'type': 'enum', 'options': sl.scene_names(), 'access': 'w'},
		'show_scene_capture': {'kind': 'param', 'type': 'str', 'access': 'w'},
		'show_scenes': {'kind': 'param', 'type': 'json', 'access': 'r'},
		'show_scene_catalog': {'kind': 'param', 'type': 'json', 'access': 'r'},
		'show_active_scene': {'kind': 'param', 'type': 'json', 'access': 'r'},
		'show_cues': {'kind': 'param', 'type': 'json', 'access': 'rw'},
		'show_keys': {'kind': 'param', 'type': 'json', 'access': 'rw'},
	}
	services = {name: {'kind': 'service', 'type': kind} for name, kind, _ in SHOW_SERVICES}
	services['show_rewind'] = {'kind': 'service', 'type': 'action'}
	return {'params': params, 'services': services, 'scenes': sl.scenes(),
		'lanes': sl.automatable(), 'interps': list(sl.INTERPS)}


def _build_fixtures_matrix():
	fl = _fixtures()
	groups = []
	for g in fl.groups():
		groups.append({
			'group': g['group'],
			'alias': g.get('alias') or '',
			'kind': g.get('kind') or '',
			'profiles': [{'name': n, 'channels': fl.profile_channels(g['group'], n)}
				for n in fl.profile_names(g['group'])],
			# per-fixture palette options ('' = the rig's palette); [] = none
			'palettes': fl.palette_names(g['group']),
		})
	params = {
		'dmx_fixtures': {'kind': 'param', 'type': 'json', 'access': 'rw'},
		'dmx_fixture_add': {'kind': 'param', 'type': 'json', 'access': 'w'},
		'dmx_fixture_update': {'kind': 'param', 'type': 'json', 'access': 'w'},
		'dmx_fixture_remove': {'kind': 'param', 'type': 'int', 'access': 'w'},
		'dmx_fixture_auto_address': {'kind': 'param', 'type': 'json', 'access': 'w'},
		'dmx_patch_report': {'kind': 'param', 'type': 'json', 'access': 'r'},
		'dmx_group_add': {'kind': 'param', 'type': 'json', 'access': 'w'},
		'dmx_group_remove': {'kind': 'param', 'type': 'str', 'access': 'w'},
		'dmx_groups': {'kind': 'param', 'type': 'json', 'access': 'rw'},
		'dmx_groups_result': {'kind': 'param', 'type': 'json', 'access': 'r'},
		'dmx_universe_map': {'kind': 'param', 'type': 'json', 'access': 'r'},
		'dmx_patch_conflicts': {'kind': 'param', 'type': 'json', 'access': 'r'},
		'dmx_patch_check': {'kind': 'param', 'type': 'json', 'access': 'w'},
		'dmx_patch_check_result': {'kind': 'param', 'type': 'json', 'access': 'r'},
		'dmx_patch_resolve': {'kind': 'param', 'type': 'json', 'access': 'w'},
		'dmx_patch_resolve_result': {'kind': 'param', 'type': 'json', 'access': 'r'},
		'dmx_patch_optimize': {'kind': 'param', 'type': 'json', 'access': 'w'},
		'dmx_patch_optimize_result': {'kind': 'param', 'type': 'json', 'access': 'r'},
	}
	return {'params': params, 'columns': list(fl.COLUMNS), 'groups': groups,
		'group_kinds': list(_groups().KINDS),
		'groups_strict': bool(_groups().is_strict()),
		'bind_targets': list(_groups().PROTECTED),
		'services': {'dmx_groups_strict': {'kind': 'service', 'type': 'bool'}},
		'planning': {'auto': 'auto', 'on_conflict': list(_conflicts().ON_CONFLICT),
			'conflict_kinds': ['duplicate', 'shared', 'overlap'],
			'optimize_modes': list(_conflicts().OPTIMIZE_MODES)}}


LEVEL_RIG_FLOATS = [('level', 'Level'), ('fan', 'Fan')]


def _build_level_rig_matrix(group, comp_name):
	rig = _rig(comp_name)
	prefix = 'dmx_%s_' % group
	params = {}
	for suffix, par_name in LEVEL_RIG_FLOATS:
		par = rig.par[par_name]
		params[prefix + suffix] = {'kind': 'param', 'type': 'float',
			'range': _numeric_range(par), 'default': float(par.default)}
	services = {prefix + 'patch_enable': {'kind': 'service', 'type': 'bool'}}
	return {'kind': 'level', 'params': params, 'services': services}


# Moving heads (/project1/moving_heads): 'heads_*', one group per device.
HEADS_FLOAT_PARAMS = [
	('heads_pan', 'Pan'),
	('heads_tilt', 'Tilt'),
	('heads_speed', 'Speed'),
	('heads_dimmer', 'Dimmer'),
	('heads_level', 'Level'),      # group level (universe_build), Plancia /dmx/group/mh
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


# PTZ (/project1/ptz): aim of the moving heads from the XY pad or the
# mediapipe pose (Gaia channel 7). Effective while heads_control = ptz.
PTZ_FLOAT_PARAMS = [
	('ptz_pad_x', 'Padu'),
	('ptz_pad_y', 'Padv'),
	('ptz_smooth', 'Smooth'),
	('ptz_deadzone', 'Deadzone'),
	('ptz_min_visibility', 'Visibility'),
	('ptz_lost_timeout', 'Losttimeout'),
	('ptz_pan_center', 'Pancenter'),
	('ptz_pan_span', 'Panspan'),
	('ptz_tilt_center', 'Tiltcenter'),
	('ptz_tilt_span', 'Tiltspan'),
]

PTZ_INT_PARAMS = [
	('ptz_person', 'Person'),
]

PTZ_MENU_PARAMS = [
	('ptz_mode', 'Mode'),          # pad | mocap
	('ptz_landmark', 'Landmark'),  # body_center | nose | shoulders | left/right_wrist | left/right_index
	('ptz_lost', 'Lost'),          # hold | home
	('ptz_sender', 'Sender'),      # mocap sender device_id ('' = any)
]

PTZ_SERVICES = [
	('ptz_mirror', 'bool', 'Mirror'),
	('ptz_simulate', 'bool', 'Simulate'),
	('ptz_invert_pan', 'bool', 'Invertpan'),
	('ptz_invert_tilt', 'bool', 'Inverttilt'),
	('ptz_home', 'action', 'Home'),
]


def _ptz():
	return me.parent().parent().op('ptz')


def _build_ptz_matrix():
	p = _ptz()
	params = {}
	for name, par_name in PTZ_FLOAT_PARAMS:
		par = p.par[par_name]
		params[name] = {'kind': 'param', 'type': 'float', 'range': _numeric_range(par), 'default': float(par.default)}
	for name, par_name in PTZ_INT_PARAMS:
		par = p.par[par_name]
		params[name] = {'kind': 'param', 'type': 'int', 'range': _numeric_range(par), 'default': int(par.default)}
	for name, par_name in PTZ_MENU_PARAMS:
		par = p.par[par_name]
		params[name] = {'kind': 'param', 'type': 'enum', 'options': list(par.menuNames), 'default': str(par.default)}
	params['ptz_preset'] = {'kind': 'param', 'type': 'int', 'range': [1, 8], 'default': 1}
	services = {name: {'kind': 'service', 'type': kind} for name, kind, _ in PTZ_SERVICES}
	services['ptz_store_preset'] = {'kind': 'service', 'type': 'action'}
	return {'params': params, 'services': services}


def _register_ptz(agent):
	for name, par_name in PTZ_FLOAT_PARAMS:
		_register_value(agent, name, None, par_name, float, comp=_ptz)
	for name, par_name in PTZ_INT_PARAMS:
		_register_value(agent, name, None, par_name, int, comp=_ptz)
	for name, par_name in PTZ_MENU_PARAMS:
		if name == 'ptz_sender':
			# free text allowed ('' = any sender), not only the menu entries
			_register_value(agent, name, None, par_name, str, comp=_ptz)
		else:
			_register_menu_on(agent, name, _ptz, par_name)
	for name, kind, par_name in PTZ_SERVICES:
		if kind == 'action':
			agent.register_service(name, start=lambda pn=par_name: _ptz().par[pn].pulse())
		else:
			agent.register_service(
				name,
				start=lambda pn=par_name: setattr(_ptz().par, pn, 1),
				stop=lambda pn=par_name: setattr(_ptz().par, pn, 0),
				status=lambda pn=par_name: bool(_ptz().par[pn].eval()))

	def recall(value):
		_ptz().par.Presetslot = int(value)
		_ptz().par.Recallpreset.pulse()
	agent.register_param('ptz_preset', get=lambda: int(_ptz().par.Presetslot.eval()), set=recall)
	agent.register_service('ptz_store_preset', start=lambda: _ptz().par.Storepreset.pulse())


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
	for name, access in PROGRAMMER_PARAMS:
		params[name] = {'kind': 'param', 'type': 'json', 'access': access}
	hp = _programmer()
	return {'params': params, 'services': services,
		'programmer': {
			'order': [{'unit': x['unit'], 'key': x['key'], 'uid': x['uid'], 'name': x['name']} for x in hp.heads()],
			'modes': list(hp.MODES), 'fields': list(hp.FIELDS),
			'selections': hp.selections(),
			'positions': [{'index': x['index'], 'position': x['position'], 'label': x['label']} for x in hp.positions()],
			'presets': [{'index': x['index'], 'preset': x['preset'], 'label': x['label']} for x in hp.presets()],
			'plancia_gobos': list(hp.PLANCIA_GOBOS)}}


# Per-head programmer (moving_heads/head_programmer, GAIA_INTERFACE
# "TD/Win-PD, 23"): selective control of the heads, same as Plancia /mh/*.
PROGRAMMER_PARAMS = [
	('heads_list', 'r'),            # [{unit, key, uid, id, name, profile, selected, mode, pan...}]
	('heads_select', 'w'),          # {all|clear: 1} | {heads|add|remove: [refs]} | {set: name} | {mask: [0/1]}
	('heads_program', 'w'),         # {<field>: value, ..., mode?, heads?: [refs]} -> selected (or heads)
	('heads_mode', 'w'),            # {mode: global|manual|follow, heads?: [refs]}
	('heads_selections', 'rw'),     # [{selection, label, heads: [keys]}]; set = replace
	('heads_positions', 'rw'),      # [{index, position, label, heads: {key|*: [pan, tilt]}}]; set = replace
	('heads_position_recall', 'w'), # index or name (or {position, heads?})
	('heads_position_store', 'w'),  # {position, label?} from the selected heads
	('heads_presets', 'r'),         # [{index, preset, label, heads: {key: {fields}}}]
	('heads_preset_store', 'w'),    # {preset, label?} from the selected heads
	('heads_preset_recall', 'w'),   # index or name (or {preset, heads?})
	('heads_preset_remove', 'w'),   # index or name
	('heads_preset_rename', 'w'),   # {preset: index|name, to, label?}
	('heads_position_remove', 'w'), # index or name
	('heads_position_rename', 'w'), # {position: index|name, to, label?}
	('heads_last_result', 'r'),     # {seq, ts, source osc|gaia, action, target, ok, message, heads}
]


def _programmer():
	return _heads().op('head_programmer').module


def _register_programmer(agent):
	hp = _programmer

	def arg(v):
		return _json_arg(v) if isinstance(v, (bytes, str)) and str(v).strip()[:1] in '{["' else v

	def heads_of(d):
		refs = d.get('heads')
		if refs is None:
			return None
		keys = [hp().resolve(r) for r in refs]
		if None in keys:
			raise ValueError('teste non trovate: %s' % [r for r, k in zip(refs, keys) if k is None])
		return keys

	def program(v):
		d = dict(arg(v))
		keys = heads_of(d)
		d.pop('heads', None)
		mode = d.pop('mode', None)
		if mode == 'global':
			hp().set_mode('global', keys)
			return
		hp().program(d, keys, mode=mode)

	def mode(v):
		d = arg(v)
		d = d if isinstance(d, dict) else {'mode': d}
		hp().set_mode(str(d.get('mode')), heads_of(d))

	def recall(kind):
		def fn(v):
			d = arg(v)
			d = d if isinstance(d, dict) else {kind: d}
			f = hp().recall_position if kind == 'position' else hp().recall_preset
			f(d.get(kind), heads_of(d))
		return fn

	def rename(kind):
		def fn(v):
			d = dict(arg(v))
			f = hp().rename_position if kind == 'position' else hp().rename_preset
			return f(d.get(kind), d.get('to'), d.get('label'))
		return fn

	def recorded(name, fn, lists=False):
		"""Setter that records its outcome (heads_last_result) and, for
		list changes, republishes the matrix (programmer.presets/positions)."""
		def wrapper(v):
			try:
				out = fn(v)
			except Exception as e:
				hp().record('gaia', name, v, False, e, hp().selection())
				raise
			hp().record('gaia', name, v, True, out if isinstance(out, str) else 'ok', hp().selection())
			if lists:
				run("op('%s').module.publish_matrix()" % me.path, delayFrames=1)
		return wrapper

	def reg(name, fn, lists=False):
		agent.register_param(name, get=lambda: None, set=recorded(name, fn, lists))

	agent.register_param('heads_list', get=lambda: hp().heads_list())
	reg('heads_select', lambda v: hp().select(arg(v)))
	reg('heads_program', program)
	reg('heads_mode', mode)
	agent.register_param('heads_selections', get=lambda: hp().selections(),
		set=recorded('heads_selections', lambda v: hp().set_selections(arg(v)), True))
	agent.register_param('heads_positions', get=lambda: hp().positions(),
		set=recorded('heads_positions', lambda v: hp().set_positions(arg(v)), True))
	reg('heads_position_recall', recall('position'))
	reg('heads_position_store',
		lambda v: hp().store_position(dict(arg(v)).get('position'), dict(arg(v)).get('label', '')), True)
	reg('heads_position_remove', lambda v: hp().remove_position(arg(v)), True)
	reg('heads_position_rename', rename('position'), True)
	agent.register_param('heads_presets', get=lambda: hp().presets())
	reg('heads_preset_store',
		lambda v: hp().store_preset(dict(arg(v)).get('preset'), dict(arg(v)).get('label', '')), True)
	reg('heads_preset_recall', recall('preset'))
	reg('heads_preset_remove', lambda v: hp().remove_preset(arg(v)), True)
	reg('heads_preset_rename', rename('preset'), True)
	agent.register_param('heads_last_result', get=lambda: hp().last_result())


def heads_lists_changed():
	"""Presets/positions changed outside Gaia (Plancia OSC): republish the
	status (heads_presets, heads_positions, heads_last_result) and the
	matrix now, instead of at the next heartbeat."""
	agent = op.Gaia.op('gaia_device_agent').module
	agent._publish_status()
	publish_matrix()


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


def _build_rigs_matrix():
	"""Built-in rigs keyed a / b (names dmx_<letter>_*), created rigs keyed
	by group (dmx_<group>_*). Chase-rig entries keep the unprefixed names,
	as before; level rigs list their full names."""
	out = {letter: _build_matrix_for_rig(rig_name) for letter, rig_name in RIGS}
	for group, comp_name, kind in _created_rigs():
		if _rig(comp_name) is None:
			continue
		out[group] = _build_matrix_for_rig(comp_name) if kind == 'chase' \
			else _build_level_rig_matrix(group, comp_name)
	return out


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
		'rigs': _build_rigs_matrix(),
		'audio': _build_audio_matrix(),
		'patch': _build_patch_matrix(),
		'heads': _build_heads_matrix(),
		'ptz': _build_ptz_matrix(),
		'fixtures': _build_fixtures_matrix(),
		'catalog': _build_catalog_matrix(),
		'show': _build_show_matrix(),
		'ts': int(time.time() * 1000),
	}
	topic = 'gaia/devices/%s/%s_matrix' % (device_id, family.lower())
	dat.publish(topic, json.dumps(payload).encode('utf-8'), retain=True)
	print('[DMX Services] Matrix published to %s' % topic)
	return True


def _register_level_rig(agent, group, rig_name):
	prefix = 'dmx_%s_' % group
	for suffix, par_name in LEVEL_RIG_FLOATS:
		_register_value(agent, prefix + suffix, rig_name, par_name, float)
	agent.register_service(
		prefix + 'patch_enable',
		start=lambda rn=rig_name: setattr(_rig(rn).par, 'Patchenable', 1),
		stop=lambda rn=rig_name: setattr(_rig(rn).par, 'Patchenable', 0),
		status=lambda rn=rig_name: bool(_rig(rn).par.Patchenable.eval()))


def _drop_stale_rig_names(agent, live_keys):
	"""Unregister dmx_<key>_* of rigs that no longer exist (removed groups)."""
	fixed = ('dmx_fixture', 'dmx_fixtures', 'dmx_patch_report', 'dmx_group_',
		'dmx_scan', 'dmx_output', 'dmx_blackout', 'dmx_model', 'dmx_type',
		'dmx_patch_', 'dmx_universe_', 'dmx_groups')
	for reg in (agent._params, agent._services):
		for name in list(reg):
			if not name.startswith('dmx_') or name.startswith(fixed):
				continue
			if not any(name.startswith('dmx_%s_' % k) for k in live_keys):
				reg.pop(name, None)


def register_all():
	agent = op.Gaia.op('gaia_device_agent').module

	created = [(g, c, k) for g, c, k in _created_rigs() if _rig(c) is not None]
	chase_rigs = list(RIGS) + [(g, c) for g, c, k in created if k == 'chase']
	for g, c, k in created:
		if k == 'level':
			_register_level_rig(agent, g, c)
	_drop_stale_rig_names(agent, [key for key, _ in RIGS] + [g for g, _, _ in created])

	for letter, rig_name in chase_rigs:
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

	_register_ptz(agent)
	_register_programmer(agent)
	_register_fixtures(agent)
	_register_catalog(agent)
	_register_planning(agent)
	_register_show(agent)

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
