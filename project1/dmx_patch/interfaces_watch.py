"""interfaces table edited -> rebuild the USB/serial DMX outputs and their
ports (interface_logic.sync)."""


def onTableChange(dat):
	run("op('interface_logic').module.sync()", fromOP=me, delayFrames=1)
	return
