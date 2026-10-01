"""
Script CHOP Callbacks

me - this DAT

scriptOp - the OP which is cooking
"""

from typing import Any
import json

def onSetupParameters(scriptOp: scriptCHOP):
	return

def onPulse(par: Any):
	return

def onCook(scriptOp: scriptCHOP):
	"""
	Called when the Script CHOP needs to cook.
	"""
	scriptOp.clear()

	dat = op('topic_canvas')
	try:
		soul = json.loads(dat.text).get('soul', {}) if dat is not None else {}
	except (ValueError, AttributeError):
		soul = {}

	mood_rgb = soul.get('mood_rgb') or {}
	values = {
		'mood_r': (mood_rgb.get('r') or 0) / 255.0,
		'mood_g': (mood_rgb.get('g') or 0) / 255.0,
		'mood_b': (mood_rgb.get('b') or 0) / 255.0,
		'stress': soul.get('stress') or 0,
		'calm': soul.get('calm') or 0,
		'social': soul.get('social') or 0,
		'curiosity': soul.get('curiosity') or 0,
		'energy': (soul.get('energy') or 0) / 100.0,
		'lifeindex': (soul.get('lifeIndex') or 0) / 100.0,
	}

	scriptOp.numSamples = 1
	for name, value in values.items():
		chan = scriptOp.appendChan(name)
		chan[0] = value
	return

def onGetCookLevel(scriptOp: scriptCHOP) -> CookLevel:
	return CookLevel.WHEN_USED
