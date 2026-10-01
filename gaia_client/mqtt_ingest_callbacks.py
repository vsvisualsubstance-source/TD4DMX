"""
MQTT Client DAT Callbacks -- Gaia canvas/brain-state/dream ingest.

me - this DAT
"""

import json
import time

TOPIC_DATS = {
	'gaia/td/canvas': 'topic_canvas',
	'gaia/brain/state': 'topic_brainstate',
	'gaia/brain/dream': 'topic_dream',
}

def onConnect(dat: mqttclientDAT):
	parent.GaiaClient.par.Connectionstatus = 'connected'
	dat.subscribe(list(TOPIC_DATS.keys()))
	return

def onConnectFailure(dat: mqttclientDAT, msg: str):
	parent.GaiaClient.par.Connectionstatus = 'connect failed: %s' % msg
	return

def onConnectionLost(dat: mqttclientDAT, msg: str):
	parent.GaiaClient.par.Connectionstatus = 'connection lost: %s' % msg
	return

def onSubscribe(dat: mqttclientDAT):
	return

def onSubscribeFailure(dat: mqttclientDAT, msg: str):
	parent.GaiaClient.par.Connectionstatus = 'subscribe failed: %s' % msg
	return

def onUnsubscribe(dat: mqttclientDAT):
	return

def onUnsubscribeFailure(dat: mqttclientDAT, msg: str):
	return

def onPublish(dat: mqttclientDAT, topic: str):
	return

def onMessage(dat: mqttclientDAT, topic: str, payload: str, qos: int,
			  retained: bool, dup: bool):
	"""Services > Canvas Ingest gates storage/processing, never the connection
	itself -- toggling mqttclientDAT.par.active at runtime has crashed TD
	before (see gaia_device_agent.py docstring for the same lesson)."""
	if not parent.GaiaClient.par.Canvasingest.eval():
		return

	dat_name = TOPIC_DATS.get(topic)
	if dat_name is None:
		return

	# payload arrives as bytes at runtime despite the str type hint above
	raw = payload.decode('utf-8', errors='replace') if isinstance(payload, bytes) else payload

	try:
		obj = json.loads(raw)
		text = json.dumps(obj, indent=2)
	except (json.JSONDecodeError, TypeError, ValueError):
		text = raw

	target = op(dat_name)
	if target is not None:
		target.text = text

	parent.GaiaClient.par.Lastmessage = '%s @ %s' % (topic, time.strftime('%H:%M:%S'))
	# read by constant_status msg_age (status output connector)
	parent.GaiaClient.store('lastmsg_seconds', absTime.seconds)
	return
