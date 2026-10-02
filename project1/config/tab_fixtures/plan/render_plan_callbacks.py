def onSetupParameters(scriptOp):
	return


def onCook(scriptOp):
	parent.Config.op('tab_fixtures/fixture_ui').module.render_plan(scriptOp)
	return
