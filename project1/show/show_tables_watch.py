# a timeline table changed (editor, Gaia, git checkout) -> drop the
# engine caches and refresh the inspector
def onTableChange(dat):
	m = op('show_logic').module
	m.invalidate()
	m.load_all()
	return
