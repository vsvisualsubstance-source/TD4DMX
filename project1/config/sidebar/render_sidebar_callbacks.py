def onSetupParameters(scriptOp):
	return


def onCook(scriptOp):
	parent.Config.op('config_ui').module.render_sidebar(scriptOp)
	return
