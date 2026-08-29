# TDN Exclusions drop zone. A native par-dialog drag delivers
# ParGroup items (field-verified 2026-08-24), a network-editor drag
# delivers OPs, a scripted drag can deliver bare Pars -- accept Pars
# (unwrapped from groups) and COMPs; EmbodyExt.OmitPanelDrop toggles
# tdn_omit:<par> / tdn_exclude accordingly.

def _trace(msg):
	# Diagnostic ring on the panel (read via fetch('dd_trace')).
	try:
		log = parent().fetch('dd_trace', [], search=False)
		log.append(msg)
		parent().store('dd_trace', log[-40:])
	except Exception:
		pass

def _itemsFromDrag(items):
	out = []
	for i in items:
		if isinstance(i, Par):
			out.append(i)
		elif isinstance(i, ParGroup):
			out.extend(p for p in i if p is not None)
		elif isinstance(i, COMP):
			out.append(i)
	return out

def onHoverStartGetAccept(comp, info):
	items = info.get('dragItems', [])
	usable = _itemsFromDrag(items)
	_trace(f'hover on {comp.name}: {[type(i).__name__ for i in items]} -> {bool(usable)}')
	return bool(usable)

def onDropGetResults(comp, info):
	items = info.get('dragItems', [])
	usable = _itemsFromDrag(items)
	_trace(f'drop on {comp.name}: {[getattr(i, "name", "?") for i in usable]}')
	if usable:
		parent.Embody.OmitPanelDrop(usable)
	return {'droppedOn': comp}
