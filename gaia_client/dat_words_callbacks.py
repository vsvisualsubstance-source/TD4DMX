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
	Called when the Script DAT needs to cook. Top-20 Gaia lexicon words by
	count, from gaia/td/canvas's 'lexicon' field.
	"""
	scriptOp.clear()
	scriptOp.appendRow(['word', 'count'])

	src = op('topic_canvas')
	try:
		obj = json.loads(src.text) if src is not None else {}
	except (ValueError, AttributeError):
		obj = {}

	lexicon = obj.get('lexicon') or {}
	items = sorted(
		lexicon.items(),
		key=lambda kv: (kv[1] or {}).get('count', 0),
		reverse=True,
	)[:20]
	for word, info in items:
		scriptOp.appendRow([word, str((info or {}).get('count', 0))])
	return

def onGetCookLevel(scriptOp: scriptDAT) -> CookLevel:
	return CookLevel.WHEN_USED
