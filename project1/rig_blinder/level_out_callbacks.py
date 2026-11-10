"""level_out -- one channel per unit attribute (unit<u>_<attr>, DMX order of
the unit's profile, see dmx_patch/group_logic). Intensity channels (dimmer*
and colour/output) at full scale (255): Level/Master/Strobe are applied in
dmx_patch/universe_build. 'fan' follows the Fan par; any other role
(strobe, mode, placeholder ch<N> of a catalog model with only its channel
count) is 0. Cooks on change only (tables + pars)."""
FULL = 255.0
INTENSITY = ('red', 'green', 'blue', 'white', 'amber', 'uv', 'output')


def onSetupParameters(scriptOp):
	return


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.numSamples = 1
	comp = parent()
	fl = comp.parent().op('dmx_patch/fixture_logic').module
	group = fl.group_of(comp)
	if group is None:
		return
	fan = float(comp.par.Fan.eval()) * FULL
	for u, prof in enumerate(fl.unit_profiles(comp, cached=False), 1):
		for attr in fl.profile_channels(group, prof) or []:
			c = scriptOp.appendChan('unit%d_%s' % (u, attr))
			c[0] = fan if attr == 'fan' else 				FULL if attr.startswith('dimmer') or attr in INTENSITY else 0.0
	return
