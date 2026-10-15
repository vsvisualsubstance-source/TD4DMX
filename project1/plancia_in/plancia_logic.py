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
  /dmx/chase i          not implemented yet (no chase modes on the rigs)
  /mh/*                 moving heads: deferred, logged only
  /led/*                no LED wall: ignored

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
	if address == '/show/go':
		return _cue(1, args)
	if address == '/show/back':
		return _cue(-1, args)
	if address == '/dmx/chase':
		return 'chase %d non implementato (teste/chase rinviati)' % int(_f(args))
	if address.startswith('/mh/'):
		return 'ignorato: teste mobili rinviate (%s)' % address
	if address.startswith('/led/'):
		return None
	return 'indirizzo sconosciuto %s' % address


def on_osc(address, args):
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
