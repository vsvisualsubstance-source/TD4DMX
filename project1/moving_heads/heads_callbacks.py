"""moving_heads parameter callbacks.

Count / Startaddress / Profile = PATCH RAPIDA del gruppo 'heads' nella patch
fixture (/project1/dmx_patch/fixtures): riscrivono le teste come blocco
uniforme consecutivo. Outputport sposta tutte le teste su quella porta.
Le modifiche fatte dalla finestra Config tornano qui via
fixture_logic.sync_quick_pars(): quel valore e' un "eco" (is_echo), niente
ripatch.
"""


def _logic(comp):
	fx = comp.parent().op('dmx_patch/fixture_logic')
	return fx.module if fx is not None else None


def _quick_patch(par):
	comp, par_name = par.owner, par.name
	fl = _logic(comp)
	if fl is None or fl.is_echo(par):
		return
	if par_name == 'Outputport':
		port = str(comp.par.Outputport.eval())
		for f in fl.rows('heads'):
			if f['port_id'] != port:
				fl.update_fixture(f['id'], port_id=port)
		return
	fl.quick_patch(comp)


def _programmer(par):
	"""Programmer page (head_programmer): selection, follow, release."""
	comp = par.owner
	hp = comp.op('head_programmer').module
	name = str(comp.par.Selectionname.eval()).strip()
	try:
		if par.name == 'Selectall':
			hp.select({'all': 1})
		elif par.name == 'Selectclear':
			hp.select({'clear': 1})
		elif par.name == 'Saveselection':
			hp.save_selection(name)
		elif par.name == 'Recallselection':
			hp.select({'set': name})
		elif par.name == 'Follow':
			hp.set_mode('follow')
		elif par.name == 'Release':
			hp.set_mode('global')
	except ValueError as e:
		debug('programmer:', e)


def onPulse(par):
	if par.name == 'Home':
		par.owner.par.Pan = 0
		par.owner.par.Tilt = 0
	elif par.name in ('Selectall', 'Selectclear', 'Saveselection', 'Recallselection', 'Follow', 'Release'):
		_programmer(par)
	return


def onValueChange(par, prev):
	if par.name in ('Count', 'Startaddress', 'Profile', 'Outputport'):
		_quick_patch(par)
	return
