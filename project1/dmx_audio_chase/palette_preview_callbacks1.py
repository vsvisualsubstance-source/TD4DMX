
import numpy as np

def onSetupParameters(scriptOp):
	return

def onCook(scriptOp):
	ALL_PALETTES = {'Rainbow (Daslight)': [(0, 0, 255), (0, 255, 255), (0, 255, 0), (255, 255, 0), (255, 128, 0), (255, 0, 0), (0, 0, 255)], 'Warm': [(255, 0, 0), (255, 90, 0), (255, 170, 0), (255, 220, 0), (255, 90, 0), (255, 0, 0)], 'Cool': [(0, 0, 255), (0, 140, 255), (0, 255, 200), (120, 0, 255), (0, 0, 255)], 'Fire': [(255, 0, 0), (255, 100, 0), (255, 180, 0), (255, 40, 0), (255, 0, 0)], 'Fire Inverted': [(0, 255, 255), (0, 155, 255), (0, 75, 255), (0, 215, 255), (0, 255, 255)], 'Ocean': [(0, 0, 180), (0, 130, 180), (0, 210, 160), (0, 130, 180), (0, 0, 180)], 'Magenta-Cyan': [(255, 0, 150), (150, 0, 255), (0, 150, 255), (0, 255, 200), (255, 0, 150)], 'Plasma': [(13, 8, 135), (126, 3, 168), (204, 71, 120), (248, 149, 64), (240, 249, 33), (13, 8, 135)], 'Basic': [(255, 0, 0), (0, 0, 255), (255, 255, 0), (0, 255, 0), (255, 0, 255), (255, 0, 0)], 'Basic 2': [(255, 0, 0), (0, 0, 255), (255, 255, 0), (0, 255, 0), (255, 0, 255)], 'Neon Party': [(255, 0, 120), (0, 60, 255), (180, 255, 0), (255, 210, 0), (255, 0, 120)], 'Sunset': [(0, 0, 150), (120, 0, 180), (255, 0, 120), (255, 90, 0), (255, 200, 0), (0, 0, 150)], 'Forest': [(0, 100, 0), (60, 180, 0), (170, 220, 0), (0, 180, 120), (0, 100, 0)], 'Deep Purple': [(60, 0, 120), (140, 0, 200), (255, 0, 150), (80, 0, 255), (60, 0, 120)], 'Red': [(255, 0, 0), (255, 0, 0)], 'Blue': [(0, 0, 255), (0, 0, 255)], 'Yellow': [(255, 255, 0), (255, 255, 0)], 'Amber': [(255, 150, 0), (255, 150, 0)]}
	DEFAULT_PALETTE_NAME = 'Rainbow (Daslight)'
	STEPPED_PALETTES = {'Basic 2'}
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
