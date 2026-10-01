"""PTZ logic -- decodes mediapipe pose from Gaia channel 7 and keeps the latest
pose per person (GAIA_INTERFACE.md "Canale 7"):

  /gaia/mocap/{device_id}/pose/{person_id} -> 33 landmarks x (x, y, z,
  visibility), ONE message, INTERLEAVED (132 floats). x, y normalized 0-1,
  origin TOP-LEFT, y grows DOWNWARD (image convention).

landmark_uv() returns the chosen body point as (u, v) with v pointing UP
(v = 1 - y), optionally mirrored, so the same uv -> pan/tilt mapping serves
both the XY pad and the mocap (see targets_callbacks).
"""
import math
import time

# MediaPipe Pose landmark indexes (left/right = the performer own side)
LANDMARKS = {
	'nose': (0,),
	'shoulders': (11, 12),
	'body_center': (11, 12, 23, 24),
	'left_wrist': (15,),
	'right_wrist': (16,),
	'left_index': (19,),
	'right_index': (20,),
}
STRIDE = 4          # x, y, z, visibility
N_POINTS = 33
PERSON_TTL_S = 1.0  # a person disappears 1 s after its last pose message

_persons = {}       # person_id -> {'pts': [132 floats], 't': time}
_device = ''
_last_msg = 0.0


def on_osc(address, args):
	"""From osc_mocap callbacks: keep the latest pose per person."""
	global _device, _last_msg
	parts = address.strip('/').split('/')
	# gaia mocap <device> pose <person>
	if len(parts) != 5 or parts[0] != 'gaia' or parts[1] != 'mocap' or parts[3] != 'pose':
		return
	want = str(parent().par.Sender.eval()).strip()
	if want and parts[2] != want:
		return
	if len(args) < STRIDE * N_POINTS:
		return
	try:
		pid = int(parts[4])
	except ValueError:
		return
	now = time.time()
	_persons[pid] = {'pts': [float(a) for a in args[:STRIDE * N_POINTS]], 't': now}
	_device = parts[2]
	_last_msg = now


def _alive():
	now = time.time()
	for k in [k for k, v in _persons.items() if now - v['t'] > PERSON_TTL_S]:
		del _persons[k]
	return _persons


def landmark_uv():
	"""(u, v) of the chosen landmark for the chosen person, or None."""
	comp = parent()
	persons = _alive()
	if not persons:
		return None
	pid = int(comp.par.Person.eval())
	if pid not in persons:
		pid = min(persons)
	pts = persons[pid]['pts']
	idx = LANDMARKS.get(str(comp.par.Landmark.eval()), LANDMARKS['body_center'])
	thr = float(comp.par.Visibility.eval())
	xs, ys = [], []
	for i in idx:
		x, y, _z, vis = pts[i * STRIDE: i * STRIDE + STRIDE]
		if vis >= thr:
			xs.append(x)
			ys.append(y)
	if not xs:
		return None
	u = sum(xs) / len(xs)
	v = 1.0 - sum(ys) / len(ys)
	if comp.par.Mirror.eval():
		u = 1.0 - u
	return (max(0.0, min(1.0, u)), max(0.0, min(1.0, v)))


def simulated_uv(t):
	"""Synthetic body point for tests: slow figure-8 inside the frame."""
	return (0.5 + 0.3 * math.sin(t * 0.6), 0.5 + 0.2 * math.sin(t * 1.2))


def status():
	comp = parent()
	if comp.par.Simulate.eval():
		return 'SIMULAZIONE attiva (nessun mocap reale)'
	persons = _alive()
	if not _last_msg:
		return 'nessun messaggio pose ricevuto (accendere Mocap diretto da Admin verso questo TD)'
	age = time.time() - _last_msg
	return '%s - %d persone - ultimo messaggio %.1f s fa' % (_device or '?', len(persons), age)
