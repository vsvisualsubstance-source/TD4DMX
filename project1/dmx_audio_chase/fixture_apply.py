# Pagina "Fixture" del rig = PATCH RAPIDA del gruppo nella patch fixture
# (/project1/dmx_patch/fixtures, vedi fixture_logic). Un Parameter Execute
# DAT si scrive il codice addosso (.text), non ha un parametro che punta a un
# DAT esterno.
#
# - Fixtureprofile / Nbars / Startaddress / Applyfixture: riscrivono il
#   gruppo come blocco uniforme di indirizzi consecutivi (le fixture gia'
#   esistenti tengono nome e posizione sulla pianta).
# - Outputport: sposta tutte le fixture del gruppo su quella porta,
#   indirizzi invariati.
# Le modifiche fatte dalla finestra Config (fixture singole, profili misti)
# tornano su questi par tramite fixture_logic.sync_quick_pars(): quel valore
# e' un "eco" (is_echo) e qui non si ripatcha.
#
# dmx_select seleziona bar* (ordine DMX per unita'), vale anche per il clone
# dmx_audio_chase_b.

def _logic(comp):
	fx = comp.parent().op('dmx_patch/fixture_logic')
	return fx.module if fx is not None else None


def refresh_menu(comp):
	tbl = comp.op('fixture_profiles')
	if tbl is None:
		return
	names = [r[0].val for r in tbl.rows()[1:] if str(r[0].val).strip()]
	if not names:
		return
	par = comp.par.Fixtureprofile
	par.menuNames = names
	par.menuLabels = names
	if par.eval() not in names:
		par.val = names[0]


def apply(par):
	comp, par_name = par.owner, par.name
	fl = _logic(comp)
	if fl is None or (par.style != 'Pulse' and fl.is_echo(par)):
		return
	refresh_menu(comp)
	group = fl.group_of(comp)
	if group is None:
		return
	if par_name == 'Outputport':
		port = str(comp.par.Outputport.eval())
		for f in fl.rows(group):
			if f['port_id'] != port:
				fl.update_fixture(f['id'], port_id=port)
		return
	fl.quick_patch(comp)
	print('Fixture %s: %s' % (group, fl.addresses_text(comp)))


def onPulse(par):
	apply(par)
	return


def onValueChange(par, prev):
	apply(par)
	return
