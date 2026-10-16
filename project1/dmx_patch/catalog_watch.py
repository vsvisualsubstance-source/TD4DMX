"""catalog_watch -- DAT Execute on fixture_models / fixture_types: any change
(a manual edit in TD, or a write by catalog_logic) re-derives the group
profile tables and republishes dmx_matrix to Gaia, once per frame however
many cells changed. sync_profiles() is idempotent, so the extra pass after a
catalog_logic write costs nothing."""

_pending = False


def _after_change():
	global _pending
	_pending = False
	cat = op('catalog_logic').module
	try:
		cat.sync_profiles()
	except Exception as e:
		debug('sync_profiles:', e)
	svc = parent().parent().op('gaia_services/dmx_services')
	if svc is not None:
		try:
			svc.module.publish_matrix()
		except Exception as e:
			debug('publish_matrix:', e)


def onTableChange(dat, prevDAT, info):
	global _pending
	if not _pending:
		_pending = True
		run("me.module._after_change()", fromOP=me, delayFrames=1)
	return
