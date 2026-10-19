# every frame (throttled inside): programmer state -> heads_pad / heads_text
def onFrameStart(frame):
	op('programmer_view').module.sync()
	return
