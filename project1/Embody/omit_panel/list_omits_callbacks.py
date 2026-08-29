# Omit-panel exclusions list. Rows come from the panel's storage
# ('omit_rows': [[op_path, label, par_name], ...] written by
# EmbodyExt.RefreshOmitPanel); col 0 = label, col 1 = remove (×).
# Clicking × removes that tdn_omit tag via OmitPanelRemove.

TEXT = (0.92, 0.92, 0.92, 1)
MUTED = (0.60, 0.61, 0.60, 1)
BG = (0.11, 0.12, 0.115, 1)

def _rows():
	return parent().fetch('omit_rows', [], search=False)

def onInitTable(comp, attribs):
	attribs.bgColor = BG
	attribs.textColor = TEXT
	attribs.fontSizeX = 12
	attribs.rowHeight = 24
	attribs.textOffsetX = 4
	attribs.textJustify = JustifyType.CENTERLEFT
	return

def onInitCol(comp, col, attribs):
	if col == 1:
		attribs.colWidth = 28
		attribs.textJustify = JustifyType.CENTER
	else:
		attribs.colWidth = 100
		attribs.colStretch = True
	return

def onInitCell(comp, row, col, attribs):
	rows = _rows()
	if not rows:
		if row == 0 and col == 0:
			attribs.text = '(none yet)'
			attribs.textColor = MUTED
		return
	if row >= len(rows):
		return
	if col == 0:
		attribs.text = rows[row][1]
	else:
		attribs.text = '×'
		attribs.textColor = MUTED
	return

def onSelect(comp, startRow, startCol, startCoords, endRow, endCol, endCoords, start, end):
	if not end:
		return
	rows = _rows()
	if endRow is None or endRow < 0 or endRow >= len(rows):
		return
	if endCol == 1:
		r = rows[endRow]
		kind = r[3] if len(r) > 3 else 'par'
		parent.Embody.OmitPanelRemove(r[0], r[2], kind)
	return
