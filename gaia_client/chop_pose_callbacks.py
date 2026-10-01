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

CATEGORY = '/pose/'
BUDGET = 200

# Source row indexes, rebuilt only when oscin_mocap's channel list changes:
# scanning its ~4k channel names every frame cost ~2.4 ms (2026-09-30).
_rows = {'key': None, 'idx': np.zeros(0, dtype=np.int64)}

def sourceRows(src: CHOP) -> np.ndarray:
	"""Row indexes of the pose channels in src, cached per channel layout."""
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

	Pose OSC addresses use an unstable, non-contiguous, mixed-zero-padding
	flat index -- NOT a clean per-landmark/per-person scheme -- so this does
	not attempt semantic decoding. It just takes a deterministic, size-capped
	slice (sorted by name) so downstream cost never grows with oscin_mocap's
	own unbounded channel count.
	"""
	scriptOp.clear()
	src = op('oscin_mocap')
	if src is None:
		return

	# explicit names: copyNumpyArray(baseName=) numbers from 1, the
	# published contract numbers from 0 ('p0' is the first channel)
	idx = sourceRows(src)
	scriptOp.numSamples = 1
	for i, v in enumerate(src.numpyArray()[idx, -1].tolist()):
		scriptOp.appendChan('p%d' % i)[0] = v
	return

def onGetCookLevel(scriptOp: scriptCHOP) -> CookLevel:
	return CookLevel.WHEN_USED
