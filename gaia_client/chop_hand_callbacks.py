"""
Script CHOP Callbacks

me - this DAT

scriptOp - the OP which is cooking
"""

from typing import Any
import numpy as np

def onSetupParameters(scriptOp: scriptCHOP):
	return

def onPulse(par: Any):
	return

CATEGORY = '/hand/'
BUDGET = 200

# Source row indexes, rebuilt only when oscin_mocap's channel list changes:
# scanning its ~4k channel names every frame cost ~2.5 ms (2026-09-30).
_rows = {'key': None, 'idx': np.zeros(0, dtype=np.int64)}

def sourceRows(src: CHOP) -> np.ndarray:
	"""Row indexes of the hand channels in src, cached per channel layout."""
	n = src.numChans
	key = (n, src[0].name, src[n - 1].name) if n else (0, '', '')
	if _rows['key'] != key:
		pos = {c.name: i for i, c in enumerate(src.chans())}
		names = sorted(name for name in pos if CATEGORY in name)[:BUDGET]
		_rows['idx'] = np.array([pos[name] for name in names], dtype=np.int64)
		_rows['key'] = key
	return _rows['idx']

def onCook(scriptOp: scriptCHOP):
	"""
	Called when the Script CHOP needs to cook.

	Bounded pool over oscin_mocap's raw hand (left+right) channels -- same
	deterministic size-capped-slice approach as chop_pose (see its comment).
	"""
	scriptOp.clear()
	src = op('oscin_mocap')
	if src is None:
		return

	# explicit names: copyNumpyArray(baseName=) numbers from 1, the
	# published contract numbers from 0 ('h0' is the first channel)
	idx = sourceRows(src)
	scriptOp.numSamples = 1
	for i, v in enumerate(src.numpyArray()[idx, -1].tolist()):
		scriptOp.appendChan('h%d' % i)[0] = v
	return

def onGetCookLevel(scriptOp: scriptCHOP) -> CookLevel:
	return CookLevel.WHEN_USED
