"""dmx_patch parameter callbacks: Scan, and the Catalog page (manual entry of
fixture models in TD, see catalog_logic)."""


def _catalog_action(par):
	comp = parent()
	cat = op('catalog_logic').module
	name = str(comp.par.Modelname.eval()).strip()
	try:
		if par.name == 'Modelload':
			m = cat.model(name)
			if m is None:
				raise ValueError('modello %r non nel catalogo' % name)
			comp.par.Modelkind = m['kind']
			comp.par.Modelchannels = ' '.join(m['channels'])
			comp.par.Modelmanufacturer = m['manufacturer']
			msg = 'caricato %s: %d canali' % (name, m['footprint'])
		elif par.name == 'Modelsave':
			cat.set_model({'model': name, 'kind': str(comp.par.Modelkind.eval()),
				'channels': str(comp.par.Modelchannels.eval()),
				'manufacturer': str(comp.par.Modelmanufacturer.eval())}, source='manual')
			m = cat.model(name)
			msg = 'salvato %s: %d canali%s' % (name, m['footprint'],
				'' if m['complete'] else ' (ruoli ch1..chN da compilare)')
		else:
			cat.remove_model(name)
			msg = 'rimosso %s' % name
	except Exception as e:
		msg = 'errore: %s' % e
	comp.par.Catalogstatus = msg


def onPulse(par):
	if par.name == 'Scan':
		op('scan_logic').module.scan()
	elif par.name in ('Modelload', 'Modelsave', 'Modelremove'):
		_catalog_action(par)
	return
