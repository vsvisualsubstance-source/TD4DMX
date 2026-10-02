# every frame: advance the timeline clock and apply its state (show_logic)
def onFrameStart(frame):
	op('show_logic').module.tick()
	return
