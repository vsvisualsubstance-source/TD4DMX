"""
Script CHOP Callbacks

me - this DAT

scriptOp - the OP which is cooking
"""

from typing import Any

def onSetupParameters(scriptOp: scriptCHOP):
	return

def onPulse(par: Any):
	return

CATEGORY = '/meta/'

def onCook(scriptOp: scriptCHOP):
	"""
	Called when the Script CHOP needs to cook.

	Passthrough of oscin_mocap's meta/faces|hands|poses counters -- always
	exactly 3 channels, no bounding needed.
	"""
	scriptOp.clear()
	src = op('oscin_mocap')
	if src is None:
		return

	scriptOp.numSamples = 1
	for row, name in sourceRows(src):
		chan = scriptOp.appendChan(name)
		chan[0] = src[row].eval()
	return

# (source row, output name) pairs, rebuilt only when oscin_mocap's channel
# list changes: scanning ~4k channels every frame cost ~1.3 ms (2026-09-30).
_rows = {'key': None, 'pairs': []}

def sourceRows(src: CHOP) -> list:
	"""(row, name) of the meta counter channels in src, cached per channel layout."""
	n = src.numChans
	key = (n, src[0].name, src[n - 1].name) if n else (0, '', '')
	if _rows['key'] != key:
		_rows['pairs'] = [(i, c.name.split(CATEGORY, 1)[1])
			for i, c in enumerate(src.chans()) if CATEGORY in c.name]
		_rows['key'] = key
	return _rows['pairs']

def onGetCookLevel(scriptOp: scriptCHOP) -> CookLevel:
	return CookLevel.WHEN_USED
