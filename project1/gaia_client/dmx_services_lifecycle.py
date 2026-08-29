"""
DMX Services Lifecycle -- wires dmx_services.register_all() into
gaia_client's project-registrar hook. gaia_client's own core
(agent_lifecycle.py) never calls project code directly by design (it
stays identical across every project that uses gaia_client) -- this
project-specific Execute DAT does it instead.

Registers once at onCreate, and re-arms the registrar pointer
periodically: gaia_device_agent.py wipes its _registrar back to None on
every hot-reload of ITS OWN module (see its register_project_registrar
docstring), so the pointer needs to be handed back periodically, not only
once at startup.
"""
import time

_REARM_INTERVAL_S = 10.0
_last_rearm = 0.0


def _agent():
	return op('gaia_device_agent').module


def _arm(run_now):
	agent = _agent()
	agent.register_project_registrar(op('dmx_services').module.register_all)
	if run_now:
		try:
			op('dmx_services').module.register_all()
		except Exception as e:
			agent._record_error('register_all', e)


def onStart():
	return


def onCreate():
	_arm(run_now=True)
	return


def onExit():
	return


def onFrameStart(frame: int):
	global _last_rearm
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
