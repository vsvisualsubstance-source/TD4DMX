"""
Execute DAT

me - this DAT

Make sure the corresponding toggle is enabled in the Execute DAT.
"""

def onFrameStart(frame: int):
	"""
	Called at the start of each frame.

	Args:
		frame: The current frame number
	"""
	op('gaia_fleet_control').module.tick()
	op('beacon_discovery').module.resolve()
	return
