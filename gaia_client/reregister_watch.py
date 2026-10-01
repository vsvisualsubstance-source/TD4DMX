"""Parameter Execute DAT -- watches the Reregister pulse on gaia_client
(GAIA_INTERFACE.md section 2, 2026-08-29) and calls
gaia_device_agent.reregister() when it fires. Value Change/Expression/
Export/Enable/Mode callbacks are unused stubs (Value Change toggle stays
on by default, harmless -- only onPulse acts)."""


def onValueChange(par, prev):
	return


def onPulse(par):
	if par.name == 'Reregister':
		op('gaia_device_agent').module.reregister()
	return


def onExpressionChange(par, val):
	return


def onExportChange(par, val):
	return


def onEnableChange(par, val):
	return


def onModeChange(par, val):
	return
