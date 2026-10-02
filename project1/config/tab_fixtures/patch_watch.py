# fixtures table changed (Gaia, quick patch, another view) -> refresh
# the inspector from the table. Writes nothing back: equal values are no-ops.
def onTableChange(dat):
	parent.Config.op('tab_fixtures/fixture_ui').module.load_selected()
	return
