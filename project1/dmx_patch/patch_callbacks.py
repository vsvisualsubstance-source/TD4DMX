"""dmx_patch parameter callbacks."""


def onPulse(par):
	if par.name == 'Scan':
		op('scan_logic').module.scan()
	return
