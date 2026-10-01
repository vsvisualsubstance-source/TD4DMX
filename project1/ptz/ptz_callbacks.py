"""ptz parameter callbacks: Home, Store / Recall preset."""


def onPulse(par):
	comp = par.owner
	pres = op('presets')
	slot = str(int(comp.par.Presetslot.eval()))
	if par.name == 'Home':
		comp.par.Padu = 0.5
		comp.par.Padv = 0.5
	elif par.name == 'Storepreset':
		t = op('targets')
		pres[slot, 'u'] = round(float(t['u']), 4)
		pres[slot, 'v'] = round(float(t['v']), 4)
	elif par.name == 'Recallpreset':
		comp.par.Mode = 'pad'
		comp.par.Padu = float(pres[slot, 'u'])
		comp.par.Padv = float(pres[slot, 'v'])
	return
