
def onStart():
	return

def onCreate():
	return

def onExit():
	return

def onFrameStart(frame):
	_parent = me.parent()
	g = _parent.op('dmx_generator')
	pp = _parent.op('pixel_preview')
	if g is None or pp is None:
		return
	try:
		r = g['bar1_red'][0] / 255.0
		gr = g['bar1_green'][0] / 255.0
		b = g['bar1_blue'][0] / 255.0
		# in un profilo senza canale dimmer il livello e' gia' dentro l'RGB
		dch = g['bar1_dimmer']
		d = (dch[0] / 255.0) if dch is not None else 1.0
		pp.par.colorr = r * d
		pp.par.colorg = gr * d
		pp.par.colorb = b * d
	except:
		pass
	return

def onFrameEnd(frame):
	return

def onPlayStateChange(state):
	return

def onDeviceChange():
	return

def onProjectPreSave():
	return

def onProjectPostSave():
	return
