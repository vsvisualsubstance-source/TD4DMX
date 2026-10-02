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


def onPulse(par):
	if par.name == 'Home':
		par.owner.par.Pan = 0
		par.owner.par.Tilt = 0
	return


def onValueChange(par, prev):
	if par.name in ('Count', 'Startaddress', 'Profile', 'Outputport'):
		_quick_patch(par)
	return
