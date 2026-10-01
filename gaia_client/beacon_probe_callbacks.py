def onReceive(dat, rowIndex, message, bytes, peer):
	op('beacon_discovery').module.onReceive(dat, rowIndex, message, bytes, peer)
	return
