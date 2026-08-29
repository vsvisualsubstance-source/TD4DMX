# Any parameter the status readout SHOWS is an event: republish, once.
# Scoped to those parameters (see the Parameters par) so unrelated Embody
# parameter traffic -- which is constant -- never redraws the panel.
#
# me.parent() rather than a relative op() path: inside a DAT, op('../x')
# resolves a level above this network and silently returns None, which is
# exactly how this callback failed quietly the first time.

def onValueChange(par, prev):
	publisher = me.parent().op('status_publish')
	if publisher is not None:
		publisher.module.Refresh()
	return
