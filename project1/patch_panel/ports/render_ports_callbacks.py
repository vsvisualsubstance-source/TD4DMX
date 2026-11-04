def onSetupParameters(scriptOp):
	return


def onCook(scriptOp):
	me.parent(2).op('ports_ui').module.render(scriptOp)
	return
