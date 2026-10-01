"""moving_heads parameter callbacks."""


def onPulse(par):
	if par.name == 'Home':
		par.owner.par.Pan = 0
		par.owner.par.Tilt = 0
	return
