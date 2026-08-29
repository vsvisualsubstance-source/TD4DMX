"""
Script TOP Callbacks

me - this DAT
scriptOp - the OP which is cooking

Preview multi-bar: una colonna per ogni fixture (Nbars), colorata con
l'output REALE di dmx_generator (bar{N}_red/green/blue, con dimmer gia'
applicato se il profilo non ha un canale dimmer separato -- stessa
logica di pixel_preview_exec, ma per TUTTE le barre invece che solo la
prima). Nessun hardware richiesto: serve a vedere/tarare palette,
color speed, bar phase e kick prima di avere fixture reali collegate.
"""
import numpy as np


def onSetupParameters(scriptOp):
	return


def onCook(scriptOp):
	# scriptOp.width/.height riflette la texture GIA' allocata (puo' restare
	# bloccata su una dimensione stantia da un cook precedente), non il
	# parametro Resolution -- leggere SEMPRE i parametri direttamente cosi'
	# copyNumpyArray() ridefinisce la texture alla dimensione voluta.
	w = int(scriptOp.par.resolutionw.eval())
	h = int(scriptOp.par.resolutionh.eval())
	img = np.zeros((h, w, 4), dtype=np.float32)
	img[:, :, 3] = 1.0  # opaco

	p = scriptOp.parent()
	gen = p.op('dmx_generator')

	try:
		n_bars = max(1, int(p.par.Nbars.eval()))
	except Exception:
		n_bars = 1

	if gen is None:
		scriptOp.copyNumpyArray(img)
		return

	bar_w = w / float(n_bars)
	gap = max(1, int(bar_w * 0.08))  # piccolo margine tra le barre, scala con la larghezza

	for i in range(n_bars):
		try:
			r_ch = gen['bar{}_red'.format(i + 1)]
			g_ch = gen['bar{}_green'.format(i + 1)]
			b_ch = gen['bar{}_blue'.format(i + 1)]
			d_ch = gen['bar{}_dimmer'.format(i + 1)]
			r = (r_ch[0] / 255.0) if r_ch is not None else 0.0
			g = (g_ch[0] / 255.0) if g_ch is not None else 0.0
			b = (b_ch[0] / 255.0) if b_ch is not None else 0.0
			# profilo senza canale dimmer -> livello gia' dentro l'RGB (stessa
			# convenzione di pixel_preview_exec/dmx_generator)
			d = (d_ch[0] / 255.0) if d_ch is not None else 1.0
		except Exception:
			r = g = b = d = 0.0

		x0 = int(i * bar_w) + gap
		x1 = int((i + 1) * bar_w) - gap
		if x1 > x0:
			img[:, x0:x1, 0] = r * d
			img[:, x0:x1, 1] = g * d
			img[:, x0:x1, 2] = b * d

	scriptOp.copyNumpyArray(img)
	return


def onPulse(par):
	return
