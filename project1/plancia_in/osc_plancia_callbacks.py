"""osc_plancia callbacks -- every Plancia message goes to plancia_logic."""


def onReceiveOSC(dat, rowIndex, message, byteData, timeStamp, address, args, peer):
	op('plancia_logic').module.on_osc(address, args)
	return
