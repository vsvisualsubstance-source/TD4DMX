def onSetupParameters(scriptOp):
	return


def onCook(scriptOp):
	parent.Config.op('tab_look/look_ui').module.render_preview(scriptOp)
	return
