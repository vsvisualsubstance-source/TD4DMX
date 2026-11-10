"""show_logic -- timeline engine of /project1/show (scenes, cues, automation).

Tables (siblings, file-synced tsv):
  scenes        name, label, rigs, heads, groups, audio, strobe, palette
                (category flags 0/1: which parts of the snapshot the scene
                applies)
  scene_values  scene, target, par, value   (one row per captured par)
  cues          id, time, scene, fade, label   (seconds)
  keys          id, lane, time, value, interp  (lane = '<target>.<Par>';
                interp: linear | step | smooth)

Categories of a scene snapshot (pars read from the live COMPs, so pars added
to those pages later are captured automatically):
  rigs    every rig of the patch (rig_groups(): dmx_patch groups table, target
          = group name): chase rigs (rig_a, rig_b, ledbar...) their 'DMX
          Reactive' page (colour motion, audio amount, smoothing, kick on/off)
          except the palette and the CALIBRATION pars, level rigs (haze,
          blinder...) Level / Fan
          Calibration (RIG_CALIBRATION_PARS: min/max dimmer, boost, AGC,
          min range, kick thresholds; GAIA_INTERFACE "TD/Win-PD, 69") is how
          a rig is tuned to its lights, set live or by a rig preset
          (gaia_services/rig_config): no category owns it, so scenes and
          lanes never write it. Rows of older scenes for those pars stay in
          scene_values but are ignored.
  palette Palette + the 5 Custom colours of every chase rig (GAIA_INTERFACE
          "OPS, 36": colour-only scenes). A scene saved before this category
          existed has an empty palette flag: it follows its rigs flag, so it
          still recalls the palette its rigs capture stored.
  heads   moving_heads 'Position' + 'Look' pages, ptz Mode / Padu / Padv
  heads_color  the heads WITHOUT their position (GAIA_INTERFACE "OPS, 47" /
          "TD/Win-PD, 65"): moving_heads 'Look' page (Colorfollow included)
          and the per-head fields except pan/tilt and mode, so a colour cue
          never moves a head. It shares the values of category heads (one
          row per par): a scene with heads applies them all, a scene with
          only heads_color the colour part. A head that was global at the
          capture stores '' (= back to the global look, its row untouched).
          Scenes saved before it have an empty flag = off.
  groups  Patchenable of every rig and of heads, dmx_patch Blackout
  audio   Audiobus of every chase rig (which audio source drives the rig)
  strobe  dmx_patch Strobe / Stroberate (the general strobe, /dmx/strobe)
  A rig created later is captured from the next capture on; scenes saved
  before it leave it alone (they have no rows for it).

Per-head state (category heads; see GAIA_INTERFACE "TD/Win-PD, 25"): besides
the global look of moving_heads, a scene stores every head of the
programmer (moving_heads/head_programmer) as target 'head:<key>' (key = the
head's uid) with par 'mode' (global | manual | follow) and one row per
field (pan, tilt, dimmer, red, green, blue, white, color, gobo, zoom,
focus, strobe: its EFFECTIVE value at capture, so every field can fade).
Applying it: a global head is released (back to the global look), a
manual/follow head gets its fields and mode. Crossfade: numbers
interpolate; a head going manual/follow changes mode at once, a head going
global is released only at the END of the fade (no pan/tilt jump halfway).
Scenes captured before this have no head rows: they leave the per-head
state alone.

Per-fixture audio (category rigs; GAIA_INTERFACE "TD/Win-PD, 44"): every
light of a chase rig is stored as target 'fx:<key>' (key = its uid, else
'id:<fixture id>') with par 'audio' (full | off | bass | mid | high | kick)
and 'audio_gain' (0..2), the patch columns of dmx_patch/fixture_logic.
Crossfade: the mode switches at half fade, the gain interpolates in 0.05
steps (each step is one write of the file-synced patch table). Scenes
captured before this have no fixture rows: they leave the lights alone.

State at time t is STATELESS (scrub / seek / loop always land right):
  cue = last cue with time <= t (none -> the timeline does not drive);
  scenes layer: every par holds the value of the LAST cue up to t whose
  scene sets it (a scene without a category leaves it as the earlier cues
  set it: colour from one cue, movement from the next);
  crossfade from that layered state over cue.fade seconds: numbers
  interpolate, menus/toggles/strings switch at half fade; then every
  automation lane whose first..last key spans t overrides its par.

Apply: a par is written only when ITS target value changes (or on a forced
apply: Active on, seek, recall). A live tweak (TD UI, Gaia) therefore holds
until the timeline moves that par again.
"""
import json

TARGETS = {
	'rig_a': 'dmx_audio_chase',
	'rig_b': 'dmx_audio_chase_b',
	'heads': 'moving_heads',
	'ptz': 'ptz',
	'patch': 'dmx_patch',
}
CATEGORIES = ['rigs', 'heads', 'groups', 'audio', 'strobe', 'palette', 'heads_color']
CATEGORY_LABELS = {'rigs': 'Look dei rig', 'heads': 'Teste mobili', 'groups': 'Accensioni gruppi',
	'audio': 'Sorgente audio', 'strobe': 'Strobo generale', 'palette': 'Palette',
	'heads_color': 'Colore teste'}
# per-head fields of heads_color: everything but the position
HEAD_POS_FIELDS = ('pan', 'tilt', 'mode')
PALETTE_PARS = ['Palette'] + ['Custompalette%d%s' % (i, c) for i in range(1, 6) for c in 'rgb']
# tuning of a chase rig to its lights: out of every scene category (see the
# module docstring); rig_config (gaia_services) reads it from here
RIG_CALIBRATION_PARS = ['Mindimmer', 'Maxdimmer', 'Dimmerboost', 'Dimmergamma', 'Agcrelease',
	'Minrange', 'Kickthresh', 'Kickboost', 'Kickdecay', 'Kickcooldown', 'Kicksmooth']
INTERPS = ['linear', 'smooth', 'step']

# only: space-separated groups the scene is limited to ('' = all), see
# scene_groups (GAIA_INTERFACE "OPS, 44" point 4 / "TD/Win-PD, 60")
SCENE_COLS = ['name', 'label'] + CATEGORIES + ['only']
VALUE_COLS = ['scene', 'target', 'par', 'value']
CUE_COLS = ['id', 'time', 'scene', 'fade', 'label', 'track']
# Cue tracks (GAIA_INTERFACE "OPS, 44" / "TD/Win-PD, 60"): one clock, cues
# grouped in tracks (track '' = MAIN_TRACK). GO / BACK, "cue n/m" of the
# status and of the show clock count the MAIN track only; every track
# composes the output the same way (see state_at).
MAIN_TRACK = 'luci'
KEY_COLS = ['id', 'lane', 'time', 'value', 'interp']

_last = {}        # (target, par) -> last value applied
_force = [False]  # next tick applies everything (seek, rewind, Active on, load)
_seeded = [False]  # False after a (re)load of this module: see tick()
_clock = {'secs': None}
_cache = {}       # memoised table reads; cleared by invalidate()
_xfade = {}       # live recall in progress: {frm, to, t0, dur} (see recall)
_active = {}      # last scene applied: see active_scene()
_cue_seen = [None]   # (Active, cue index) of the last tick, for the cue -> active scene


def _memo(fn):
	"""Cache a table-derived result until invalidate(): tick() runs every
	frame and the tables change rarely (edits here, or show_tables_watch)."""
	def wrapper(*args):
		k = (fn.__name__,) + args
		if k not in _cache:
			_cache[k] = fn(*args)
		return _cache[k]
	wrapper.__name__ = fn.__name__
	wrapper.__doc__ = fn.__doc__
	return wrapper


def invalidate(force=True):
	"""Tables or COMP pages changed: drop the caches; force = re-apply
	everything (cues/keys changed). A scene capture or flag change does not
	force: it must not undo live moves (Plancia heads, TD tweaks)."""
	_cache.clear()
	if force:
		_force[0] = True


# ---------------------------------------------------------------- basics

def _show():
	return me.parent()


def target_comp(target):
	name = TARGETS.get(target) or dict((g, c) for g, c, k in rig_groups()).get(target)
	return _show().parent().op(name) if name else None


@_memo
def rig_groups():
	"""[(group, comp name, kind)] of every rig of the patch (dmx_patch groups
	table, kind chase | level): rig_a / rig_b, ledbar, haze, blinder and any
	group created later. The group name is the scene target. Heads are
	not here (category heads)."""
	fx = _show().parent().op(TARGETS['patch'] + '/fixture_logic')
	if fx is None:
		return [('rig_a', TARGETS['rig_a'], 'chase'), ('rig_b', TARGETS['rig_b'], 'chase')]
	return [(g['group'], g['comp'], g['kind']) for g in fx.module.groups()
		if g['kind'] in ('chase', 'level') and g['comp']]


def _table(name, cols):
	t = _show().op(name)
	if t.numRows == 0 or t[0, 0] is None or t[0, 0].val != cols[0]:
		t.clear()
		t.appendRow(cols)
	elif t.numCols < len(cols):
		# a column added later (e.g. category strobe): old rows get '' (= on)
		for c in cols:
			if t[0, c] is None:
				t.appendCol([c])
	return t


def _rows(name, cols):
	t = _table(name, cols)
	return [{c: (t[r, c].val if t[r, c] is not None else '') for c in cols} for r in range(1, t.numRows)]


def _f(v, d=0.0):
	try:
		return float(v)
	except (TypeError, ValueError):
		return d


def _i(v, d=0):
	try:
		return int(float(v))
	except (TypeError, ValueError):
		return d


def _next_id(name, cols):
	return max([0] + [_i(r['id']) for r in _rows(name, cols)]) + 1


def _row_index(name, cols, key, val):
	t = _table(name, cols)
	for r in range(1, t.numRows):
		if t[r, key].val == str(val):
			return r
	return None


# ---------------------------------------------------------------- par lists

def _page_pars(target, pages, exclude=()):
	c = target_comp(target)
	if c is None:
		return []
	return [(target, p.name) for p in c.customPars
		if p.page.name in pages and p.style not in ('Pulse', 'Header', 'Momentary')
		and not p.readOnly and p.name not in exclude]


