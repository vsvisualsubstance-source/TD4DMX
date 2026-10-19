"""programmer_view -- the per-head programmer (moving_heads/head_programmer)
in the TD UI, so what Plancia (/mh/*) or Gaia do to the heads is visible
here too. The PTZ pad above drives the PTZ TARGET and the Teste page shows
the GLOBAL look: neither moves when Plancia moves single heads.

  heads_pad   XY pad of the FIRST selected head, same values AND orientation
              as Plancia's pad: x = pan (right = +1), y up = +1, -1..1 over
              the model's mechanical range (tilt = -y * range / 2, the
              engine's /mh/pantilt mapping).
              Dragging it moves every selected head (pantilt_norm, like
              /mh/pantilt).
  heads_text  one line per head: selected, mode, pan, tilt, dimmer, rgb,
              gobo.

sync() runs from view_tick (onFrameStart, throttled to SYNC_S); it never
writes the pad while it is being dragged. on_pad() comes from pad_exec;
values equal to the last one sync() wrote are its own echo and ignored.
"""
import time

SYNC_S = 0.1
_st = {'t': 0.0, 'wrote': None, 'text': None}


def _hp():
	return parent().parent().parent().op('moving_heads/head_programmer').module


def _pad():
	return op('heads_pad')


def _first_selected(hp):
	sel = set(hp.selection())
	for h in hp.heads():
		if h['key'] in sel:
			return h
	return None


def sync():
	now = time.perf_counter()
	if now - _st['t'] < SYNC_S:
		return
	_st['t'] = now
	hp = _hp()
	pad = _pad()
	first = _first_selected(hp)
	if first is not None and pad is not None and not pad.panel.lselect:
		e = hp.effective(first['key'])
		x, y = hp.pantilt_to_norm(first['key'], e['pan'], e['tilt'])
		# same orientation as Plancia's pad: top = y +1 (GAIA_INTERFACE 30)
		u, v = round((x + 1) / 2.0, 4), round((y + 1) / 2.0, 4)
		if _st['wrote'] != (u, v) or abs(pad.par.value0.eval() - u) > 1e-4 or abs(pad.par.value1.eval() - v) > 1e-4:
			_st['wrote'] = (u, v)
			pad.par.value0 = u
			pad.par.value1 = v
	_set_text(hp, first)


def _set_text(hp, first):
	rows = hp.heads_list()
	nsel = sum(1 for r in rows if r['selected'])
	lines = ['Programmer teste: %d teste, %d selezionate%s' % (len(rows), nsel,
		('  |  pad: %s' % first['name']) if first else '  |  nessuna selezionata: il pad non muove niente')]
	for r in rows:
		lines.append('%s %-6s %-7s pan %6.1f  tilt %6.1f  dim %.2f  rgb %.2f %.2f %.2f  gobo %3d' % (
			'*' if r['selected'] else ' ', r['name'], r['mode'], r['pan'], r['tilt'], r['dimmer'],
			r['red'], r['green'], r['blue'], int(r['gobo'])))
	text = '\n'.join(lines)
	if text != _st['text']:
		_st['text'] = text
		t = op('heads_text')
		if t is not None:
			t.par.text = text


def on_pad(par):
	"""pad_exec: the pad moved. Ours (sync) -> ignore; the user's -> move
	the selected heads like Plancia's /mh/pantilt."""
	pad = _pad()
	u, v = round(float(pad.par.value0.eval()), 4), round(float(pad.par.value1.eval()), 4)
	if _st['wrote'] is not None and abs(_st['wrote'][0] - u) < 1e-4 and abs(_st['wrote'][1] - v) < 1e-4:
		return
	hp = _hp()
	if not hp.selection():
		return
	hp.pantilt_norm(u * 2.0 - 1.0, v * 2.0 - 1.0)
	_st['wrote'] = (u, v)
