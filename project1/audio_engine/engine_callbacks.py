"""audio_engine parameter callbacks -- Refresh Devices pulse rescans the
system audio devices so the Input Device menu (menuSource of audio_in.par.device)
shows newly plugged cards."""


def onPulse(par):
	if par.name == 'Refreshdevices':
		op('audio_in').par.refresh.pulse()
	return
