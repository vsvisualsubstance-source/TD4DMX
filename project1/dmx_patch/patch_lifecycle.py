"""dmx_patch lifecycle -- fixture catalog seed/sync, optional scan on project
start."""


def onStart():
	run("op('catalog_logic').module.ensure_seeded(); op('catalog_logic').module.sync_profiles(); "
		"op('../moving_heads/head_programmer').module.ensure_seeded()",
		fromOP=me, delayFrames=30)
	if parent().par.Scanonstart.eval():
		run("op('scan_logic').module.scan()", fromOP=me, delayFrames=60)
	return
