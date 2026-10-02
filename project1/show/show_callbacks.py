# inspector pages of the show COMP -> show_logic (load / edit / pulses)
def onValueChange(par, prev):
	op('show_logic').module.on_value_change(par)
	return


def onPulse(par):
	op('show_logic').module.on_pulse(par)
	return
