# umap: press = select/grab, drag = move, release = commit (fixture_ui)
def _ui():
	return parent.Config.op('tab_fixtures/fixture_ui').module


def onOffToOn(panelValue):
	if panelValue.name == 'lselect':
		_ui().on_press('umap', panelValue.owner.panel)
	return


def onOnToOff(panelValue):
	if panelValue.name == 'lselect':
		_ui().on_release('umap', panelValue.owner.panel)
	return


def onValueChange(panelValue, prev):
	if panelValue.name in ('u', 'v') and panelValue.owner.panel.lselect:
		_ui().on_move('umap', panelValue.owner.panel)
	return
