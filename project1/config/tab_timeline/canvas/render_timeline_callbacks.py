def onSetupParameters(scriptOp):
	return


def onCook(scriptOp):
	parent.Config.op('tab_timeline/timeline_ui').module.render(scriptOp)
	return
