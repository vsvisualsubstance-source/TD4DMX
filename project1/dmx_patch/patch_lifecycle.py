"""dmx_patch lifecycle -- optional scan on project start."""


def onStart():
	if parent().par.Scanonstart.eval():
		run("op('scan_logic').module.scan()", fromOP=me, delayFrames=60)
	return
