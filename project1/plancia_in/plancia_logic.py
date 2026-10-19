"""plancia_logic -- Plancia channel 5 (gaia plancia/GAIA_PLANCIA_INTEGRATION.md):
live show control sent by Plancia's bridge.js (on OPS) straight to DMX
Master over OSC, port Port (7020). osc_plancia_callbacks hands every message
to on_osc(). Status / Lastmessage / Messages on this COMP show what happened.

  /dmx/group/<g> f      Level of the group's rig (name or alias: front = rig_a,
                        back = rig_b, ...); unknown group -> Status only
  /dmx/master f         dmx_patch Master
  /dmx/blackout 0/1     dmx_patch Blackout
  /dmx/strobe 0/1       dmx_patch Strobe
  /dmx/strobe/rate hz   dmx_patch Stroberate
  /dmx/fade s           Fade used by the next /dmx/scene
  /dmx/scene i          show scene number i (0-based, show order), crossfade Fade
  /show/go, /show/back  next / previous cue of the show timeline (on press)
  /show/play 0/1        play / pause the show timeline (TD is the clock master)
  /show/time s          seek, only while TD is stopped: while playing Plancia
                        sends its own time 10x/s and TD's clock wins
  /show/cue n           ignored: it is a cue of Plancia's own widget list,
                        not of TD's timeline (use /show/go, /show/back or the
                        show clock command 'cue' on MQTT)
  /dmx/output/osc 0/1   Plancia's MQTT is down: send the per-fixture
                        output over OSC too (valid OSC_WANT_S, repeat it)
  /dmx/chase i         not implemented yet (no chase modes on the rigs)
  /mh/*                 moving heads, selective: moving_heads/head_programmer
                        (select mask / select/heads|add|remove|set|all|clear,
                        pantilt, pan, tilt, color, dimmer, zoom, focus,
                        white, strobe, gobo, colorwheel, position,
                        position/store, preset/recall, preset/store, home,
                        follow, release) on the selected heads; preset/remove,
                        preset/rename, position/remove, position/rename
                        (no selection needed). Store/recall/remove take an
                        index or a name (string arg); a preset/position list
                        change is republished to Gaia at once
  /led/*                no LED wall: ignored

Feedback to bridge.js (Feedbackhost:Feedbackport, OSC_IN 9000) via
osc_feedback, every frame from feedback_tick(); par Feedback = master switch,
then per area:
  Feedbackshow   the show timeline -- /show/play on change, /show/time 10x/s
                 while playing (and on change while stopped), /show/cue <n>
                 (1-based, 0 = before the first cue) on change. The same
                 clock goes to every other device on MQTT through
                 gaia_client/show_clock. Off until Plancia follows TD's clock
                 (today it fires its own cues when it sees play=1).
  Feedbackheads  the moving heads, 10x/s on change: /mh/select (mask in unit
                 order) and /mh/select/heads <uid...> (Plancia's head
                 selector), /mh/result <seq> <ok 0|1> <action> <target>
                 <message> after every discrete /mh/* command (also Gaia
                 heads_*: the outcome Plancia waits for), the first selected head's
                 /mh/pantilt (pad -1..1), /mh/color, /mh/dimmer, /mh/zoom,
                 /mh/focus, /mh/strobe, /mh/gobo (slot index), and
                 /dmx/group/mh (heads Level). Plancia only updates its
                 widgets with what it receives (no re-send), so there is no
                 loop. An address Plancia sent in the last ECHO_HOLD_S is not
                 echoed back (a pad being dragged never jumps); everything is
                 re-sent every FEEDBACK_REFRESH_S for tablets opened later.
  Feedbackdmx    /dmx/master, /dmx/blackout, /dmx/strobe, /dmx/strobe/rate,
                 /dmx/fade, /dmx/scene, /dmx/group/<alias> (same rules), and
                 the per-fixture OSC backup (Feedbackfixtures, see
                 _fixtures_feedback): the main channel is MQTT dmx_output.

All numbers arrive as OSC floats. Runs on the main thread (OSC In DAT
callback), so it touches pars directly.
"""
import time


def _home():
	return parent().parent()


def _patch():
	return _home().op('dmx_patch')


def _fl():
	return _patch().op('fixture_logic').module


