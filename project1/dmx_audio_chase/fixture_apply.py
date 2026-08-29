
# Tiene allineati dmx_select e dmx_out ai parametri della pagina "Fixture".
# Un Parameter Execute DAT si scrive il codice addosso (.text), non ha un
# parametro che punta a un DAT esterno.

def profile_channels(comp):
	tbl = comp.op('fixture_profiles')
	if tbl is not None:
		cell = tbl[str(comp.par.Fixtureprofile.eval()), 'channels']
		if cell is not None and str(cell.val).strip():
			return str(cell.val).split()
	return ['red', 'green', 'blue']

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

def apply(comp):
	refresh_menu(comp)
	chans = profile_channels(comp)
	n = max(1, int(comp.par.Nbars.eval()))
	start = int(comp.par.Startaddress.eval())
	names = ['bar{}_{}'.format(i + 1, ch) for i in range(n) for ch in chans]

	sel = comp.op('dmx_select')
	if sel is not None:
		# l'ordine dei nomi = l'ordine degli indirizzi DMX
		sel.par.channames = ' '.join(names)

	out = comp.op('dmx_out')
	if out is not None:
		try:
			out.par.dmxstart = start
		except Exception as e:
			print('WARNING: dmx_out.par.dmxstart non impostato:', e)

	gen = comp.op('dmx_generator')
	if gen is not None:
		gen.cook(force=True)

	total = n * len(chans)
	last = start + total - 1
	print('Fixture: {} x {}CH -> DMX {}-{} ({} canali)'.format(
		n, len(chans), start, last, total))
	print('  indirizzi da impostare sulle fixture:',
	      ', '.join(str(start + i * len(chans)) for i in range(n)))
	if last > 512:
		print('  ATTENZIONE: sfori i 512 canali dell universo.'
		      ' Riduci le fixture o abbassa lo start address.')
	if 'dimmer' not in chans:
		print('  profilo senza canale dimmer: il livello viene moltiplicato'
		      ' dentro l RGB (Dimmer Gamma attiva)')

def onPulse(par):
	apply(par.owner)
	return

def onValueChange(par, prev):
	apply(par.owner)
	return
