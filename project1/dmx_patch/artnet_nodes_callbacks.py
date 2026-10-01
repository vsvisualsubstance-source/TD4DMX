"""Art-Net DAT callbacks -- the poll result is processed in scan_logic."""

from typing import List


def onPollReply(dat, device):
	return


def onPollComplete(dat, devices: List):
	op('scan_logic').module.on_poll_complete()
	return
