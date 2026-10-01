"""
Execute DAT

me - this DAT

Make sure the corresponding toggle is enabled in the Execute DAT.

A per-project script may call op('gaia_client/gaia_device_agent').module
.register_service()/.register_param() to expose real controls -- this file
stays identical across every project that uses gaia_client, so it deliberately
does not call into any project-specific registration module. Call your own
registration from wherever your project already runs startup code (its own
onStart/onCreate), not from here.
"""

def onFrameStart(frame: int):
	"""
	Called at the start of each frame.

	Args:
		frame: The current frame number
	"""
	op('gaia_device_agent').module.tick()
	op('gaia_device_agent').module.perf_tick()
	return
