
import numpy as np

def onSetupParameters(scriptOp):
	return

def onCook(scriptOp):
	# catalogo del generatore dello stesso rig (palettes.json, OPS 59); copia di ripiego se manca
	_gen = scriptOp.parent().op('dmx_generator_callbacks1')
	_m = _gen.module if _gen is not None else None
	ALL_PALETTES = getattr(_m, 'ALL_PALETTES', None) or {'Rainbow (Daslight)': [(0, 0, 255), (0, 255, 255), (0, 255, 0), (255, 255, 0), (255, 128, 0), (255, 0, 0), (0, 0, 255)]}
	DEFAULT_PALETTE_NAME = getattr(_m, 'DEFAULT_PALETTE_NAME', 'Rainbow (Daslight)')
	STEPPED_PALETTES = getattr(_m, 'STEPPED_PALETTES', {'Basic 2'})
	p = scriptOp.parent()

	try:
		palette_name = str(p.par['Palette'].eval())
	except:
		palette_name = DEFAULT_PALETTE_NAME

	if palette_name == 'Custom':
		custom = []
		for idx in range(1, 6):
			try:
				r = float(p.par['Custompalette{}r'.format(idx)].eval()) * 255.0
				g = float(p.par['Custompalette{}g'.format(idx)].eval()) * 255.0
				b = float(p.par['Custompalette{}b'.format(idx)].eval()) * 255.0
				custom.append((r, g, b))
			except:
				pass
		PALETTE = (custom + [custom[0]]) if len(custom) >= 2 else ALL_PALETTES[DEFAULT_PALETTE_NAME]
		STEPPED = False
	else:
		PALETTE = ALL_PALETTES.get(palette_name, ALL_PALETTES[DEFAULT_PALETTE_NAME])
		STEPPED = palette_name in STEPPED_PALETTES

	w = int(scriptOp.width)
	h = int(scriptOp.height)

	def palette_color(t, palette, stepped=False):
		t = t % 1.0
		if stepped:
			core = palette[:-1] if palette[0] == palette[-1] and len(palette) > 1 else palette
			idx = min(int(t * len(core)), len(core) - 1)
			return core[idx]
		n = len(palette) - 1
		seg = t * n
		i = int(seg)
		i = min(i, n - 1)
		f = seg - i
		c0 = palette[i]
		c1 = palette[min(i + 1, n)]
		r = c0[0] + (c1[0] - c0[0]) * f
		g = c0[1] + (c1[1] - c0[1]) * f
		b = c0[2] + (c1[2] - c0[2]) * f
		return (r, g, b)

	# barra sfumata (o a blocchi): un colore per colonna, ripetuto su tutta l'altezza
	row = np.array([palette_color(x / float(w), PALETTE, stepped=STEPPED) for x in range(w)],
	               dtype=np.float32) / 255.0
	img = np.tile(row[np.newaxis, :, :], (h, 1, 1))
	alpha = np.ones((h, w, 1), dtype=np.float32)
	img = np.concatenate([img, alpha], axis=2)

	# cursore: legge la posizione audio-driven attuale da dmx_generator
	try:
		cursor_t = op('dmx_generator')['debug_color_t'][0] % 1.0
	except:
		cursor_t = 0.0
	cx = int(cursor_t * w)
	half = max(1, w // 150)
	x0 = max(0, cx - half)
	x1 = min(w, cx + half)
	img[:, x0:x1, 0:3] = 1.0  # riga bianca ben visibile sopra la sfumatura

	scriptOp.copyNumpyArray(img)
	return
