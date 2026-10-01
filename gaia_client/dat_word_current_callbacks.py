"""
Script DAT Callbacks

me - this DAT

scriptOp - the OP which is cooking
"""

def onSetupParameters(scriptOp: scriptDAT):
	return

def onPulse(par: Par):
	return

def onCook(scriptOp: scriptDAT):
	"""
	Called when the Script DAT needs to cook. Cycles through dat_words'
	top-20 lexicon rows, one word every cycle_seconds.
	"""
	scriptOp.clear()

	words_dat = op('dat_words')
	if words_dat is None or words_dat.numRows <= 1:
		scriptOp.text = ''
		return

	n = words_dat.numRows - 1  # exclude header row
	cycle_seconds = 4.0
	idx = 1 + int(absTime.seconds / cycle_seconds) % n
	scriptOp.text = words_dat[idx, 0].val
	return

def onGetCookLevel(scriptOp: scriptDAT) -> CookLevel:
	return CookLevel.WHEN_USED
