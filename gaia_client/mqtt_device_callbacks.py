"""
MQTT Client DAT Callbacks

me - this DAT
"""

def onConnect(dat: mqttclientDAT):
	op('gaia_device_agent').module.on_connect(dat)
	return

def onConnectFailure(dat: mqttclientDAT, msg: str):
	op('gaia_device_agent').module.on_connect_failure(msg)
	return

def onConnectionLost(dat: mqttclientDAT, msg: str):
	op('gaia_device_agent').module.on_connection_lost(msg)
	return

def onSubscribe(dat: mqttclientDAT):
	return

def onSubscribeFailure(dat: mqttclientDAT, msg: str):
	return

def onUnsubscribe(dat: mqttclientDAT):
	return

def onUnsubscribeFailure(dat: mqttclientDAT, msg: str):
	return

def onPublish(dat: mqttclientDAT, topic: str):
	return

def onMessage(dat: mqttclientDAT, topic: str, payload: str, qos: int,
			  retained: bool, dup: bool):
	op('gaia_device_agent').module.on_message(topic, payload)
	return