@_memo
def category_pars(cat):
	rigs = rig_groups()
	if cat == 'rigs':
		out = []
		for g, c, kind in rigs:
			if kind == 'chase':
				out += _page_pars(g, ('DMX Reactive',), ['Audiobus'] + PALETTE_PARS + RIG_CALIBRATION_PARS)
			else:
				out += [(g, n) for n in ('Level', 'Fan') if _par(g, n) is not None]
		return out
	if cat == 'heads':
		return _page_pars('heads', ('Position', 'Look')) + \
			[('ptz', n) for n in ('Mode', 'Padu', 'Padv') if target_comp('ptz') is not None]
	if cat == 'heads_color':
		return _page_pars('heads', ('Look',))
	if cat == 'groups':
		return [(g, 'Patchenable') for g, c, k in rigs] + \
			[('heads', 'Patchenable'), ('patch', 'Blackout')]
	if cat == 'audio':
		return [(g, 'Audiobus') for g, c, k in rigs if k == 'chase']
	if cat == 'strobe':
		return [('patch', n) for n in ('Strobe', 'Stroberate') if _par('patch', n) is not None]
	if cat == 'palette':
		return [(g, n) for g, c, k in rigs if k == 'chase' for n in PALETTE_PARS
			if _par(g, n) is not None]
	return []


@_memo
def _category_of():
	"""{(target, par): owning category}; heads_color pars belong to heads
	(see _in_scene)."""
	m = {}
	for cat in CATEGORIES:
		for k in category_pars(cat):
			m.setdefault(k, cat)
	return m


@_memo
def _head_color_pars():
	return set(category_pars('heads_color'))


def _is_head_color(k):
	"""A key of category heads_color: Look pars, head fields but position."""
	if _is_head(k[0]):
		return k[1] not in HEAD_POS_FIELDS
	return k in _head_color_pars()


def _in_scene(sc, k, owner):
	"""Key k (owning category `owner`) is applied by scene sc."""
	if sc.get(owner, 0):
		return True
	return owner == 'heads' and sc.get('heads_color', 0) and _is_head_color(k)


def _par(target, name):
	c = target_comp(target)
	return getattr(c.par, name) if c is not None and hasattr(c.par, name) else None


# ---------------------------------------------------------------- per-head state

HEAD_PREFIX = 'head:'


def _is_head(target):
	return target.startswith(HEAD_PREFIX)


def _hp():
	c = target_comp('heads')
	dat = c.op('head_programmer') if c is not None else None
	return dat.module if dat is not None else None


def _head_rows(color_only=False):
	"""[(target, par, value)] of every head's current state, for capture.
	color_only (category heads_color): no mode/pan/tilt, and '' for the
	fields of a global head (it follows the global look again)."""
	hp = _hp()
	if hp is None:
		return []
	out = []
	for h in hp.heads():
		t = HEAD_PREFIX + h['key']
		e = hp.effective(h['key'])
		if not color_only:
			out.append((t, 'mode', e['mode']))
		for f in hp.FIELDS:
			if color_only and f in HEAD_POS_FIELDS:
				continue
			v = '' if color_only and e['mode'] == 'global' else round(float(e[f]), 6)
			out.append((t, f, v))
	return out


# ---------------------------------------------------------------- per-fixture audio

FX_PREFIX = 'fx:'
FX_PARS = ('audio', 'audio_gain')
FX_GAIN_STEP = 0.05


def _is_fx(target):
	return target.startswith(FX_PREFIX)


def _fl():
	c = target_comp('patch')
	dat = c.op('fixture_logic') if c is not None else None
	return dat.module if dat is not None else None


def _fx_key(f):
	return f['uid'] or 'id:%d' % f['id']


def _fx_lights():
	"""{fx key: fixture row} of every light of a chase rig."""
	fl = _fl()
	if fl is None:
		return {}
	chase = {g for g, c, k in rig_groups() if k == 'chase'}
	return {_fx_key(f): f for f in fl.rows() if f['group'] in chase}


def _fx_rows():
	"""[(target, par, value)] of every chase light's audio, for capture."""
	out = []
	for key, f in _fx_lights().items():
		t = FX_PREFIX + key
		out.append((t, 'audio', f['audio'] or 'full'))
		out.append((t, 'audio_gain', 1.0 if f['audio_gain'] == '' else float(f['audio_gain'])))
	return out


def _apply_fx(changed):
	"""Write the fx keys of `changed` to the patch, one call per light."""
	fl = _fl()
	if fl is None:
		return
	lights = _fx_lights()
	per = {}
	for (t, n), v in changed.items():
		per.setdefault(t, {})[n] = v
	for t, vals in per.items():
		f = lights.get(t[len(FX_PREFIX):])
		if f is None:
			continue
		try:
			fl.set_audio([f['id']], mode=vals.get('audio'), gain=vals.get('audio_gain'))
		except Exception as e:
			debug('show apply %s: %s' % (t, e))


def _current(k):
	"""Live value of a scene key (a par, a head or a light field), None if
	gone."""
	if _is_fx(k[0]):
		f = _fx_lights().get(k[0][len(FX_PREFIX):])
		if f is None:
			return None
		if k[1] == 'audio':
			return f['audio'] or 'full'
		return 1.0 if f['audio_gain'] == '' else float(f['audio_gain'])
	if _is_head(k[0]):
		hp = _hp()
		key = k[0][len(HEAD_PREFIX):]
		if hp is None or key not in hp.keys_by_unit().values():
			return None
		v = hp.effective(key)[k[1]]
		return v if k[1] == 'mode' else float(v)
	p = _par(*k)
	return _read(p) if p is not None else None


def _blend(k, a, v, x):
	"""Value of key k at fade position x (0..1) from a to v: numbers
	interpolate, other values switch at half fade; a head's mode switches at
	once, except back to global, which waits for the end of the fade."""
	if x >= 1.0 or a is None:
		return v
	if k[1] == 'mode' and _is_head(k[0]):
		return a if v == 'global' else v
	if isinstance(v, float) and isinstance(a, float):
		return a + (v - a) * x
	return a if x < 0.5 else v


def _apply_heads(changed, state, force):
	"""Write the head keys of `changed` ({(target, field): value}) to the
	programmer, one call per head. A head whose mode in `state` is global is
	released (only when its mode changed, or on a forced apply)."""
	hp = _hp()
	if hp is None:
		return
	known = set(hp.keys_by_unit().values())
	per = {}
	for (t, f), v in changed.items():
		per.setdefault(t, {})[f] = v
	for t, fields in per.items():
		key = t[len(HEAD_PREFIX):]
		if key not in known:
			continue
		mode = state.get((t, 'mode'))
		try:
			if mode == 'global':
				if force or 'mode' in fields:
					hp.set_mode('global', [key])
				continue
			vals = {f: v for f, v in fields.items() if f != 'mode'}
			if mode is None and key not in hp.state() and all(v is None for v in vals.values()):
				continue   # heads_color: a global head stays global (no row, no position change)
			hp.program(vals, [key], mode=mode if mode in ('manual', 'follow') else None)
		except Exception as e:
			debug('show apply %s: %s' % (t, e))


def _is_number(p):
	return p.style in ('Float', 'Int', 'RGB', 'RGBA', 'XY', 'XYZ', 'UV', 'UVW', 'WH')


def _read(p):
	if p.style == 'Toggle':
		return 1 if p.eval() else 0
	if _is_number(p):
		return float(p.eval())
	return str(p.eval())


@_memo
def automatable():
	"""'target.Par' of every numeric/toggle par a lane can drive."""
	out = []
	for cat in CATEGORIES:
		for t, n in category_pars(cat):
			p = _par(t, n)
			if p is not None and (_is_number(p) or p.style == 'Toggle'):
				out.append('%s.%s' % (t, n))
	return out


def par_range(lane):
	t, n = lane.split('.', 1)
	p = _par(t, n)
	if p is None:
		return 0.0, 1.0
	if p.style == 'Toggle':
		return 0.0, 1.0
	lo = p.min if p.clampMin else p.normMin
	hi = p.max if p.clampMax else p.normMax
	return float(lo), float(hi) if hi != lo else float(lo) + 1.0


# ---------------------------------------------------------------- scenes

@_memo
def scenes():
	out = []
	for r in _rows('scenes', SCENE_COLS):
		d = {'name': r['name'], 'label': r['label'] or r['name']}
		for c in CATEGORIES:
			d[c] = 1 if _i(r[c], 1) else 0
		if r['heads_color'] == '':   # saved before category heads_color
			d['heads_color'] = 0
		if r['palette'] == '':   # saved before category palette: as its rigs
			d['palette'] = d['rigs']
		d['only'] = r['only'].split()
		out.append(d)
	return out


def scene_groups():
	"""Groups a scene can be limited to (scene 'only'): every rig group of
	the patch, plus 'heads'."""
	return [g for g, c, k in rig_groups()] + ['heads']


def _clean_only(only):
	"""Validated group list for 'only' (Plancia aliases accepted); [] = all."""
	if not only:
		return []
	only = only.split() if isinstance(only, str) else list(only)
	fx = _show().parent().op(TARGETS['patch'] + '/fixture_logic')
	known = scene_groups()
	out = []
	for g in only:
		name = 'heads' if str(g) in ('heads', 'mh') else (fx.module.resolve_group(g) if fx else str(g))
		if name not in known:
			raise ValueError('only: gruppo %r sconosciuto (%s)' % (g, ', '.join(known)))
		if name not in out:
			out.append(name)
	return out


def _key_group(k):
	"""Group a scene key belongs to: the rig group, 'heads', or None for
	the global pars (patch Blackout / Strobe)."""
	t = k[0]
	if _is_head(t) or t in ('heads', 'ptz'):
		return 'heads'
	if _is_fx(t):
		f = _fx_lights().get(t[len(FX_PREFIX):])
		return f['group'] if f else None
	if t == 'patch':
		return None
	return t


def scene_names():
	return [s['name'] for s in scenes()]


