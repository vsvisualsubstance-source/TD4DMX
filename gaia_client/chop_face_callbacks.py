"""
Script CHOP Callbacks

me - this DAT

scriptOp - the OP which is cooking
"""

from typing import Any
import re
import numpy as np

def onSetupParameters(scriptOp: scriptCHOP):
	return

def onPulse(par: Any):
	return

CATEGORY = '/face/'
PERSON_BUDGET = 2   # '/face/{person}/{region}{idx}' -- person IS a clean
                    # segment here (unlike pose/hand), so we bound by person
                    # count instead of an arbitrary channel slice.

def onCook(scriptOp: scriptCHOP):
	"""
	Called when the Script CHOP needs to cook.

	Bounded pool over oscin_mocap's raw face-mesh-contour channels
	('/face/{person}/{region}{idx}', region in eye_left/eye_right/
	eyebrow_left/eyebrow_right/lips/nose/oval). Keeps the first
	PERSON_BUDGET person ids (sorted) in full; drops the rest. This bounds
	output size regardless of how many stale person ids accumulate in
	oscin_mocap over a session (no automatic expiry there).
	"""
	scriptOp.clear()
	src = op('oscin_mocap')
	if src is None:
		return

	# explicit names: copyNumpyArray(baseName=) numbers from 1, the
	# published contract numbers from 0 ('f0' is the first channel)
	idx = sourceRows(src)
	scriptOp.numSamples = 1
	for i, v in enumerate(src.numpyArray()[idx, -1].tolist()):
		scriptOp.appendChan('f%d' % i)[0] = v
	return

# Source row indexes, rebuilt only when oscin_mocap's channel list changes:
# parsing its ~4k channel names every frame cost ~11.5 ms (2026-09-30).
_rows = {'key': None, 'idx': np.zeros(0, dtype=np.int64)}

def sourceRows(src: CHOP) -> np.ndarray:
	"""Row indexes of the face contour channels in src, in output order, cached per channel layout."""
	n = src.numChans
	key = (n, src[0].name, src[n - 1].name) if n else (0, '', '')
	if _rows['key'] == key:
		return _rows['idx']

	# region -> {numeric_idx -> source row}. Sorting the remainder as
	# a STRING scrambles contour order (e.g. 'eye_left11' < 'eye_left2') --
	# split the trailing digits out and sort numerically so consecutive
	# output values trace the actual contour in order.
	by_person = {}
	name_re = re.compile(r'([a-zA-Z_]+)(\d+)$')
	for row, c in enumerate(src.chans()):
		if CATEGORY not in c.name:
			continue
		seg = c.name.split(CATEGORY, 1)[1]
		parts = seg.split('/', 1)
		if len(parts) != 2:
			continue
		person, rest = parts
		m = name_re.match(rest)
		if not m:
			continue
		region, idx = m.group(1), int(m.group(2))
		by_person.setdefault(person, {}).setdefault(region, {})[idx] = row

	rows = []
	for person in sorted(by_person)[:PERSON_BUDGET]:
		regions = by_person[person]
		for region in sorted(regions):
			rows.extend(regions[region][idx] for idx in sorted(regions[region]))
	_rows['idx'] = np.array(rows, dtype=np.int64)
	_rows['key'] = key
	return _rows['idx']

def onGetCookLevel(scriptOp: scriptCHOP) -> CookLevel:
	return CookLevel.WHEN_USED
