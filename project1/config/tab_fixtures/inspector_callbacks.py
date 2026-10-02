# Inspector of the Fixture tab -> fixture_ui (edits write the selected
# fixture; values equal to the table are no-ops, so loading is safe).
def _ui():
	return parent.Config.op('tab_fixtures/fixture_ui').module


def onValueChange(par, prev):
	if par.name == 'Selected':
		_ui().load_selected()
	else:
		_ui().on_field_change(par)
	return


def onPulse(par):
	_ui().on_pulse(par)
	return