@_memo
def scene_values(name):
	"""{(target, par): value} of a scene, only its enabled categories."""
	sc = [s for s in scenes() if s['name'] == name]
	if not sc:
		return {}
	sc = sc[0]
	cat = _category_of()
	only = set(sc.get('only') or [])
	out = {}
	for r in _rows('scene_values', VALUE_COLS):
		if r['scene'] != name:
			continue
		k = (r['target'], r['par'])
		if only and _key_group(k) not in only:
			continue   # a scene limited to some groups leaves the others as they are
		if _is_head(k[0]):
			if _in_scene(sc, k, 'heads'):
				# '' = the head was global at a heads_color capture: back to global
				out[k] = r['value'] if k[1] == 'mode' else _f(r['value'], None)
			continue
		if _is_fx(k[0]):
			if sc.get('rigs', 0) and k[1] in FX_PARS:
				out[k] = r['value'] if k[1] == 'audio' else _f(r['value'], 1.0)
			continue
		if not _in_scene(sc, k, cat.get(k, '')):
			continue
		p = _par(*k)
		if p is None:
			continue
		v = r['value']
		out[k] = _i(v) if p.style == 'Toggle' else (_f(v) if _is_number(p) else v)
	# heads scenes stored before the colour follow ("TD/Win-PD, 64") carry
	# their colour but no Colorfollow: a saved colour = fixed colour
	cf = ('heads', 'Colorfollow')
	if (sc.get('heads', 0) or sc.get('heads_color', 0)) and cf not in out and _par(*cf) is not None \
			and (not only or 'heads' in only) and any(_key_group(k) == 'heads' for k in out):
		out[cf] = ''
	return out


def capture(name, label=None, categories=None, only=None):
	"""Store the current live values of every category into scene `name`
	(created if new, enabled = the captured categories; existing: values
	replaced, category flags kept). categories: only those (e.g. ['heads']);
	the scene's other values stay. only: limit the scene to these groups
	(rig groups / 'heads'): only their values are captured and replaced,
	and the scene's 'only' is set to them (None = as it is, [] = all)."""
	name = str(name).strip()
	if not name:
		raise ValueError('nome scena vuoto')
	cats = list(CATEGORIES) if categories is None else [c for c in CATEGORIES if c in categories]
	if categories is not None and not cats:
		raise ValueError('categorie %r sconosciute (%s)' % (categories, ', '.join(CATEGORIES)))
	grp = None if only is None else set(_clean_only(only))
	keep = lambda k: not grp or _key_group(k) in grp
	owned = _category_of()
	st = _table('scenes', SCENE_COLS)
	if _row_index('scenes', SCENE_COLS, 'name', name) is None:
		# a new scene applies what it captured: capture(..., ['heads']) = 'only heads'
		# by column name: a column added later sits at the end of the table
		row = dict(name=name, label=label or name, only=' '.join(sorted(grp)) if grp else '',
			**{c: 1 if c in cats else 0 for c in CATEGORIES})
		st.appendRow([row.get(st[0, i].val, '') for i in range(st.numCols)])
	else:
		r0 = _row_index('scenes', SCENE_COLS, 'name', name)
		if label:
			st[r0, 'label'] = label
		if grp is not None:
			st[r0, 'only'] = ' '.join(sorted(grp))
	vt = _table('scene_values', VALUE_COLS)
	for r in range(vt.numRows - 1, 0, -1):
		if vt[r, 'scene'].val != name:
			continue
		k = (vt[r, 'target'].val, vt[r, 'par'].val)
		cat = 'heads' if _is_head(k[0]) else 'rigs' if _is_fx(k[0]) else owned.get(k)
		if (categories is None or cat in cats or 'heads_color' in cats and cat == 'heads'
				and _is_head_color(k)) and keep(k):
			vt.deleteRow(r)
	done = set()
	for cat in cats:
		for t, n in category_pars(cat):
			p = _par(t, n)
			if p is not None and keep((t, n)) and (t, n) not in done:
				done.add((t, n))
				v = _read(p)
				vt.appendRow([name, t, n, round(v, 6) if isinstance(v, float) else v])
	if 'heads' in cats:
		for t, n, v in _head_rows():
			if keep((t, n)):
				vt.appendRow([name, t, n, v])
	elif 'heads_color' in cats:
		for t, n, v in _head_rows(color_only=True):
			if keep((t, n)):
				vt.appendRow([name, t, n, v])
	if 'rigs' in cats:
		for t, n, v in _fx_rows():
			if keep((t, n)):
				vt.appendRow([name, t, n, v])
	invalidate(force=False)
	return name


def set_scene_flags(name, **flags):
	r = _row_index('scenes', SCENE_COLS, 'name', name)
	if r is None:
		raise ValueError('scena %r non esiste' % name)
	t = _table('scenes', SCENE_COLS)
	for c in CATEGORIES:
		if c in flags:
			t[r, c] = 1 if _i(flags[c], 1) else 0
	if 'label' in flags:
		t[r, 'label'] = flags['label']
	if 'only' in flags:   # [] / None = every group
		t[r, 'only'] = ' '.join(_clean_only(flags['only']))
	invalidate(force=False)


def rename_scene(name, new_name, label=None):
	"""Rename a scene everywhere: its row, its values, the cues using it."""
	new_name = str(new_name or '').strip()
	r = _row_index('scenes', SCENE_COLS, 'name', name)
	if r is None:
		raise ValueError('scena %r non esiste' % name)
	if not new_name:
		raise ValueError('nome scena vuoto')
	if new_name != name and new_name in scene_names():
		raise ValueError("scena %r esiste gia'" % new_name)
	st = _table('scenes', SCENE_COLS)
	if st[r, 'label'].val in ('', name):
		st[r, 'label'] = new_name
	st[r, 'name'] = new_name
	if label:
		st[r, 'label'] = label
	vt = _table('scene_values', VALUE_COLS)
	for i in range(1, vt.numRows):
		if vt[i, 'scene'].val == name:
			vt[i, 'scene'] = new_name
	ct = _table('cues', CUE_COLS)
	for i in range(1, ct.numRows):
		if ct[i, 'scene'].val == name:
			ct[i, 'scene'] = new_name
	if _active.get('scene') == name:
		_active['scene'] = new_name
	invalidate(force=False)
	return new_name


def delete_scene(name):
	if any(c['scene'] == name for c in cues()):
		raise ValueError('la scena %r e\' usata da delle cue: cancella prima le cue' % name)
	r = _row_index('scenes', SCENE_COLS, 'name', name)
	if r is not None:
		_table('scenes', SCENE_COLS).deleteRow(r)
	vt = _table('scene_values', VALUE_COLS)
	for r in range(vt.numRows - 1, 0, -1):
		if vt[r, 'scene'].val == name:
			vt.deleteRow(r)
	invalidate(force=False)


def recall(name, fade=0.0):
	"""Apply a scene now (live use), crossfading over `fade` seconds from the
	current live values (same rules as a cue: numbers interpolate, toggles/
	menus/strings switch at half fade; tick() advances it). The timeline,
	if Active, takes over again only for pars whose target changes
	afterwards."""
	vals = scene_values(name)
	if not vals:
		raise ValueError('scena %r vuota o inesistente' % name)
	fade = max(0.0, _f(fade))
	_set_active(name, 'recall', fade)
	_xfade.clear()
	if fade <= 0:
		_apply(vals, force=True)
		return
	frm = {}
	for k in vals:
		v = _current(k)
		if v is not None:
			frm[k] = v
	_xfade.update(frm=frm, to=dict(vals), t0=absTime.seconds, dur=fade)


def _xfade_step():
	"""Advance a live recall crossfade (called every frame by tick)."""
	if not _xfade:
		return
	x = min(1.0, (absTime.seconds - _xfade['t0']) / _xfade['dur'])
	state = {k: _blend(k, _xfade['frm'].get(k), v, x) for k, v in _xfade['to'].items()}
	_apply(state, force=True)
	if x >= 1.0:
		_xfade.clear()


def goto_cue(step):
	"""Jump to the next (step=1) or previous (step=-1) cue of the timeline
	from the current Time. With the timeline not Active the cue's scene is
	recalled live with the cue's fade. Returns the cue."""
	p = _show().par
	idx, _cue, cs = cue_at(float(p.Time.eval()))   # main track only ("OPS, 44")
	if not cs:
		raise ValueError('nessun cue nella traccia %s' % MAIN_TRACK)
	j = max(0, min(len(cs) - 1, idx + int(step)))
	return _jump_to(cs[j])


def goto_cue_number(n):
	"""Jump to cue number n (1-based, main track order), same rules as
	goto_cue. Returns the cue."""
	cs = track_cues()
	n = int(n)
	if not 1 <= n <= len(cs):
		raise ValueError('cue %d non esiste (%d cue)' % (n, len(cs)))
	return _jump_to(cs[n - 1])


def _jump_to(c):
	p = _show().par
	p.Time = c['time']
	force_apply()
	if not p.Active.eval():
		recall(c['scene'], c['fade'])
	return c


# ---------------------------------------------------------------- show clock

def clock_state():
	"""State of this timeline for gaia_client/show_clock (master)."""
	p = _show().par
	t = float(p.Time.eval())
	idx, cue, cs = cue_at(t)
	return {
		'timeline': 'show',
		'name': _meta('name', ''),
		'bpm': _meta('bpm'),
		'playing': bool(p.Play.eval()),
		'pos': round(t, 3),
		'rate': 1.0,
		'length': float(p.Length.eval()),
		'loop': bool(p.Loop.eval()),
		'active': bool(p.Active.eval()),
		'cue': {
			'index': idx + 1,
			'count': len(cs),
			'label': (cue or {}).get('label', '') or '',
			'scene': (cue or {}).get('scene', '') or '',
			'time': (cue or {}).get('time', 0.0),
			'track': MAIN_TRACK,   # index/count = main track only ("OPS, 44")
		},
	}


