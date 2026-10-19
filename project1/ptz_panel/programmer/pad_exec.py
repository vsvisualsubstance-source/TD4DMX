# heads_pad moved -> programmer_view.on_pad (the user's drags move the selected heads)
def onValueChange(par, prev):
	op('programmer_view').module.on_pad(par)
	return
