"""osc_mocap callbacks -- every pose message goes to ptz_logic."""


def onReceiveOSC(dat, rowIndex, message, byteData, timeStamp, address, args, peer):
	op('ptz_logic').module.on_osc(address, args)
	return