def clock_command(action, value=None):
	"""Transport command from the show clock (Plancia, other devices):
	play [0|1], pause, toggle, stop, seek <s>, go, back, cue <n>."""
	p = _show().par
	if action == 'play':
		on = True if value in (None, '') else _f(value) >= 0.5
		p.Play = on
		return 'play' if on else 'pause'
	if action == 'pause':
		p.Play = False
		return 'pause'
	if action == 'toggle':
		p.Play = not p.Play.eval()
		return 'play' if p.Play.eval() else 'pause'
	if action == 'stop':
		p.Play = False
		p.Time = 0
		force_apply()
		return 'stop'
	if action == 'seek':
		t = max(0.0, min(float(p.Length.eval()), _f(value)))
		p.Time = t
		force_apply()
		return 'seek %.2fs' % t
	if action in ('go', 'back'):
		c = goto_cue(1 if action == 'go' else -1)
		return 'cue %s @ %.1fs' % (c.get('label') or c['id'], c['time'])
	if action == 'cue':
		c = goto_cue_number(_i(value))
		return 'cue %s @ %.1fs' % (c.get('label') or c['id'], c['time'])
	raise ValueError('azione %r sconosciuta' % action)


# ---------------------------------------------------------------- cues

@_memo
def cues():
	out = []
	for r in _rows('cues', CUE_COLS):
		out.append({'id': _i(r['id']), 'time': _f(r['time']), 'scene': r['scene'],
			'fade': max(0.0, _f(r['fade'])), 'label': r['label'],
			'track': r['track'].strip() or MAIN_TRACK})
	return sorted(out, key=lambda c: (c['time'], c['id']))


def track_cues(track=MAIN_TRACK):
	"""Cues of one track (time order); None = every cue."""
	return [c for c in cues() if track is None or c['track'] == track]


def tracks():
	"""Track names: the main one first, then the others by their first cue."""
	out = [MAIN_TRACK]
	for c in cues():
		if c['track'] not in out:
			out.append(c['track'])
	return out


def _clean_track(v):
	s = str(v or '').strip().replace('\t', ' ')
	return s or MAIN_TRACK


def _check_cue(d):
	if 'track' in d:
		d['track'] = _clean_track(d['track'])
	# scene '' = a MARKER: a named point of the timeline that changes nothing
	if d.get('scene') and d['scene'] not in scene_names():
		raise ValueError('scena %r non esiste' % d['scene'])
	if 'time' in d:
		d['time'] = round(max(0.0, _f(d['time'])), 3)
	if 'fade' in d:
		d['fade'] = round(max(0.0, _f(d['fade'])), 3)
	return d


def _cue_row(d):
	"""Table row of a cue: the main track is stored as '' (older files)."""
	return [('' if d.get('track', MAIN_TRACK) == MAIN_TRACK else d['track']) if c == 'track' else d.get(c, '')
		for c in CUE_COLS]


def add_cue(time, scene, fade=2.0, label='', track=MAIN_TRACK):
	d = _check_cue({'id': _next_id('cues', CUE_COLS), 'time': time, 'scene': scene, 'fade': fade, 'label': label,
		'track': track})
	_table('cues', CUE_COLS).appendRow(_cue_row(d))
	invalidate()
	return d['id']


def update_cue(cid, **fields):
	r = _row_index('cues', CUE_COLS, 'id', int(cid))
	if r is None:
		raise ValueError('cue %s non trovata' % cid)
	fields.pop('id', None)
	d = _check_cue(dict(fields))
	t = _table('cues', CUE_COLS)
	for k, v in d.items():
		if k in CUE_COLS:
			t[r, k] = '' if k == 'track' and v == MAIN_TRACK else v
	invalidate()


def delete_cue(cid):
	r = _row_index('cues', CUE_COLS, 'id', int(cid))
	if r is not None:
		_table('cues', CUE_COLS).deleteRow(r)
		invalidate()


# ---------------------------------------------------------------- automation

@_memo
def keys():
	out = []
	for r in _rows('keys', KEY_COLS):
		out.append({'id': _i(r['id']), 'lane': r['lane'], 'time': _f(r['time']),
			'value': _f(r['value']), 'interp': r['interp'] if r['interp'] in INTERPS else 'linear'})
	return sorted(out, key=lambda k: (k['lane'], k['time'], k['id']))


@_memo
def lanes():
	"""{lane: [keys sorted by time]} in first-appearance order."""
	out = {}
	for k in keys():
		out.setdefault(k['lane'], []).append(k)
	return out


def _check_key(d):
	if 'lane' in d and d['lane'] not in automatable():
		raise ValueError('parametro %r non automatizzabile' % d['lane'])
	if 'time' in d:
		d['time'] = round(max(0.0, _f(d['time'])), 3)
	if 'value' in d:
		d['value'] = round(_f(d['value']), 6)
	if 'interp' in d and d['interp'] not in INTERPS:
		raise ValueError('interp %r (usa %s)' % (d['interp'], ', '.join(INTERPS)))
	return d


def add_key(lane, time, value=None, interp='linear'):
	if value is None:
		t, n = lane.split('.', 1)
		p = _par(t, n)
		value = _read(p) if p is not None else 0.0
	d = _check_key({'id': _next_id('keys', KEY_COLS), 'lane': lane, 'time': time, 'value': value, 'interp': interp})
	_table('keys', KEY_COLS).appendRow([d[c] for c in KEY_COLS])
	invalidate()
	return d['id']


def update_key(kid, **fields):
	r = _row_index('keys', KEY_COLS, 'id', int(kid))
	if r is None:
		raise ValueError('keyframe %s non trovato' % kid)
	fields.pop('id', None)
	d = _check_key(dict(fields))
	t = _table('keys', KEY_COLS)
	for k, v in d.items():
		if k in KEY_COLS:
			t[r, k] = v
	invalidate()


def delete_key(kid):
	r = _row_index('keys', KEY_COLS, 'id', int(kid))
	if r is not None:
		_table('keys', KEY_COLS).deleteRow(r)
		invalidate()


def _lane_value(ks, t):
	if t < ks[0]['time'] or t > ks[-1]['time']:
		return None
	for a, b in zip(ks, ks[1:]):
		if a['time'] <= t <= b['time']:
			span = b['time'] - a['time']
			x = 0.0 if span <= 0 else (t - a['time']) / span
			if a['interp'] == 'step':
				x = 0.0 if t < b['time'] else 1.0
			elif a['interp'] == 'smooth':
				x = x * x * (3 - 2 * x)
			return a['value'] + (b['value'] - a['value']) * x
	return ks[-1]['value']


# ---------------------------------------------------------------- state

def cue_at(t, track=MAIN_TRACK):
	"""(index, cue, cues) of the cue active at time t on `track` (default
	the main one; None = any track), or (-1, None, cues)."""
	cs = track_cues(track)
	idx = -1
	for i, c in enumerate(cs):
		if c['time'] <= t:
			idx = i
	return idx, (cs[idx] if idx >= 0 else None), cs


@_memo
def _layered(idx):
	"""{(target, par): value} the cues 0..idx leave behind, each scene
	over the earlier ones (only its enabled categories)."""
	out = {}
	for c in cues()[:idx + 1]:
		if c['scene']:
			out.update(scene_values(c['scene']))
	return out


@_memo
def _history():
	"""{(target, par): [(time, fade, value)]} -- every cue (any track) that
	sets the key, in timeline order."""
	out = {}
	# timeline cues and the expanded steps of the chase track, in time order
	# (a step at the same instant as a cue comes after it)
	evs = [(c['time'], 0, c['fade'], c['scene']) for c in cues() if c['scene']]
	evs += [(s['time'], 1, s['fade'], s['scene']) for s in chase_steps()]
	evs.sort(key=lambda e: (e[0], e[1]))
	for tc, _o, fade, scene in evs:
		for k, v in scene_values(scene).items():
			out.setdefault(k, []).append((tc, fade, v))
	return {k: ([h[0] for h in hist], hist) for k, hist in out.items()}


def state_at(t):
	"""{(target, par): value} the timeline wants at time t. PER KEY: the
	last cue up to t that sets it (any track) gives the value, crossfading
	over ITS fade from the value of the cue before it on that key. So a cue
	on another track that does not touch a key never cuts its fade (with a
	single track this equals the old 'layered + crossfade of the last cue'
	except that such fades now finish instead of snapping)."""
	import bisect
	out = {}
	for k, (times, hist) in _history().items():
		i = bisect.bisect_right(times, t) - 1
		if i < 0:
			continue
		tc, fade, v = hist[i]
		prev = hist[i - 1][2] if i > 0 else None
		x = 1.0 if fade <= 0 else max(0.0, min(1.0, (t - tc) / fade))
		out[k] = _blend(k, prev, v, x)
	for lane, ks in lanes().items():
		v = _lane_value(ks, t)
		if v is None:
			continue
		tgt, n = lane.split('.', 1)
		p = _par(tgt, n)
		if p is None:
			continue
		out[(tgt, n)] = (1 if v >= 0.5 else 0) if p.style == 'Toggle' else v
	return out


def _apply(state, force=False):
	heads, lights = {}, {}
	for k, v in state.items():
		if _is_fx(k[0]) and k[1] == 'audio_gain' and isinstance(v, float):
			v = round(round(v / FX_GAIN_STEP) * FX_GAIN_STEP, 3)   # one patch write per step
		old = _last.get(k)
		if not force and old is not None and (old == v or (
				isinstance(v, float) and isinstance(old, float) and abs(old - v) < 1e-6)):
			continue
		_last[k] = v
		if _is_head(k[0]):
			heads[k] = v
			continue
		if _is_fx(k[0]):
			lights[k] = v
			continue
		p = _par(*k)
		if p is None:
			continue
		try:
			if p.style == 'Toggle':
				p.val = bool(v)
			elif p.isMenu and p.style == 'Menu' and str(v) not in p.menuNames:
				continue   # e.g. a port/source that no longer exists
			elif p.style == 'Int':
				p.val = int(round(float(v)))
			else:
				p.val = v
		except Exception as e:
			debug('show apply %s.%s=%r: %s' % (k[0], k[1], v, e))
	if heads:
		_apply_heads(heads, state, force)
	if lights:
		_apply_fx(lights)


# ---------------------------------------------------------------- catalog / active

def _set_active(name, source, fade=0.0, cue=None):
	import time
	if not name:
		return   # a marker cue changes nothing
	_active.clear()
	_active.update(scene=name, index=(scene_names().index(name) if name in scene_names() else -1),
		source=source, fade=float(fade or 0.0), cue=cue, ts=int(time.time() * 1000))


