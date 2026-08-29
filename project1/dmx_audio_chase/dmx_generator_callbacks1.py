
import math

_state = None  # stato persistito a livello di MODULO (non TD storage) --
                # fetch()/store() sull'operatore stesso creavano un cook
                # dependency loop (scriptOp dipende dal proprio storage,
                # store() lo re-invalida ogni cook): un semplice globale
                # Python nel modulo di questo DAT ha la stessa persistenza
                # tra i cook, senza toccare il grafo di dipendenze di TD.


def onSetupParameters(scriptOp):
	scriptOp.isTimeSlice = False
	return

def onCook(scriptOp):
	global _state
	scriptOp.isTimeSlice = False
	scriptOp.clear()

	# --- fixture: numero e mappa canali arrivano dalla pagina "Fixture" e
	# dalla tabella fixture_profiles, quindi si cambiano live -----------------
	_parent = scriptOp.parent()
	try:
		N_BARS = max(1, int(_parent.par.Nbars.eval()))
	except:
		N_BARS = 6
	CHANNELS = ['red', 'green', 'blue', 'white']
	try:
		_tbl = _parent.op('fixture_profiles')
		_cell = _tbl[str(_parent.par.Fixtureprofile.eval()), 'channels'] if _tbl else None
		if _cell is not None and str(_cell.val).strip():
			CHANNELS = str(_cell.val).split()
	except:
		pass
	ALL_PALETTES = {'Rainbow (Daslight)': [(0, 0, 255), (0, 255, 255), (0, 255, 0), (255, 255, 0), (255, 128, 0), (255, 0, 0), (0, 0, 255)], 'Warm': [(255, 0, 0), (255, 90, 0), (255, 170, 0), (255, 220, 0), (255, 90, 0), (255, 0, 0)], 'Cool': [(0, 0, 255), (0, 140, 255), (0, 255, 200), (120, 0, 255), (0, 0, 255)], 'Fire': [(255, 0, 0), (255, 100, 0), (255, 180, 0), (255, 40, 0), (255, 0, 0)], 'Fire Inverted': [(0, 255, 255), (0, 155, 255), (0, 75, 255), (0, 215, 255), (0, 255, 255)], 'Ocean': [(0, 0, 180), (0, 130, 180), (0, 210, 160), (0, 130, 180), (0, 0, 180)], 'Magenta-Cyan': [(255, 0, 150), (150, 0, 255), (0, 150, 255), (0, 255, 200), (255, 0, 150)], 'Plasma': [(13, 8, 135), (126, 3, 168), (204, 71, 120), (248, 149, 64), (240, 249, 33), (13, 8, 135)], 'Basic': [(255, 0, 0), (0, 0, 255), (255, 255, 0), (0, 255, 0), (255, 0, 255), (255, 0, 0)], 'Basic 2': [(255, 0, 0), (0, 0, 255), (255, 255, 0), (0, 255, 0), (255, 0, 255)], 'Neon Party': [(255, 0, 120), (0, 60, 255), (180, 255, 0), (255, 210, 0), (255, 0, 120)], 'Sunset': [(0, 0, 150), (120, 0, 180), (255, 0, 120), (255, 90, 0), (255, 200, 0), (0, 0, 150)], 'Forest': [(0, 100, 0), (60, 180, 0), (170, 220, 0), (0, 180, 120), (0, 100, 0)], 'Deep Purple': [(60, 0, 120), (140, 0, 200), (255, 0, 150), (80, 0, 255), (60, 0, 120)], 'Red': [(255, 0, 0), (255, 0, 0)], 'Blue': [(0, 0, 255), (0, 0, 255)], 'Yellow': [(255, 255, 0), (255, 255, 0)], 'Amber': [(255, 150, 0), (255, 150, 0)]}
	DEFAULT_PALETTE_NAME = 'Rainbow (Daslight)'
	STEPPED_PALETTES = {'Basic 2'}

	def get_par(comp, name, default):
		try:
			return float(comp.par[name].eval())
		except:
			return default

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
		if len(custom) >= 2:
			PALETTE = custom + [custom[0]]  # richiude il ciclo sul primo colore
		else:
			PALETTE = ALL_PALETTES[DEFAULT_PALETTE_NAME]
		STEPPED = False
	else:
		PALETTE = ALL_PALETTES.get(palette_name, ALL_PALETTES[DEFAULT_PALETTE_NAME])
		STEPPED = palette_name in STEPPED_PALETTES

	MIN_DIMMER = get_par(p, 'Mindimmer', 30)
	MAX_DIMMER = get_par(p, 'Maxdimmer', 255)
	DIMMER_BOOST = get_par(p, 'Dimmerboost', 1.0)
	GLOBAL_SMOOTH = get_par(p, 'Globalsmooth', 1.0)
	SMOOTH_FACTOR = max(0.001, min(1.0, get_par(p, 'Smoothfactor', 0.12) * GLOBAL_SMOOTH))
	COLOR_CURVE = get_par(p, 'Colorcurve', 0.6)
	COLOR_SMOOTH = max(0.001, min(1.0, get_par(p, 'Colorsmooth', 0.25) * GLOBAL_SMOOTH))
	COLOR_SPEED = max(0.001, min(1.0, get_par(p, 'Colorspeed', 0.2) * GLOBAL_SMOOTH))
	COLOR_PHASE = get_par(p, 'Colorphase', 0.0)
	BAR_PHASE = get_par(p, 'Barphase', 0.0)
	AGC_RELEASE = get_par(p, 'Agcrelease', 0.0008)
	MIN_RANGE = get_par(p, 'Minrange', 0.02)
	KICK_ENABLE = get_par(p, 'Kickenable', 1.0 if True else 0.0) > 0.5
	KICK_THRESH = get_par(p, 'Kickthresh', 0.35)
	KICK_BOOST = get_par(p, 'Kickboost', 100.0)
	KICK_DECAY = get_par(p, 'Kickdecay', 0.75)
	KICK_COOLDOWN = get_par(p, 'Kickcooldown', 0.22)
	KICK_SMOOTH = max(0.001, min(1.0, get_par(p, 'Kicksmooth', 0.3) * GLOBAL_SMOOTH))
	DIMMER_GAMMA = get_par(p, 'Dimmergamma', 2.2)
	HAS_DIMMER = 'dimmer' in CHANNELS

	def band_level(chop):
		if chop is None or chop.numChans == 0:
			return 0.0
		vals = chop[0].vals
		if len(vals) == 0:
			return 0.0
		return sum(abs(v) for v in vals) / len(vals)

	def palette_color(t, palette, stepped=False):
		t = t % 1.0  # ciclico: con la fase attiva puo' avvolgersi oltre l'ultimo colore
		if stepped:
			# palette a blocchi netti: nessuna sfumatura, taglio secco tra un colore
			# e l'altro. Usa solo i colori "distinti" (se il primo e l'ultimo
			# coincidono, quello finale e' solo la chiusura del ciclo, non conta)
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

	bass_raw = band_level(scriptOp.inputs[0]) if len(scriptOp.inputs) > 0 else 0.0
	mid_raw  = band_level(scriptOp.inputs[1]) if len(scriptOp.inputs) > 1 else 0.0
	high_raw = band_level(scriptOp.inputs[2]) if len(scriptOp.inputs) > 2 else 0.0

	st = _state
	if st is None:
		st = {'bass_env': 0.0, 'mid_env': 0.0, 'high_env': 0.0, 'smooth_level': 0.0,
		       'level_min': None, 'level_max': None,
		       'smooth_r': [0.0] * N_BARS, 'smooth_g': [0.0] * N_BARS, 'smooth_b': [0.0] * N_BARS,
		       'prev_bass_env': 0.0, 'punch': 0.0, 'punch_smooth': 0.0, 'last_kick_time': 0.0,
		       'color_t_smooth': 0.0}

	# --- il numero di fixture e' live: se cambia, ridimensiona lo stato per
	# barra invece di andare in IndexError al primo cook dopo la modifica ----
	for _k in ('smooth_r', 'smooth_g', 'smooth_b'):
		_cur = st[_k]
		if len(_cur) < N_BARS:
			_cur.extend([0.0] * (N_BARS - len(_cur)))
		elif len(_cur) > N_BARS:
			del _cur[N_BARS:]

	a = 0.35  # smoothing envelope grezzo (0-1, piu' alto = piu' reattivo)
	st['bass_env'] = st['bass_env'] * (1 - a) + bass_raw * a
	st['mid_env']  = st['mid_env']  * (1 - a) + mid_raw  * a
	st['high_env'] = st['high_env'] * (1 - a) + high_raw * a

	total = min(1.0, st['bass_env'] * 1.2 + st['mid_env'] * 0.5 + st['high_env'] * 0.3)
	st['smooth_level'] += (total - st['smooth_level']) * SMOOTH_FACTOR

	# --- normalizzazione automatica (AGC): impara da sola il min/max reale
	# del brano che sta suonando, cosi' la palette viene sempre sfruttata
	# tutta, qualunque sia il volume/compressione della sorgente -------------
	level = st['smooth_level']
	if st['level_min'] is None:
		st['level_min'] = level
		st['level_max'] = level + 1e-6

	if level > st['level_max']:
		st['level_max'] = level
	else:
		st['level_max'] += (level - st['level_max']) * AGC_RELEASE

	if level < st['level_min']:
		st['level_min'] = level
	else:
		st['level_min'] += (level - st['level_min']) * AGC_RELEASE

	rng = max(st['level_max'] - st['level_min'], MIN_RANGE)  # floor: sotto MIN_RANGE = silenzio,
	                                                          # non si amplifica il rumore di fondo
	level_norm = max(0.0, min(1.0, (level - st['level_min']) / rng))  # livello 0-1
	                                                                    # relativo al brano (AGC), usato dal dimmer
	color_t = (level - st['level_min']) / rng
	color_t = max(0.0, min(1.0, color_t)) ** COLOR_CURVE
	color_t = (color_t + COLOR_PHASE) % 1.0  # ruota la mappatura sulla palette

	# --- Color Speed: il PUNTO sulla palette insegue color_t con la sua
	# propria velocita', indipendente dal dimmer. Smoothing circolare (non
	# lineare) per gestire correttamente il giro 0.98 -> 0.02 senza scatti --
	diff = (color_t - st['color_t_smooth'] + 0.5) % 1.0 - 0.5
	st['color_t_smooth'] = (st['color_t_smooth'] + diff * COLOR_SPEED) % 1.0
	color_t = st['color_t_smooth']

	# --- rilevatore di kick: guarda la VARIAZIONE dei bassi (non il volume
	# assoluto) relativa al range del brano (AGC), quindi si adatta da solo
	# a generi/tracce diverse invece di essere tarato su un singolo tipo ------
	now = absTime.seconds
	bass_delta = st['bass_env'] - st['prev_bass_env']
	st['prev_bass_env'] = st['bass_env']

	if KICK_ENABLE and bass_delta > KICK_THRESH * rng and (now - st['last_kick_time']) > KICK_COOLDOWN and st['punch'] < 0.3:
		st['punch'] = 1.0
		st['last_kick_time'] = now
	else:
		st['punch'] *= KICK_DECAY

	# --- lente generale sopra tutta la logica del punch: ammorbidisce sia
	# l'attacco (niente salto istantaneo a piena vampata) sia la coda -------
	st['punch_smooth'] += (st['punch'] - st['punch_smooth']) * KICK_SMOOTH

	level_boosted = max(0.0, min(1.0, level_norm * DIMMER_BOOST))  # guadagno extra sul dimmer
	dimmer_val = MIN_DIMMER + level_boosted * (MAX_DIMMER - MIN_DIMMER)  # AGC-normalizzato + boost
	dimmer_val = max(MIN_DIMMER, min(MAX_DIMMER, dimmer_val))
	dimmer_val = min(255.0, dimmer_val + st['punch_smooth'] * KICK_BOOST)

	scriptOp.numSamples = 1
	for i in range(N_BARS):
		# --- fase tra le barre: ognuna legge un punto diverso della palette,
		# spostato di i*BAR_PHASE rispetto alle altre (0 = tutte identiche) ---
		bar_t = (color_t + i * BAR_PHASE) % 1.0
		r_raw, g_raw, b_raw = palette_color(bar_t, PALETTE, stepped=STEPPED)

		# --- fade indipendente per barra: anche se bar_t salta, il colore
		# effettivo in uscita insegue morbidamente (niente cambi a scatti) ---
		st['smooth_r'][i] += (r_raw - st['smooth_r'][i]) * COLOR_SMOOTH
		st['smooth_g'][i] += (g_raw - st['smooth_g'][i]) * COLOR_SMOOTH
		st['smooth_b'][i] += (b_raw - st['smooth_b'][i]) * COLOR_SMOOTH
		r_val, g_val, b_val = st['smooth_r'][i], st['smooth_g'][i], st['smooth_b'][i]

		# --- garanzia anti-bianco: rimuove la componente "grigia" condivisa,
		# almeno un canale resta sempre a 0, il bianco non puo' MAI comparire -
		m = min(r_val, g_val, b_val)
		r_val -= m
		g_val -= m
		b_val -= m

		# --- se il profilo HA un canale dimmer, l'RGB resta pieno e a dimmerare
		# ci pensa la fixture. Se NON ce l'ha (es. 4CH RGBW), il livello va
		# moltiplicato dentro l'RGB, con gamma per non perdere la parte bassa -
		k = 1.0 if HAS_DIMMER else (dimmer_val / 255.0) ** DIMMER_GAMMA

		values = {
			'dimmer': dimmer_val,
			'red':    r_val * k,
			'green':  g_val * k,
			'blue':   b_val * k,
		}
		for ch in CHANNELS:
			chan_name = 'bar{:d}_{}'.format(i + 1, ch)
			c = scriptOp.appendChan(chan_name)
			# ruolo non gestito (white/amber/uv/strobe/mode/speed/macro...) -> 0
			c[0] = max(0.0, min(255.0, values.get(ch, 0.0)))

	# --- canali di debug: NON fanno parte dell'indirizzamento DMX, servono
	# solo per controllare nel monitor cosa sta facendo l'audio / il Perlin --
	for name, val in [('debug_bass', st['bass_env']),
	                   ('debug_mid', st['mid_env']),
	                   ('debug_high', st['high_env']),
	                   ('debug_level', st['smooth_level']),
	                   ('debug_color_t', color_t),
	                   ('debug_punch', st['punch']),
	                   ('debug_punch_smooth', st['punch_smooth'])]:
		c = scriptOp.appendChan(name)
		c[0] = val

	_state = st
	return
