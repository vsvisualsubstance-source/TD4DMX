"""
Script TOP Callbacks

me - this DAT

scriptOp - the OP which is cooking
"""

import numpy

# press 'Setup Parameters' in the OP to call this function to re-create 
# the parameters.
def onSetupParameters(scriptOp: scriptTOP):
	"""
	Called to setup custom parameters for the Script TOP.
	"""
	page = scriptOp.appendCustomPage('Custom')
	p = page.appendFloat('Valuea', label='Value A')
	p = page.appendFloat('Valueb', label='Value B')
	return

def onPulse(par: Par):
	"""
	Called when a custom pulse parameter is pushed.
	
	Args:
		par: The parameter that was pulsed
	"""
	return


def onCook(scriptOp: scriptTOP):
	"""
	Called when the Script TOP needs to cook.
	"""
	a = numpy.random.randint(0, high=255, size=(2, 2, 4), dtype='uint8')
	scriptOp.copyNumpyArray(a)
	return

def onGetCookLevel(scriptOp: scriptTOP) -> CookLevel:
	"""
	Sets the scriptOp's cook level, the conditions necessary to cause a cook.

	Return one of the following:
		CookLevel.AUTOMATIC - inputs changed and output being used. 
							 TD default behavior.
		CookLevel.ON_CHANGE - inputs changed, output used or not.
		CookLevel.WHEN_USED - every frame when output is being used
		CookLevel.ALWAYS - every frame
	"""

	return CookLevel.AUTOMATIC