def active_scene():
	"""The last scene applied: {scene, index, source 'recall' (live: TD,
	Plancia /dmx/scene, Gaia) | 'cue' (timeline), fade, cue id, ts epoch
	ms}; None before the first one. Live tweaks after it do not clear it."""
	return dict(_active) if _active else None


def scene_catalog():
	"""[{id, index, label, categories, per_head, per_fixture, cues}] -- id =
	the scene name (unique, stable until renamed); index = position in the
	list, the number /dmx/scene takes (it shifts when a scene before it is
	deleted). per_fixture = it holds the audio of every chase light."""
	vrows = _rows('scene_values', VALUE_COLS)
	heads = {r['scene'] for r in vrows if _is_head(r['target'])}
	lights = {r['scene'] for r in vrows if _is_fx(r['target'])}
	used = {}
	for c in cues():
		used.setdefault(c['scene'], []).append(c['id'])
	return [{'id': s['name'], 'index': i, 'label': s['label'],
		'categories': [c for c in CATEGORIES if s[c]], 'per_head': s['name'] in heads,
		'per_fixture': s['name'] in lights, 'only': s.get('only') or [],
		'cues': used.get(s['name'], []), 'preview': scene_preview(s['name'])}
		for i, s in enumerate(scenes())]


def scene_preview(name):
	"""The colours a scene sets, for UIs to paint scene buttons and cues:
	{<chase rig>: {'palette', 'colors': [[r, g, b] 0-1]} (rig_a, rig_b,
	ledbar...), <level rig>: {'level'} (haze, blinder),
	'heads': [{'uid', 'name', 'rgb', 'source', 'dimmer'}]} -- only what the
	scene's enabled categories hold. Head rgb = the beam colour before the
	dimmer (dmx_patch/catalog_logic.beam_color), as dmx_output reports it.
	GAIA_INTERFACE "OPS, 2" / "TD/Win-PD, 37"."""
	v = scene_values(name)
	out = {}
	for t, c, kind in rig_groups():
		if kind == 'level':
			if (t, 'Level') in v:
				out[t] = {'level': round(float(v[(t, 'Level')]), 3)}
			continue
		pal = v.get((t, 'Palette'))
		comp = target_comp(t)
		if pal is None or comp is None:
			continue
		if pal == 'Custom':
			cols = []
			for i in range(1, 6):
				rgb = []
				for c in 'rgb':
					k = (t, 'Custompalette%d%s' % (i, c))
					x = v[k] if k in v else _current(k)
					rgb.append(round(float(x or 0.0), 3))
				cols.append(rgb)
		else:
			gen = comp.op('dmx_generator_callbacks1')
			pals = getattr(gen.module, 'ALL_PALETTES', {}) if gen else {}
			cols = [[round(c / 255.0, 3) for c in rgb] for rgb in pals.get(pal, [])]
			if len(cols) > 1 and cols[-1] == cols[0]:
				cols = cols[:-1]
		out[t] = {'palette': pal, 'colors': cols}
	hp = _hp()
	if hp is not None and any(_is_head(k[0]) for k in v):
		cat = target_comp('patch').op('catalog_logic').module
		heads = []
		for h in hp.heads():
			t = HEAD_PREFIX + h['key']
			if (t, 'mode') not in v and (t, 'dimmer') not in v:
				continue
			look = {'red': 'Colorr', 'green': 'Colorg', 'blue': 'Colorb', 'white': 'White',
				'color': 'Colorwheel', 'dimmer': 'Dimmer'}
			# None = global head of a heads_color scene: the scene's (or live) look
			f = lambda n: float((v.get((t, n)) if v.get((t, n)) is not None else
				v.get(('heads', look[n]), _current(('heads', look[n])))) or 0.0)
			m = cat.model(h['profile']) or {}
			chans = set(m.get('channels') or [])
			# only the model's own roles: beam_color adds white/amber/... when present
			vals = {c: f(c) * 255.0 for c in ('red', 'green', 'blue', 'white') if c in chans}
			if 'color' in chans:
				vals['color'] = f('color')
			rgb, src = cat.beam_color(m, vals) if m else (None, None)
			heads.append({'uid': h['uid'], 'name': h['name'], 'rgb': rgb, 'source': src,
				'dimmer': round(f('dimmer'), 3)})
		out['heads'] = heads
	return out


# ---------------------------------------------------------------- clock

def tick():
	"""Execute DAT onFrameStart: advance the clock, apply the state."""
	show = _show()
	now = absTime.seconds
	dt = 0.0 if _clock['secs'] is None else max(0.0, min(0.5, now - _clock['secs']))
	_clock['secs'] = now
	p = show.par
	t = float(p.Time.eval())
	length = max(0.1, float(p.Length.eval()))
	if p.Play.eval():
		t += dt
		if t >= length:
			if p.Loop.eval():
				# no forced apply at the wrap: only what the timeline changes is
				# written, so live moves (Plancia /mh/*, TD tweaks) hold
				t = t % length
			else:
				t = length
				p.Play = False
		p.Time = round(t, 4)
	if p.Active.eval():
		st = state_at(t)
		if not _seeded[0]:
			# first tick after a (re)load of this module (project save, file
			# sync): the outputs already hold the timeline's look, so take it
			# as applied instead of re-writing it over live changes (a save
			# used to snap the heads back from where Plancia had moved them)
			_last.update(st)
			_seeded[0] = True
		else:
			_apply(st, force=_force[0])
		_force[0] = False
		idx, cue, _cs = cue_at(t, None)   # last scene applied: any track
		if cue is not None and _cue_seen[0] != (True, idx):
			_set_active(cue['scene'], 'cue', cue['fade'], cue['id'])
		_cue_seen[0] = (True, idx)
	else:
		_cue_seen[0] = None
	_live_chase_step()
	_xfade_step()
	status = status_text(t)
	if p.Status.eval() != status:
		p.Status = status


def force_apply():
	_force[0] = True


def status_text(t=None):
	show = _show()
	t = float(show.par.Time.eval()) if t is None else t
	idx, cue, cs = cue_at(t)
	m, s = divmod(t, 60)
	head = '%s %02d:%05.2f' % ('PLAY' if show.par.Play.eval() else 'STOP', m, s)
	if not show.par.Active.eval():
		return head + '  |  timeline NON attiva (live)'
	if cue is None:   # main track only: GO/BACK count these ("OPS, 44")
		return head + '  |  prima della prima cue'
	if not cue['scene']:
		return '%s  |  cue %d/%d  %s  (marker)' % (head, idx + 1, len(cs), cue['label'] or '')
	x = 1.0 if cue['fade'] <= 0 else min(1.0, (t - cue['time']) / cue['fade'])
	s = '%s  |  cue %d/%d  %s  -> %s' % (head, idx + 1, len(cs), cue['label'] or '', cue['scene'])
	if x < 1.0:
		s += '  (fade %d%%)' % int(x * 100)
	return s


# ---------------------------------------------------------------- json (Gaia)

def to_json():
	return {'cues': cues(), 'scenes': scenes(), 'keys': keys()}


def set_cues(items):
	items = json.loads(items) if isinstance(items, (str, bytes)) else items
	clean = []
	for i, it in enumerate(items):
		d = _check_cue(dict(it))
		d.setdefault('fade', 0.0)
		d.setdefault('label', '')
		d['id'] = i + 1
		if 'time' not in d or 'scene' not in d:
			raise ValueError('cue %d: servono time e scene' % (i + 1))
		clean.append(d)
	t = _table('cues', CUE_COLS)
	t.clear()
	t.appendRow(CUE_COLS)
	# rows grouped by track (main first) so the table reads track by track;
	# ids stay in timeline order
	order = {MAIN_TRACK: 0}
	for d in sorted(clean, key=lambda d: _f(d['time'])):
		order.setdefault(d.get('track', MAIN_TRACK), len(order))
	for d in sorted(clean, key=lambda d: (order[d.get('track', MAIN_TRACK)], _f(d['time']), d['id'])):
		t.appendRow(_cue_row(d))
	invalidate()


def set_keys(items):
	items = json.loads(items) if isinstance(items, (str, bytes)) else items
	clean = []
	for i, it in enumerate(items):
		d = _check_key(dict(it))
		d.setdefault('interp', 'linear')
		d['id'] = i + 1
		if 'lane' not in d or 'time' not in d or 'value' not in d:
			raise ValueError('keyframe %d: servono lane, time e value' % (i + 1))
		clean.append(d)
	t = _table('keys', KEY_COLS)
	t.clear()
	t.appendRow(KEY_COLS)
	for d in clean:
		t.appendRow([d[c] for c in KEY_COLS])
	invalidate()


# ---------------------------------------------------------------- timeline document
# Load a whole timeline designed elsewhere (Plancia), GAIA_INTERFACE
# "TD/Win-PD, 29". One document, validated as a whole: on any error nothing
# is written and the errors come back in the result.
#   {"v": 1, "name": str, "bpm": number|null, "length": s, "loop": bool,
#    "default_fade": s (2.0), "rewind": bool (false),
#    "cues": [{"time": s | "m:ss.s", "scene": id (name) | index (int, as
#              /dmx/scene) | null (marker), "fade": s, "label": str,
#              "track": str (absent = MAIN_TRACK, "TD/Win-PD, 60")}],
#    "keys": [...]   (optional: absent = TD's automation lanes untouched,
#                     [] = cleared; same rows as show_keys)}

_tl = {'seq': 0, 'last': None}


def _meta(k, d=None):
	return _show().fetch('timeline_' + k, d, search=False)


def _seconds(v):
	"""Seconds from a number or 'm:ss(.s)' / 'h:mm:ss'."""
	if isinstance(v, (int, float)):
		return float(v)
	parts = str(v).strip().split(':')
	try:
		out = 0.0
		for x in parts:
			out = out * 60 + float(x)
		return out
	except ValueError:
		raise ValueError('tempo %r non valido (secondi o m:ss)' % v)


TIMELINE_FIELDS = ('name', 'bpm', 'length', 'loop', 'cues', 'keys')