def _show_logic():
	return _home().op('show/show_logic').module


def _f(args, i=0, d=0.0):
	try:
		return float(args[i])
	except (IndexError, TypeError, ValueError):
		return d


def _clamp01(v):
	return max(0.0, min(1.0, v))


def _pressed(args):
	return not args or _f(args) >= 0.5


def _group(name, args):
	fl = _fl()
	g = fl.resolve_group(name)
	if g is None:
		return 'gruppo %r non esiste' % name
	comp = fl.group_comp(g)
	lp = comp.par['Level'] if comp is not None else None
	if lp is None:
		return 'gruppo %s senza Level' % g
	lp.val = _clamp01(_f(args))
	return '%s Level=%.2f' % (g, lp.eval())


def _scene(args):
	sl = _show_logic()
	names = sl.scene_names()
	i = int(round(_f(args, d=-1)))
	if not 0 <= i < len(names):
		return 'scena %d non esiste (%d scene)' % (i, len(names))
	fade = float(parent().par.Fade.eval())
	sl.recall(names[i], fade)
	return 'scena %s (fade %.1fs)' % (names[i], fade)


def _cue(step, args):
	if not _pressed(args):
		return None
	c = _show_logic().goto_cue(step)
	return 'cue %s @ %.1fs (%s)' % (c.get('label') or c['id'], c['time'], c['scene'])


def handle(address, args):
	"""Apply one message; returns a status line, None = nothing to report."""
	pp = _patch().par
	if address.startswith('/dmx/group/'):
		return _group(address[len('/dmx/group/'):], args)
	if address == '/dmx/master':
		pp.Master = _clamp01(_f(args))
		return 'master %.2f' % pp.Master.eval()
	if address == '/dmx/blackout':
		pp.Blackout = _f(args) >= 0.5
		return 'blackout %s' % ('on' if pp.Blackout.eval() else 'off')
	if address == '/dmx/strobe':
		pp.Strobe = _f(args) >= 0.5
		return 'strobe %s' % ('on' if pp.Strobe.eval() else 'off')
	if address == '/dmx/strobe/rate':
		pp.Stroberate = max(0.5, _f(args, d=8.0))
		return 'strobe rate %.1f Hz' % pp.Stroberate.eval()
	if address == '/dmx/fade':
		parent().par.Fade = max(0.0, _f(args))
		return 'fade %.1fs' % parent().par.Fade.eval()
	if address == '/dmx/scene':
		return _scene(args)
	if address == '/dmx/output/osc':
		_fx['want'] = time.perf_counter() + OSC_WANT_S if _f(args) >= 0.5 else 0.0
		return 'feedback fixture OSC %s dalla Plancia' % ('richiesto' if _fx['want'] else 'non richiesto')
	if address == '/show/go':
		return _cue(1, args)
	if address == '/show/back':
		return _cue(-1, args)
	if address == '/show/play':
		return _show_logic().clock_command('play', _f(args))
	if address == '/show/time':
		if _home().op('show').par.Play.eval():
			return None
		return _show_logic().clock_command('seek', _f(args))
	if address == '/show/cue':
		return 'cue %d della Plancia ignorata: le cue sono quelle di TD' % int(_f(args))
	if address == '/dmx/chase':
		return 'chase %d non implementato (teste/chase rinviati)' % int(_f(args))
	if address.startswith('/mh/'):
		msg = _home().op('moving_heads/head_programmer').module.on_osc(address, args)
		if address.startswith(LIST_CHANGES):
			_lists_changed()
		return msg
	if address.startswith('/led/'):
		return None
	return 'indirizzo sconosciuto %s' % address


LIST_CHANGES = ('/mh/preset/store', '/mh/preset/remove', '/mh/preset/rename',
	'/mh/position/store', '/mh/position/remove', '/mh/position/rename')


def _lists_changed():
	"""A preset/position list changed from OSC: republish it to Gaia now
	(status + dmx_matrix) instead of at the next 30 s heartbeat."""
	dat = _home().op('gaia_services/dmx_services')
	if dat is not None:
		try:
			dat.module.heads_lists_changed()
		except Exception as e:
			debug('heads_lists_changed: %s' % e)


