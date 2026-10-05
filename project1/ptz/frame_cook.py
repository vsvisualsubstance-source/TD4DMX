"""frame_cook -- drives targets once per frame.

targets reads the pose from the ptz_logic module (fed by osc_mocap
callbacks), not from a CHOP input, so TD never marks it dirty: verified
live, it cooked only at startup and the heads froze while poses kept
arriving. absTime in its onCook does not make it cook every frame.
Force-cooking it here keeps the mocap tracking and the smoothing moving;
heads_dmx (select_ptz) and universe_build then follow by normal pull.
"""


def onFrameStart(frame):
	t = op('targets')
	if t is not None:
		t.cook(force=True)
	return
