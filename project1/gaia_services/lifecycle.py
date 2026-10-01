"""
DMX Services Lifecycle -- wires dmx_services.register_all() into
gaia_client's project-registrar hook. gaia_client (op.Gaia, the unmodified
portable 1.2.1 .tox) never calls project code directly by design -- this
project-specific Execute DAT does it instead, from outside gaia_client, same
layout as PatchDeck's /PATCHDECK/gaia_services/lifecycle.

Registers once at onCreate/onStart, and re-arms the registrar pointer
periodically: gaia_device_agent.py wipes its _registrar back to None on
every hot-reload of ITS OWN module, so the pointer needs to be handed back
periodically, not only once at startup. The retry itself (registry found
empty) is generic inside gaia_device_agent._self_check().
"""
import time

_REARM_INTERVAL_S = 5.0
_last_rearm = 0.0


def _agent():
	client = op.Gaia
	if client is None:
		return None
	dat = client.op('gaia_device_agent')
	return dat.module if dat is not None else None


def _arm(run_now):
	agent = _agent()
	services = op('dmx_services')
	if agent is None or services is None:
		return
	if run_now or agent._registrar is None:
		agent.register_project_registrar(services.module.register_all)
	if run_now:
		try:
			services.module.register_all()
		except Exception as e:
			agent._record_error('register_all', e)


def onStart():
	_arm(run_now=True)
	return


def onCreate():
	_arm(run_now=True)
	return


def onExit():
	return


def onFrameStart(frame: int):
	global _last_rearm
	disc = op('touch_discovery')
	if disc is not None:
		try:
			disc.module.tick()
		except Exception as e:
			debug('touch_discovery.tick failed:', e)
	now = time.time()
	if (now - _last_rearm) >= _REARM_INTERVAL_S:
		_last_rearm = now
		_arm(run_now=False)
	return


def onFrameEnd(frame: int):
	return


def onPlayStateChange(state: bool):
	return


def onDeviceChange():
	return


def onProjectPreSave():
	return


def onProjectPostSave():
	return