FEEDBACK_TIME_S = 0.1
FEEDBACK_HEADS_S = 0.1
FEEDBACK_REFRESH_S = 5.0
ECHO_HOLD_S = 0.5
OSC_WANT_S = 15.0
_fb = {'play': None, 'cue': None, 'time': None, 'sent': 0.0}
_fbh = {'sent': {}, 't': 0.0, 'refresh': 0.0}
_fx = {'sent': {}, 't': 0.0, 'refresh': 0.0, 'want': 0.0, 'source': None}
_recent = {}   # address -> perf_counter of the last message from Plancia


def feedback_tick():
	"""Every frame (feedback_tick Execute DAT): TD state -> Plancia."""
	c = parent().par
	on = c.Feedback.eval()
	if not (on and c.Feedbackshow.eval()):
		_fb.update(play=None, cue=None, time=None)
	if not on:
		_fbh['sent'].clear()
		return
	if c.Feedbackshow.eval():
		_show_feedback(op('osc_feedback'))
	if c.Feedbackheads.eval():
		try:
			_heads_feedback(op('osc_feedback'))
		except Exception as e:
			c.Status = 'feedback teste: %s' % e
	if c.Feedbackdmx.eval():
		try:
			_dmx_feedback(op('osc_feedback'))
		except Exception as e:
			c.Status = 'feedback dmx: %s' % e


def _heads_feedback(out):
	now = time.perf_counter()
	if now - _fbh['t'] < FEEDBACK_HEADS_S:
		return
	_fbh['t'] = now
	if now - _fbh['refresh'] >= FEEDBACK_REFRESH_S:
		_fbh['refresh'] = now
		_fbh['sent'].clear()
	mh = _home().op('moving_heads')
	hp = mh.op('head_programmer').module
	hs = hp.heads()
	sel = set(hp.selection())
	msgs = {'/mh/select': [1 if h['key'] in sel else 0 for h in hs],
		'/mh/select/heads': [h['uid'] or h['key'] for h in hs if h['key'] in sel]}
	first = next((h['key'] for h in hs if h['key'] in sel), None)
	if first is not None:
		e = hp.effective(first)
		msgs['/mh/pantilt'] = list(hp.pantilt_to_norm(first, e['pan'], e['tilt']))
		msgs['/mh/color'] = [e['red'], e['green'], e['blue']]
		for f in ('dimmer', 'zoom', 'focus'):
			msgs['/mh/' + f] = [e[f]]
		msgs['/mh/strobe'] = [1 if e['strobe'] >= 0.5 else 0]
		msgs['/mh/gobo'] = [hp.wheel_index(first, 'gobo', e['gobo'])]
	_send_changed(out, msgs, now)
	res = hp.last_result()
	if res and res['seq'] != _fbh.get('result'):
		_fbh['result'] = res['seq']
		out.sendOSC('/mh/result', [res['seq'], 1 if res['ok'] else 0, res['action'], res['target'], res['message']],
			useNonStandardTypes=False)


def _send_changed(out, msgs, now):
	"""Send the addresses whose args changed since the last send, never an
	address Plancia itself sent in the last ECHO_HOLD_S."""
	for addr, args in msgs.items():
		args = [x if isinstance(x, (int, str)) else round(float(x), 3) for x in args]
		if _fbh['sent'].get(addr) == args:
			continue
		_fbh['sent'][addr] = args
		if now - _recent.get(addr, -1e9) < ECHO_HOLD_S:
			continue   # Plancia's own value: never echoed back
		out.sendOSC(addr, args, useNonStandardTypes=False)


def _dmx_feedback(out):
	"""/dmx/scene <index of the active scene>, /dmx/master, /dmx/blackout,
	/dmx/group/<alias or group> <Level>: same throttle/refresh/echo rules as
	the heads (shares _fbh)."""
	now = time.perf_counter()
	if now - _fbh.get('t_dmx', 0.0) < FEEDBACK_HEADS_S:
		return
	_fbh['t_dmx'] = now
	pp = _patch().par
	msgs = {'/dmx/master': [float(pp.Master.eval())], '/dmx/blackout': [1 if pp.Blackout.eval() else 0],
		'/dmx/strobe': [1 if pp.Strobe.eval() else 0], '/dmx/strobe/rate': [float(pp.Stroberate.eval())],
		'/dmx/fade': [float(parent().par.Fade.eval())]}
	act = _show_logic().active_scene()
	if act and act.get('index', -1) >= 0:
		msgs['/dmx/scene'] = [int(act['index'])]
	fl = _fl()
	for g in fl.groups():
		comp = fl.group_comp(g['group'])
		lp = comp.par['Level'] if comp is not None else None
		if lp is not None:
			msgs['/dmx/group/' + (g.get('alias') or g['group'])] = [float(lp.eval())]
	_send_changed(out, msgs, now)
	_fixtures_feedback(out, now)


