# a timeline table changed (editor, Gaia, git checkout) -> drop the
# engine caches and refresh the inspector
def onTableChange(dat):
	m = op('show_logic').module
	# only cue / automation changes re-apply everything; a scene edit must
	# not undo live moves (Plancia heads, TD tweaks)
	m.invalidate(force=dat.name in ('cues', 'keys'))
	m.load_all()
	return
