"""show_logic -- timeline engine of /project1/show (scenes, cues, automation).

Tables (siblings, file-synced tsv):
  scenes        name, label, rigs, heads, groups, audio   (category flags 0/1:
                which parts of the snapshot the scene applies)
  scene_values  scene, target, par, value   (one row per captured par)
  cues          id, time, scene, fade, label   (seconds)
  keys          id, lane, time, value, interp  (lane = '<target>.<Par>';
                interp: linear | step | smooth)

Categories of a scene snapshot (pars read from the live COMPs, so pars added
to those pages later are captured automatically):
  rigs    rig_a / rig_b 'DMX Reactive' page (palette, dimmer, colour, kick)
  heads   moving_heads 'Position' + 'Look' pages, ptz Mode / Padu / Padv
  groups  Patchenable of rig_a / rig_b / heads, dmx_patch Blackout
  audio   Audiobus of rig_a / rig_b (which audio source drives the rig)

State at time t is STATELESS (scrub / seek / loop always land right):
  cue = last cue with time <= t (none -> the timeline does not drive);
  crossfade from the previous cue's scene over cue.fade seconds: numbers
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
CATEGORIES = ['rigs', 'heads', 'groups', 'audio']
CATEGORY_LABELS = {'rigs': 'Look rig A/B', 'heads': 'Teste mobili', 'groups': 'Accensioni gruppi', 'audio': 'Sorgente audio'}
INTERPS = ['linear', 'smooth', 'step']

SCENE_COLS = ['name', 'label'] + CATEGORIES
VALUE_COLS = ['scene', 'target', 'par', 'value']
CUE_COLS = ['id', 'time', 'scene', 'fade', 'label']
KEY_COLS = ['id', 'lane', 'time', 'value', 'interp']

_last = {}        # (target, par) -> last value applied
_force = [True]   # next tick applies everything
_clock = {'secs': None}
_cache = {}       # memoised table reads; cleared by invalidate()


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


def invalidate():
	"""Tables or COMP pages changed: drop the caches, re-apply everything."""
	_cache.clear()
	_force[0] = True


# ---------------------------------------------------------------- basics

def _show():
	return me.parent()


def target_comp(target):
	name = TARGETS.get(target)
	return _show().parent().op(name) if name else None


def _table(name, cols):
	t = _show().op(name)
	if t.numRows == 0 or t[0, 0] is None or t[0, 0].val != cols[0]:
		t.clear()
		t.appendRow(cols)
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
	if cat == 'rigs':
		return _page_pars('rig_a', ('DMX Reactive',), ('Audiobus',)) + \
			_page_pars('rig_b', ('DMX Reactive',), ('Audiobus',))
	if cat == 'heads':
		return _page_pars('heads', ('Position', 'Look')) + \
			[('ptz', n) for n in ('Mode', 'Padu', 'Padv') if target_comp('ptz') is not None]
	if cat == 'groups':
		return [('rig_a', 'Patchenable'), ('rig_b', 'Patchenable'),
			('heads', 'Patchenable'), ('patch', 'Blackout')]
	if cat == 'audio':
		return [('rig_a', 'Audiobus'), ('rig_b', 'Audiobus')]
	return []


@_memo
def _category_of():
	m = {}
	for cat in CATEGORIES:
		for k in category_pars(cat):
			m[k] = cat
	return m


def _par(target, name):
	c = target_comp(target)
	return getattr(c.par, name) if c is not None and hasattr(c.par, name) else None


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
		out.append(d)
	return out


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
	out = {}
	for r in _rows('scene_values', VALUE_COLS):
		if r['scene'] != name:
			continue
		k = (r['target'], r['par'])
		if not sc.get(cat.get(k, ''), 0):
			continue
		p = _par(*k)
		if p is None:
			continue
		v = r['value']
		out[k] = _i(v) if p.style == 'Toggle' else (_f(v) if _is_number(p) else v)
	return out


def capture(name, label=None):
	"""Store the current live values of every category into scene `name`
	(created if new; existing values replaced, category flags kept)."""
	name = str(name).strip()
	if not name:
		raise ValueError('nome scena vuoto')
	st = _table('scenes', SCENE_COLS)
	if _row_index('scenes', SCENE_COLS, 'name', name) is None:
		st.appendRow([name, label or name] + [1] * len(CATEGORIES))
	elif label:
		st[_row_index('scenes', SCENE_COLS, 'name', name), 'label'] = label
	vt = _table('scene_values', VALUE_COLS)
	for r in range(vt.numRows - 1, 0, -1):
		if vt[r, 'scene'].val == name:
			vt.deleteRow(r)
	for cat in CATEGORIES:
		for t, n in category_pars(cat):
			p = _par(t, n)
			if p is not None:
				v = _read(p)
				vt.appendRow([name, t, n, round(v, 6) if isinstance(v, float) else v])
	invalidate()
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
	invalidate()


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
	invalidate()


def recall(name, fade=0.0):
	"""Apply a scene now (live use). The timeline, if Active, takes over
	again only for pars whose target changes afterwards."""
	vals = scene_values(name)
	if not vals:
		raise ValueError('scena %r vuota o inesistente' % name)
	_apply(vals, force=True)


# ---------------------------------------------------------------- cues

@_memo
def cues():
	out = []
	for r in _rows('cues', CUE_COLS):
		out.append({'id': _i(r['id']), 'time': _f(r['time']), 'scene': r['scene'],
			'fade': max(0.0, _f(r['fade'])), 'label': r['label']})
	return sorted(out, key=lambda c: (c['time'], c['id']))


def _check_cue(d):
	if 'scene' in d and d['scene'] not in scene_names():
		raise ValueError('scena %r non esiste' % d['scene'])
	if 'time' in d:
		d['time'] = round(max(0.0, _f(d['time'])), 3)
	if 'fade' in d:
		d['fade'] = round(max(0.0, _f(d['fade'])), 3)
	return d


def add_cue(time, scene, fade=2.0, label=''):
	d = _check_cue({'id': _next_id('cues', CUE_COLS), 'time': time, 'scene': scene, 'fade': fade, 'label': label})
	_table('cues', CUE_COLS).appendRow([d[c] for c in CUE_COLS])
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
			t[r, k] = v
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

def cue_at(t):
	"""(index, cue) of the cue active at time t, or (-1, None)."""
	cs = cues()
	idx = -1
	for i, c in enumerate(cs):
		if c['time'] <= t:
			idx = i
	return idx, (cs[idx] if idx >= 0 else None), cs


def state_at(t):
	"""{(target, par): value} the timeline wants at time t."""
	idx, cue, cs = cue_at(t)
	out = {}
	if cue is not None:
		cur = scene_values(cue['scene'])
		prev = scene_values(cs[idx - 1]['scene']) if idx > 0 else {}
		x = 1.0 if cue['fade'] <= 0 else max(0.0, min(1.0, (t - cue['time']) / cue['fade']))
		for k, v in cur.items():
			if x < 1.0 and k in prev:
				a = prev[k]
				if isinstance(v, float) and isinstance(a, float):
					v = a + (v - a) * x
				elif x < 0.5:
					v = a
			out[k] = v
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
	for k, v in state.items():
		old = _last.get(k)
		if not force and old is not None and (old == v or (
				isinstance(v, float) and isinstance(old, float) and abs(old - v) < 1e-6)):
			continue
		_last[k] = v
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
				t = t % length
				_force[0] = True
			else:
				t = length
				p.Play = False
		p.Time = round(t, 4)
	if p.Active.eval():
		_apply(state_at(t), force=_force[0])
		_force[0] = False
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
	if cue is None:
		return head + '  |  prima della prima cue'
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
	for d in clean:
		t.appendRow([d[c] for c in CUE_COLS])
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
		_set(p['Apply' + c], sc[c])


def load_cue():
	p = _show().par
	c = [c for c in cues() if c['id'] == int(p.Cue.eval())]
	if not c:
		return
	c = c[0]
	_set(p.Cuetime, c['time'])
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
				field = 'label' if n == 'Scenelabel' else n[5:]
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