def timeline_rev(doc):
	"""Content revision of a timeline document: the same timeline has the
	same rev on every machine, whoever made it (TD or Plancia)."""
	import hashlib
	canon = {k: doc.get(k) for k in TIMELINE_FIELDS}
	if doc.get('motion') and (doc['motion'].get('cues') or doc['motion'].get('scenes')):
		canon['motion'] = doc['motion']   # only when there is one: older revs unchanged
	if doc.get('effects') and (doc['effects'].get('cues') or doc['effects'].get('effects')):
		canon['effects'] = doc['effects']
	if doc.get('chases') and (doc['chases'].get('cues') or doc['chases'].get('chases')):
		canon['chases'] = doc['chases']
	return hashlib.sha1(json.dumps(canon, sort_keys=True).encode('utf-8')).hexdigest()[:12]


def timeline():
	"""The current timeline, in the shape load_timeline() takes, plus its
	rev and who changed it last ('td' = edited in TD after the last load)."""
	p = _show().par
	doc = {'v': 1, 'name': _meta('name', ''), 'bpm': _meta('bpm'),
		'length': float(p.Length.eval()), 'loop': bool(p.Loop.eval()),
		'cues': [dict({'time': c['time'], 'scene': c['scene'] or None, 'fade': c['fade'], 'label': c['label']},
			# track only off the main one: older timelines keep their rev
			**({} if c['track'] == MAIN_TRACK else {'track': c['track']})) for c in cues()],
		'keys': [{k: x[k] for k in ('lane', 'time', 'value', 'interp')} for x in keys()],
		'motion': motion_track(), 'effects': effects_track(), 'chases': chases_track()}
	doc['rev'] = timeline_rev(doc)
	doc['source'] = _meta('source', 'td') if doc['rev'] == _meta('loaded_rev') else 'td'
	return doc


def load_timeline(doc, source='gaia'):
	"""Validate and load a timeline document (see above). doc['dry_run']:
	validate only. Returns the result (also timeline_result())."""
	import time
	doc = json.loads(doc) if isinstance(doc, (str, bytes)) else dict(doc or {})
	errors, warnings, clean = [], [], []
	names = scene_names()
	dfade = _f(doc.get('default_fade', 2.0), 2.0)
	missing = str(doc.get('missing_scenes') or 'error')
	if missing not in ('error', 'marker'):
		errors.append('missing_scenes %r (error | marker)' % missing)
		missing = 'error'

	def no_scene(i, what):
		"""A cue whose scene TD does not have: error, or a marker that keeps
		the label (missing_scenes: marker), so a Plancia timeline can be
		loaded before its scenes exist in TD."""
		if missing == 'marker':
			warnings.append('cue %d: %s -> marker' % (i, what))
			return ''
		errors.append('cue %d: %s' % (i, what))
		return None
	items = doc.get('cues')
	if not isinstance(items, list):
		errors.append('cues: serve una lista')
		items = []
	for i, it in enumerate(items, 1):
		if not isinstance(it, dict):
			errors.append('cue %d: serve un oggetto' % i)
			continue
		try:
			t = _seconds(it.get('time'))
			if t < 0:
				raise ValueError('tempo negativo')
		except (ValueError, TypeError) as e:
			errors.append('cue %d: %s' % (i, e))
			continue
		sc = it.get('scene')
		if sc is None or sc == '':
			sc = ''
		elif isinstance(sc, bool):
			errors.append('cue %d: scena %r non valida' % (i, sc))
			continue
		elif isinstance(sc, (int, float)):
			if not (float(sc).is_integer() and 0 <= int(sc) < len(names)):
				sc = no_scene(i, 'scena indice %r non esiste (%d scene)' % (sc, len(names)))
				if sc is None:
					continue
			else:
				sc = names[int(sc)]
		elif str(sc) not in names:
			sc = no_scene(i, 'scena %r non esiste' % sc)
			if sc is None:
				continue
		fade = _f(it.get('fade', dfade), -1)
		if fade < 0:
			errors.append('cue %d: fade %r non valido' % (i, it.get('fade')))
			continue
		clean.append({'time': round(t, 3), 'scene': str(sc), 'fade': round(fade, 3),
			'label': str(it.get('label') or it.get('name') or '').replace('\t', ' '),
			'track': _clean_track(it.get('track'))})
	clean.sort(key=lambda c: c['time'])
	end = max([c['time'] + c['fade'] for c in clean] + [0.0])
	length = doc.get('length')
	if length is None:
		length = max(float(_show().par.Length.eval()), end, 1.0)
		if end > float(_show().par.Length.eval()):
			warnings.append('length non data: portata a %.3f s (fine dell\'ultima cue)' % length)
	else:
		length = _f(length, -1)
		if length <= 0:
			errors.append('length %r non valida' % doc.get('length'))
		elif clean and clean[-1]['time'] > length:
			errors.append('length %.3f s: c\'e\' una cue a %.3f s' % (length, clean[-1]['time']))
	# legal but almost never meant: two cues at one instant (only the later
	# one ever shows), and with loop a cue at the very end -- the clock wraps
	# to 0 before reaching it (tick: t % length), so it never fires
	# (on different tracks the same instant is normal: no warning)
	for i in range(1, len(clean)):
		for j in range(i):
			if clean[i]['time'] == clean[j]['time'] and clean[i]['track'] == clean[j]['track']:
				warnings.append('cue %d: stesso tempo della cue %d (%.3f s, traccia %s)'
					% (i + 1, j + 1, clean[i]['time'], clean[i]['track']))
				break
	loop = bool(doc['loop']) if 'loop' in doc else bool(_show().par.Loop.eval())
	if loop and length > 0:
		for i, c in enumerate(clean, 1):
			if c['time'] >= length:
				warnings.append('cue %d a %.3f s = fine della timeline: con loop non scatta mai'
					% (i, c['time']))
	keys_in = doc.get('keys')
	if keys_in is not None:
		if not isinstance(keys_in, list):
			errors.append('keys: serve una lista')
		else:
			for i, k in enumerate(keys_in, 1):
				try:
					_check_key(dict(k))
				except (ValueError, TypeError) as e:
					errors.append('key %d: %s' % (i, e))
	bpm = doc.get('bpm')
	if bpm is not None and _f(bpm, -1) <= 0:
		errors.append('bpm %r non valido' % bpm)
	motion = None
	if 'motion' in doc:   # absent = motion track untouched, null / {} = cleared
		motion, merr = check_motion(doc.get('motion'))
		errors.extend(merr)
	effects = None
	if 'effects' in doc:   # same rule as motion
		effects, eerr = check_effects(doc.get('effects'))
		errors.extend(eerr)
	chases = None
	if 'chases' in doc:   # same rule; missing scenes follow missing_scenes
		chases, cerr, cwarn = check_chases(doc.get('chases'), missing)
		errors.extend(cerr)
		warnings.extend(cwarn)
	dry = bool(doc.get('dry_run'))
	name = str(doc.get('name') or '').strip()
	origin = str(doc.get('source') or source)
	prev_rev = timeline()['rev']
	base = doc.get('base_rev')
	conflict = base is not None and str(base) != prev_rev and not doc.get('force')
	if conflict:
		errors.append('conflitto: la timeline di TD è cambiata (rev %s, il documento parte da %s); '
			'rileggere show_timeline e rifare, oppure force: true' % (prev_rev, base))
	ok = not errors
	if ok and not dry:
		set_cues(clean)
		if keys_in is not None:
			set_keys(keys_in)
		p = _show().par
		p.Length = round(float(length), 3)
		if 'loop' in doc:
			p.Loop = bool(doc['loop'])
		if doc.get('rewind'):
			p.Time = 0
		_show().store('timeline_name', name)
		_show().store('timeline_bpm', None if bpm is None else float(bpm))
		if motion is not None:
			_show().store('timeline_motion', motion)
		if effects is not None:
			_show().store('timeline_effects', effects)
		if chases is not None:
			_show().store('timeline_chases', chases)
		invalidate()   # chase steps depend on the chases, Length and BPM just stored
		_show().store('timeline_source', origin)
		_show().store('timeline_loaded_rev', timeline_rev(timeline()))
		force_apply()
	_tl['seq'] += 1
	_tl['last'] = {'seq': _tl['seq'], 'ts': int(time.time() * 1000), 'source': origin, 'ok': ok,
		'conflict': conflict, 'previous_rev': prev_rev, 'rev': timeline()['rev'],
		'dry_run': dry, 'loaded': ok and not dry, 'name': name, 'cues': len(clean),
		'markers': sum(1 for c in clean if not c['scene']), 'length': round(float(length), 3) if ok else None,
		'errors': errors, 'warnings': warnings}
	return _tl['last']


def timeline_result():
	return _tl['last']


# ---------------------------------------------------------------- motion track
# Head motion on the timeline (GAIA_INTERFACE "OPS, 41" / "TD/Win-PD, 57"),
# like the Plancia's MOVIMENTO track (layout.headTimeline): its own cues,
# separate from the scene cues, played by moving_heads/head_motion.
#   {"scenes": [motion scene, ...],                 (full Plancia scenes)
#    "cues": [{"time": s | "m:ss", "scene": <scene id> | "off", "label": str}]}
# Kept in the show COMP's storage with the other timeline meta. In the
# timeline document as "motion": absent = untouched, null or {} = cleared.

def motion_track():
	return _meta('motion') or {'scenes': [], 'cues': []}


def _motion_hm():
	c = target_comp('heads')
	m = c.op('head_motion') if c is not None else None
	return m.module if m is not None else None


