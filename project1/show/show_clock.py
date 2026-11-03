# every frame: advance the timeline clock and apply its state (show_logic)
def onFrameStart(frame):
	op('show_logic').module.tick()
	# head motion right after the timeline: on pan/tilt the motion wins
	op('show_logic').module.motion_tick()
	return
