"""
Script DAT Callbacks

me - this DAT

scriptOp - the OP which is cooking
"""

import json

def onSetupParameters(scriptOp: scriptDAT):
	return

def onPulse(par: Par):
	return

def onCook(scriptOp: scriptDAT):
	"""
	Called when the Script DAT needs to cook. Gaia's latest LLM "thought"
	string, from gaia/td/canvas's 'thought' field.
	"""
	scriptOp.clear()

	src = op('topic_canvas')
	try:
		obj = json.loads(src.text) if src is not None else {}
	except (ValueError, AttributeError):
		obj = {}

	scriptOp.text = obj.get('thought') or ''
	return

def onGetCookLevel(scriptOp: scriptDAT) -> CookLevel:
	return CookLevel.WHEN_USED