def check_motion(track):
	"""Validate a motion track; returns (clean track, errors)."""
	if not track:
		return {'scenes': [], 'cues': []}, []
	errors, scenes, cues_out = [], [], []
	hm = _motion_hm()
	if not isinstance(track, dict):
		return None, ['motion: serve un oggetto {scenes, cues}']
	for i, sc in enumerate(track.get('scenes') or [], 1):
		try:
			scenes.append(hm.check_scene(sc) if hm else dict(sc))
		except (ValueError, TypeError) as e:
			errors.append('motion scena %d: %s' % (i, e))
	ids = {s['id'] for s in scenes}
	for i, c in enumerate(track.get('cues') or [], 1):
		if not isinstance(c, dict):
			errors.append('motion cue %d: serve un oggetto' % i)
			continue
		try:
			t = _seconds(c.get('time'))
		except (ValueError, TypeError) as e:
			errors.append('motion cue %d: %s' % (i, e))
			continue
		sid = str(c.get('scene') or 'off')
		if sid != 'off' and sid not in ids:
			errors.append('motion cue %d: scena %r non è in motion.scenes' % (i, sid))
			continue
		cues_out.append({'time': round(max(0.0, t), 3), 'scene': sid,
			'label': str(c.get('label') or '').replace('\t', ' ')})
	cues_out.sort(key=lambda c: c['time'])
	return {'scenes': scenes, 'cues': cues_out}, errors


def set_motion_track(track):
	clean, errors = check_motion(json.loads(track) if isinstance(track, (str, bytes)) else track)
	if errors:
		raise ValueError('; '.join(errors))
	_show().store('timeline_motion', clean)
	return clean


def motion_at(t):
	"""(cue index, scene dict | None) of the motion track at time t: the
	last cue <= t ('off' = none), -1 before the first."""
	tr = motion_track()
	idx, sid = -1, None
	for i, c in enumerate(tr.get('cues') or []):
		if c['time'] <= t:
			idx, sid = i, (None if c['scene'] == 'off' else c['scene'])
	if sid is None:
		return idx, None
	for sc in tr.get('scenes') or []:
		if sc.get('id') == sid:
			return idx, sc
	return idx, None


# ---------------------------------------------------------------- effects track
# Light effects on the timeline (GAIA_INTERFACE "OPS, 42" / "TD/Win-PD, 59"),
# played by dmx_patch/light_effects on top of the scene look:
#   {"effects": [effect, ...],                      (full effects)
#    "cues": [{"time": s | "m:ss", "effects": [<effect id>, ...], "label": str}]}
# From a cue on, exactly its effects play ([] = none) until the next cue.
# Kept in the show COMP's storage; in the timeline document as "effects":
# absent = untouched, null or {} = cleared.

def effects_track():
	return _meta('effects') or {'effects': [], 'cues': []}


def _fx_module():
	c = target_comp('patch')
	m = c.op('light_effects') if c is not None else None
	return m.module if m is not None else None


def check_effects(track):
	"""Validate an effects track; returns (clean track, errors)."""
	if not track:
		return {'effects': [], 'cues': []}, []
	if not isinstance(track, dict):
		return None, ['effects: serve un oggetto {effects, cues}']
	errors, effs, cues_out = [], [], []
	fxm = _fx_module()
	for i, e in enumerate(track.get('effects') or [], 1):
		try:
			effs.append(fxm.check_effect(e) if fxm else dict(e))
		except (ValueError, TypeError) as ex:
			errors.append('effetto %d: %s' % (i, ex))
	ids = {e['id'] for e in effs}
	for i, c in enumerate(track.get('cues') or [], 1):
		if not isinstance(c, dict):
			errors.append('effects cue %d: serve un oggetto' % i)
			continue
		try:
			t = _seconds(c.get('time'))
		except (ValueError, TypeError) as ex:
			errors.append('effects cue %d: %s' % (i, ex))
			continue
		lst = c.get('effects')
		lst = [] if lst in (None, 'off') else ([lst] if isinstance(lst, str) else list(lst))
		bad = [x for x in lst if str(x) not in ids]
		if bad:
			errors.append('effects cue %d: effetti non in effects.effects: %s' % (i, bad))
			continue
		cues_out.append({'time': round(max(0.0, t), 3), 'effects': [str(x) for x in lst],
			'label': str(c.get('label') or '').replace('\t', ' ')})
	cues_out.sort(key=lambda c: c['time'])
	return {'effects': effs, 'cues': cues_out}, errors


# Mute of the effects and chases tracks (Plancia, buttons M): the cues stay, the
# track just does not play. In memory on purpose: after a TD restart everything plays.
_muted = {'effects': False, 'chases': False}


def muted(track):
	return _muted[track]


def set_muted(track, on):
	_muted[track] = bool(on)
	invalidate(force=False)   # chase steps come out of the history, live moves stay


def effects_at(t):
	"""(cue index, [effect dicts]) of the effects track at time t."""
	if _muted['effects']:
		return -1, []
	tr = effects_track()
	idx, ids = -1, []
	for i, c in enumerate(tr.get('cues') or []):
		if c['time'] <= t:
			idx, ids = i, c['effects']
	by = {e['id']: e for e in tr.get('effects') or []}
	return idx, [by[i] for i in ids if i in by]


# ---------------------------------------------------------------- chases
# Step chases (GAIA_INTERFACE "OPS, 44" point 3 / "TD/Win-PD, 60"): a
# sequence of TD scenes, each held for a time and reached with a fade.
# Format and maths = plancia/src/63-chase.js (chaseSec, chaseOrder,
# chaseExpand; see chase_self_test):
#   chase {id, name, steps: [{scene, hold?}], hold: {value, unit: beats|s},
#          fadePct (0..100 of the step time), pingpong}
#   track {"chases": [chase...], "cues": [{"time", "chase": <id> | "off", "label"}]}
# Timeline: a chase cue plays until the next chase cue (or the end); its
# steps are expanded on the fly into virtual cues that join state_at's per
# key composition (not in the cues table, not counted by GO/BACK).
# Live: start_chase / stop_chase (Gaia dmx_chase): every step is a recall()
# of its scene with its fade, so nothing is left behind in /dmx/fade.

CHASE_MARK = '⟳'


def chase_sec(h, bpm):
	h = h or {}
	try:
		v = float(h.get('value') or 0) or 1.0
	except (TypeError, ValueError):
		v = 1.0
	return max(.05, v if h.get('unit') == 's' else v * 60.0 / (bpm if bpm and bpm > 0 else 120.0))


def chase_order(ch):
	n = len(ch.get('steps') or [])
	o = list(range(n))
	return o + o[1:-1][::-1] if ch.get('pingpong') and n > 2 else o


def chase_expand(ch, start, end, bpm, limit=500):
	"""Steps from start to end (excluded): [{time, step, scene, fade}]."""
	order, out = chase_order(ch), []
	if not order:
		return out
	t, k = float(start), 0
	pct = max(0.0, min(100.0, float(ch.get('fadePct') or 0)))
	while t < end - 1e-6 and len(out) < limit:
		i = order[k % len(order)]
		st = ch['steps'][i]
		dur = chase_sec(st.get('hold') or ch.get('hold'), bpm)
		if st.get('scene'):
			out.append({'time': round(t, 3), 'step': i, 'scene': st['scene'], 'fade': round(dur * pct / 100.0, 2)})
		t += dur
		k += 1
	return out


def chases_track():
	return _meta('chases') or {'chases': [], 'cues': []}


def check_chases(track, missing='error'):
	"""Validate a chases track; returns (clean track, errors, warnings).
	A step whose scene TD does not have: error, or dropped with a warning
	when missing == 'marker' (as the timeline's missing_scenes)."""
	if not track:
		return {'chases': [], 'cues': []}, [], []
	if not isinstance(track, dict):
		return None, ['chases: serve un oggetto {chases, cues}'], []
	errors, warnings, chs, cues_out = [], [], [], []
	names = set(scene_names())
	for i, ch in enumerate(track.get('chases') or [], 1):
		if not isinstance(ch, dict) or not str(ch.get('id') or '').strip():
			errors.append('chase %d: serve un oggetto con id' % i)
			continue
		steps = []
		for j, st in enumerate(ch.get('steps') or [], 1):
			sc = str((st or {}).get('scene') or '')
			if sc and sc not in names:
				if missing == 'marker':
					warnings.append('chase %r step %d: scena %r non esiste -> saltato' % (ch['id'], j, sc))
					continue
				errors.append('chase %r step %d: scena %r non esiste' % (ch['id'], j, sc))
				continue
			d = {'scene': sc}
			if (st or {}).get('hold'):
				d['hold'] = dict(st['hold'])
			steps.append(d)
		if not steps:
			errors.append('chase %r: nessuno step valido' % ch['id'])
			continue
		chs.append({'id': str(ch['id']), 'name': str(ch.get('name') or ch['id']), 'steps': steps,
			'hold': dict(ch.get('hold') or {'value': 4, 'unit': 'beats'}),
			'fadePct': max(0.0, min(100.0, _f(ch.get('fadePct'), 0.0))), 'pingpong': bool(ch.get('pingpong'))})
	ids = {c['id'] for c in chs}
	for i, c in enumerate(track.get('cues') or [], 1):
		if not isinstance(c, dict):
			errors.append('chases cue %d: serve un oggetto' % i)
			continue
		try:
			t = _seconds(c.get('time'))
		except (ValueError, TypeError) as e:
			errors.append('chases cue %d: %s' % (i, e))
			continue
		cid = str(c.get('chase') or 'off')
		if cid != 'off' and cid not in ids:
			errors.append('chases cue %d: chase %r non è in chases.chases' % (i, cid))
			continue
		cues_out.append({'time': round(max(0.0, t), 3), 'chase': cid,
			'label': str(c.get('label') or '').replace('\t', ' ')})
	cues_out.sort(key=lambda c: c['time'])
	return {'chases': chs, 'cues': cues_out}, errors, warnings


@_memo
def chase_steps():
	"""The timeline's chase cues expanded: [{time, scene, fade, chase, step}]."""
	if _muted['chases']:
		return []
	tr = chases_track()
	by = {c['id']: c for c in tr.get('chases') or []}
	cs = tr.get('cues') or []
	length = float(_show().par.Length.eval())
	bpm = _meta('bpm')
	out = []
	for i, c in enumerate(cs):
		ch = by.get(c['chase'])
		if ch is None:
			continue
		end = min(length, cs[i + 1]['time'] if i + 1 < len(cs) else length)
		for s in chase_expand(ch, c['time'], end, float(bpm) if bpm else None):
			out.append(dict(s, chase=ch['id']))
	return out


