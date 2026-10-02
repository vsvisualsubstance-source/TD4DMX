# timeline canvas: press = seek / select / grab, drag = scrub / move,
# release = commit (timeline_ui)
def _ui():
	return parent.Config.op('tab_timeline/timeline_ui').module


def onOffToOn(panelValue):
	if panelValue.name == 'lselect':
		_ui().on_press(panelValue.owner.panel)
	return


def onOnToOff(panelValue):
	if panelValue.name == 'lselect':
		_ui().on_release(panelValue.owner.panel)
	return


def onValueChange(panelValue, prev):
	if panelValue.name in ('u', 'v') and panelValue.owner.panel.lselect:
		_ui().on_move(panelValue.owner.panel)
	return