def _fixtures_source(now):
	"""'mqtt' or 'osc': where Plancia should read the per-fixture output."""
	mode = parent().par.Feedbackfixtures.eval()
	if mode == 'off':
		return 'mqtt'
	if mode == 'always' or now < _fx['want']:
		return 'osc'
	out_dat = _home().op('gaia_services/dmx_output')
	return 'mqtt' if out_dat is not None and out_dat.module.mqtt_ok() else 'osc'


def _fixtures_feedback(out, now):
	"""OSC backup of MQTT dmx_output (same values, see TD/Win-PD 28):
	/dmx/output/source mqtt|osc on change and every FEEDBACK_REFRESH_S;
	while the source is osc, per fixture on change (10/s, all every
	FEEDBACK_REFRESH_S): /dmx/fixture/<uid> sent intensity r g b (rgb_out
	0-1, -1 = no such channel) and, heads only, /dmx/fixture/<uid>/head
	pan tilt (degrees) gobo color_wheel shutter (0-255, -1 = none)."""
	src = _fixtures_source(now)
	refresh = now - _fx['refresh'] >= FEEDBACK_REFRESH_S
	if refresh:
		_fx['refresh'] = now
		_fx['sent'].clear()
	if src != _fx['source'] or refresh:
		_fx['source'] = src
		out.sendOSC('/dmx/output/source', [src], useNonStandardTypes=False)
	if src != 'osc':
		_fx['sent'].clear()
		return
	snap = _home().op('gaia_services/dmx_output').module.snapshot()
	n = lambda v: -1 if v is None else v
	for f in snap['fixtures']:
		key = f['uid'] or 'id%d' % f['id']
		rgb = f['rgb_out'] or [None, None, None]
		msgs = {'/dmx/fixture/' + key: [1 if f['sent'] else 0, round(float(n(f['intensity'])), 3)]
			+ [round(float(n(x)), 3) for x in rgb]}
		if f['group'] == 'heads':
			msgs['/dmx/fixture/%s/head' % key] = [round(float(n(f['pan'])), 1), round(float(n(f['tilt'])), 1),
				int(n(f['gobo'])), int(n(f['color_wheel'])), int(n(f['shutter']))]
		for addr, args in msgs.items():
			if _fx['sent'].get(addr) != args:
				_fx['sent'][addr] = args
				out.sendOSC(addr, args, useNonStandardTypes=False)


def _show_feedback(out):
	p = _home().op('show').par
	playing = bool(p.Play.eval())
	t = round(float(p.Time.eval()), 2)
	cue = _show_logic().cue_at(t)[0] + 1
	now = time.perf_counter()
	if playing != _fb['play']:
		_fb['play'] = playing
		out.sendOSC('/show/play', [1 if playing else 0], useNonStandardTypes=False)
	if cue != _fb['cue']:
		_fb['cue'] = cue
		out.sendOSC('/show/cue', [cue], useNonStandardTypes=False)
	if (playing and now - _fb['sent'] >= FEEDBACK_TIME_S) or (not playing and t != _fb['time']):
		_fb.update(time=t, sent=now)
		out.sendOSC('/show/time', [float(t)], useNonStandardTypes=False)


def on_osc(address, args):
	_recent[address] = time.perf_counter()
	c = parent()
	c.par.Messages = int(c.par.Messages.eval()) + 1
	c.par.Lastmessage = '%s %s  @ %s' % (address, ' '.join('%g' % a if isinstance(a, float) else str(a) for a in args),
		time.strftime('%H:%M:%S'))
	try:
		status = handle(address, list(args))
	except Exception as e:
		status = 'errore %s: %s' % (address, e)
		debug(status)
	if status is not None:
		c.par.Status = status