def chase_at(t):
	"""(cue index, chase dict | None, step index | None) of the timeline's
	chase track at time t."""
	if _muted['chases']:
		return -1, None, None
	tr = chases_track()
	idx, cid = -1, None
	for i, c in enumerate(tr.get('cues') or []):
		if c['time'] <= t:
			idx, cid = i, (None if c['chase'] == 'off' else c['chase'])
	ch = next((c for c in tr.get('chases') or [] if c['id'] == cid), None)
	step = None
	if ch is not None:
		for s in chase_steps():
			if s['chase'] == ch['id'] and s['time'] <= t:
				step = s['step']
	return idx, ch, step


_live_chase = {}   # {chase, bpm, started (absTime s), ts, k (step counter applied)}


def start_chase(chase, bpm=None):
	"""Live: play a chase from its first step now (replaces a running one)."""
	clean, errors, _w = check_chases({'chases': [chase], 'cues': []})
	if errors:
		raise ValueError('; '.join(errors))
	import time
	_live_chase.clear()
	_live_chase.update(chase=clean['chases'][0], bpm=float(bpm) if bpm else None,
		started=absTime.seconds, ts=int(time.time() * 1000), k=-1, step=None)
	_live_chase_step()


def stop_chase():
	"""Live chase off: the last step's look stays."""
	_live_chase.clear()


def live_chase():
	return {'chase': _live_chase['chase'], 'bpm': _live_chase['bpm']} if _live_chase else None


def _live_chase_step():
	"""From tick(): recall the step whose turn it is (once per step)."""
	if not _live_chase:
		return
	ch = _live_chase['chase']
	bpm = _live_chase['bpm'] or _meta('bpm') or 120.0
	order = chase_order(ch)
	el = absTime.seconds - _live_chase['started']
	k, t = 0, 0.0
	durs = [chase_sec(ch['steps'][i].get('hold') or ch.get('hold'), bpm) for i in order]
	cycle = sum(durs)
	if cycle <= 0:
		return
	n_cycles = int(el // cycle)
	t = n_cycles * cycle
	k = n_cycles * len(order)
	for d in durs:
		if t + d > el:
			break
		t += d
		k += 1
	if k == _live_chase['k']:
		return
	_live_chase['k'] = k
	i = order[k % len(order)]
	st = ch['steps'][i]
	_live_chase['step'] = i
	if st.get('scene'):
		fade = round(durs[k % len(order)] * float(ch.get('fadePct') or 0) / 100.0, 2)
		try:
			recall(st['scene'], fade)
		except Exception as e:
			debug('live chase %s: %s' % (ch['id'], e))


def chase_state():
	"""{live: {chase_id, name, step, started_ts, bpm} | None,
	timeline: {cue, chase_id, step}} -- changes at start/stop and per step."""
	lv = None
	if _live_chase:
		lv = {'chase_id': _live_chase['chase']['id'], 'name': _live_chase['chase']['name'],
			'step': _live_chase.get('step'), 'started_ts': _live_chase['ts'], 'bpm': _live_chase['bpm']}
	p = _show().par
	tl = {'cue': -1, 'chase_id': None, 'step': None}
	if p.Active.eval():
		idx, ch, step = chase_at(float(p.Time.eval()))
		tl = {'cue': idx, 'chase_id': ch['id'] if ch else None, 'step': step}
	return {'live': lv, 'timeline': tl}


def chase_self_test():
	"""The assertions of plancia/test/chase.test.js (expansion part)."""
	CH = {'id': 'ch1', 'name': 'Rosso blu', 'steps': [{'scene': 'rosso'}, {'scene': 'blu'},
		{'scene': 'verde', 'hold': {'value': 2, 'unit': 'beats'}}], 'hold': {'value': 4, 'unit': 'beats'},
		'fadePct': 50, 'pingpong': False}
	fails = []
	s = chase_expand(CH, 10, 30, 120)
	if [[x['time'], x['scene'], x['fade']] for x in s[:4]] != [[10, 'rosso', 1], [12, 'blu', 1], [14, 'verde', 0.5], [15, 'rosso', 1]]:
		fails.append('expand: %r' % s[:4])
	if not all(x['time'] < 30 for x in s):
		fails.append('expand oltre la fine')
	pp = chase_expand(dict(CH, pingpong=True, steps=[{'scene': x['scene']} for x in CH['steps']]), 0, 10, 120)
	if [x['scene'] for x in pp[:5]] != ['rosso', 'blu', 'verde', 'blu', 'rosso']:
		fails.append('pingpong: %r' % [x['scene'] for x in pp[:5]])
	# the timeline: chase from 0, off at 6 -> steps at 0, 2, 4, 5
	tl = [x['time'] for x in chase_expand(CH, 0, 6, 120)]
	if tl != [0, 2, 4, 5]:
		fails.append('timeline: %r' % tl)
	return fails


def motion_tick():
	"""After tick(): run the head motion engine (it writes pan/tilt AFTER
	the timeline, so on pan/tilt the motion wins)."""
	hm = _motion_hm()
	if hm is None:
		return
	p = _show().par
	bpm = _meta('bpm')
	hm.tick(float(p.Time.eval()), bool(p.Active.eval()), float(bpm) if bpm else None)


# ---------------------------------------------------------------- inspector
# The show COMP's Scene / Cue / Automation pages edit the selected scene, cue
# and keyframe in place. Loading writes the table's values into the pars;
# the parexec then sees values equal to the table and writes nothing back.

class _Menu:
	def __init__(self, names, labels):
		self.menuNames = names
		self.menuLabels = labels


def lane_menu():
	names = automatable()
	return _Menu(names, [n.replace('.', '  ') for n in names])


def _set(p, v):
	if p.style == 'Toggle':
		v = bool(v)
	if str(p.eval()) != str(v):
		p.val = v


def load_scene():
	p = _show().par
	sc = [s for s in scenes() if s['name'] == str(p.Scene.eval())]
	if not sc:
		return
	sc = sc[0]
	_set(p.Scenelabel, sc['label'])
	for c in CATEGORIES:
		if p[_apply_par(c)] is not None:
			_set(p[_apply_par(c)], sc[c])


def load_cue():
	p = _show().par
	c = [c for c in cues() if c['id'] == int(p.Cue.eval())]
	if not c:
		return
	c = c[0]
	_set(p.Cuetime, c['time'])
	if c['scene']:   # a marker has no scene: leave the menu alone (no write-back)
		_set(p.Cuescene, c['scene'])
	_set(p.Cuefade, c['fade'])
	_set(p.Cuelabel, c['label'])


def load_key():
	p = _show().par
	k = [k for k in keys() if k['id'] == int(p.Key.eval())]
	if not k:
		return
	k = k[0]
	if k['lane'] in p.Lane.menuNames:
		_set(p.Lane, k['lane'])
	_set(p.Keytime, k['time'])
	_set(p.Keyvalue, k['value'])
	_set(p.Keyinterp, k['interp'])


def load_all():
	load_scene()
	load_cue()
	load_key()


def _differs(a, b):
	try:
		return abs(float(a) - float(b)) > 1e-6
	except (TypeError, ValueError):
		return str(a) != str(b)


def _apply_par(cat):
	"""Show par of a category flag (Applyrigs, Applyheadscolor...)."""
	return 'Apply' + cat.replace('_', '')


def on_value_change(par):
	p = _show().par
	n = par.name
	try:
		if n == 'Active' and par.eval():
			force_apply()
		elif n == 'Scene':
			load_scene()
		elif n == 'Cue':
			load_cue()
		elif n == 'Key':
			load_key()
		elif n in ('Scenelabel',) or n.startswith('Apply'):
			sc = [s for s in scenes() if s['name'] == str(p.Scene.eval())]
			if sc:
				field = 'label' if n == 'Scenelabel' else \
					next((c for c in CATEGORIES if _apply_par(c) == n), n[5:])
				v = par.eval() if n == 'Scenelabel' else (1 if par.eval() else 0)
				if _differs(sc[0][field], v):
					set_scene_flags(sc[0]['name'], **{field: v})
		elif n in ('Cuetime', 'Cuescene', 'Cuefade', 'Cuelabel'):
			c = [c for c in cues() if c['id'] == int(p.Cue.eval())]
			field = n[3:]
			if c and _differs(c[0][field], par.eval()):
				update_cue(c[0]['id'], **{field: par.eval()})
		elif n in ('Keytime', 'Keyvalue', 'Keyinterp'):
			k = [k for k in keys() if k['id'] == int(p.Key.eval())]
			field = n[3:]
			if k and _differs(k[0][field], par.eval()):
				update_key(k[0]['id'], **{field: par.eval()})
		p.Message = ''
	except ValueError as e:
		p.Message = str(e)
		load_all()


def on_pulse(par):
	show = _show()
	p = show.par
	n = par.name
	try:
		if n == 'Rewind':
			p.Time = 0
			force_apply()
		elif n == 'Fit':
			p.Viewstart = 0
			p.Viewlength = max(2.0, float(p.Length.eval()))
		elif n == 'Recall':
			recall(str(p.Scene.eval()))
		elif n == 'Capture':
			capture(str(p.Scene.eval()))
		elif n == 'Newscene':
			name = str(p.Newscenename.eval()).strip() or 'scena %d' % (len(scenes()) + 1)
			capture(name)
			p.Scene = name
			load_scene()
		elif n == 'Deletescene':
			delete_scene(str(p.Scene.eval()))
		elif n == 'Addcue':
			p.Cue = add_cue(float(p.Time.eval()), str(p.Scene.eval()), float(p.Cuefade.eval() or 2.0))
			load_cue()
		elif n == 'Deletecue':
			delete_cue(int(p.Cue.eval()))
		elif n == 'Gotocue':
			c = [c for c in cues() if c['id'] == int(p.Cue.eval())]
			if c:
				p.Time = c[0]['time']
		elif n == 'Addkey':
			p.Key = add_key(str(p.Lane.eval()), float(p.Time.eval()), interp=str(p.Keyinterp.eval()))
			load_key()
		elif n == 'Deletekey':
			delete_key(int(p.Key.eval()))
		p.Message = ''
	except ValueError as e:
		p.Message = str(e)
