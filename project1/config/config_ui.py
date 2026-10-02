"""config_ui -- shell of the Config window (/project1/config, parent
shortcut Config): the left tab bar and the tab switch.

Tabs = the Tab menu of the Config COMP; each tab is a child panel named
tab_<name> whose display par follows Tab. Existing panels are reused, not
copied: tab_audio / tab_patch / tab_ptz are OP Viewers of audio_panel /
patch_panel / ptz_panel, tab_gaia a Parameter COMP of gaia_client.
"""
import numpy as np
import cv2

# RGBA 0-255: the panels draw into uint8 RGBA images (4x lighter than
# float32 to fill, flip and upload every cook)
BG = (13, 14, 17, 255)
ACTIVE = (41, 107, 158, 255)
HOVER = (28, 31, 36, 255)
TEXT = (224, 230, 237, 255)
DIM = (128, 135, 148, 255)
ROW_H = 56
TOP = 70


def tabs():
	p = parent.Config.par.Tab
	return list(zip(p.menuNames, p.menuLabels))


def render_sidebar(scriptOp):
	w = int(scriptOp.par.resolutionw.eval())
	h = int(scriptOp.par.resolutionh.eval())
	img = np.empty((h, w, 4), dtype=np.uint8)
	img[:] = BG
	cv2.putText(img, 'DMX CONFIG', (18, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.62, TEXT, 1, cv2.LINE_AA)
	cur = str(parent.Config.par.Tab.eval())
	sb = parent.Config.op('sidebar')
	hover = None
	if sb.panel.inside:
		hover = int(((1.0 - float(sb.panel.v)) * h - TOP) // ROW_H)
	for i, (name, label) in enumerate(tabs()):
		y0 = TOP + i * ROW_H
		if name == cur:
			cv2.rectangle(img, (0, y0), (w, y0 + ROW_H - 4), ACTIVE, -1)
		elif i == hover:
			cv2.rectangle(img, (0, y0), (w, y0 + ROW_H - 4), HOVER, -1)
		cv2.putText(img, label, (18, y0 + 34), cv2.FONT_HERSHEY_SIMPLEX, 0.58,
			TEXT if name == cur else DIM if i != hover else TEXT, 1, cv2.LINE_AA)
	scriptOp.copyNumpyArray(np.ascontiguousarray(img[::-1]))


def on_click(panel_comp):
	h = float(panel_comp.height)
	i = int(((1.0 - float(panel_comp.panel.v)) * h - TOP) // ROW_H)
	t = tabs()
	if 0 <= i < len(t):
		parent.Config.par.Tab = t[i][0]
