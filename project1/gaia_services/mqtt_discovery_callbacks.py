"""mqtt_discovery callbacks -- delegate to touch_discovery."""


def onConnect(dat):
	op('touch_discovery').module.on_connect(dat)
	return


def onConnectFailure(dat, msg):
	debug('[Touch discovery] connect failed:', msg)
	return


def onConnectionLost(dat, msg):
	debug('[Touch discovery] connection lost:', msg)
	return


def onSubscribe(dat):
	return


def onSubscribeFailure(dat, msg):
	debug('[Touch discovery] subscribe failed:', msg)
	return


def onUnsubscribe(dat):
	return


def onUnsubscribeFailure(dat, msg):
	return


def onPublish(dat, topic):
	return


def onMessage(dat, topic, payload, qos, retained, dup):
	op('touch_discovery').module.on_message(topic, payload)
	return
