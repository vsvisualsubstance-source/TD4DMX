"""
Zero-config LAN discovery of the Gaia broker host via gaia_beacon (UDP
8899, GAIA_DISCOVER protocol, documented in the gaia repo's
docs/discovery-protocol.md). Ported from TD-Gaia's proven
Bridge/gaia_config/beacon_discovery.py, trimmed to Brokerhost only (this
component has no OSC-out consumer that would need a mirrored "Corehost").

WHAT IT COVERS: only Brokerhost. Every _PROBE_INTERVAL_S, `beacon_probe`
(the UDP Out DAT this module is docked to) sends 'GAIA_DISCOVER' to
255.255.255.255:8899 -- a genuine LAN BROADCAST, not a probe of whatever
Brokerhost currently holds (`beacon_probe.par.address` is the constant
'255.255.255.255', verified live 2026-09-29: TD's udpoutDAT broadcasts
with no SO_BROADCAST wrangling needed and no exception). Any device that
answers as service=='gaia-core' corrects Brokerhost to the reported
mqtt_host -- this finds Core on a fresh, never-configured deployment with
zero prior Brokerhost value, not just re-validates a value already close
to right. Broadcast is subnet-local by nature: it never crosses a router,
which is exactly why _maybe_failover_tailscale below exists as the next
tier when this LAN is not Core's LAN. Windows note (from the UDP Out DAT
doc): a strict Windows Firewall can block this; if broadcast discovery
never finds Core on a machine that should reach it, check the firewall
before assuming the network topology is the problem.

FRAMING GOTCHA (cost real debugging time to find on TD-Gaia, will bite
again if re-derived from scratch): the beacon's reply is bare JSON with NO
line terminator, so the UDP Out DAT's Row/Callback Format must be 'One Per
Byte' -- 'One Per Line'/'One Per Message' never see a closed line and
onReceive never fires with a complete message. Buffer byte-by-byte and
attempt json.loads() on every arrival; a valid dict closes the message.
"""
import json
import time

_PROBE_INTERVAL_S = 30.0
_last_probe = 0.0

_rx_buffer = ''
_RX_BUFFER_MAX = 4096  # guard against a buffer that never closes

# Tailscale fallback (GAIA_INTERFACE.md section 3, 2026-08-29): LAN always
# stays primary (this module never stops trying it), Tailscale only kicks
# in when the LAN path has given no evidence of working for a while AND
# neither MQTT client is actually connected. Starts at import/reinit time,
# not epoch 0 -- otherwise the very first frame after a hot-reload would
# read as "decades of silence" and fail over immediately.
_TAILSCALE_FAILOVER_S = 90.0  # ~3 missed LAN beacon probes
_last_beacon_reply = time.time()


def _enabled(cfg):
	try:
		return bool(cfg.par.Beacondiscovery.eval())
	except Exception:
		return False


def resolve():
	"""Call every frame from an Execute DAT onFrameStart -- throttled
	internally, retries forever every _PROBE_INTERVAL_S (self-healing if
	Core's IP drifts while TD is already running). Tailscale failover is
	checked on the same throttled cadence, independent of the
	Beacondiscovery toggle -- setting Tailscalehost is itself the opt-in
	(same reasoning Beacondiscovery uses: never act without a deliberate
	signal from the user)."""
	global _last_probe
	probe = op('beacon_probe')
	if probe is None:
		return
	cfg = probe.parent()
	now = time.time()
	if (now - _last_probe) < _PROBE_INTERVAL_S:
		return
	_last_probe = now
	_maybe_failover_tailscale(cfg, now)
	if _enabled(cfg):
		probe.send('GAIA_DISCOVER')


def _maybe_failover_tailscale(cfg, now):
	"""LAN prima di Tailscale: only switches Brokerhost to Tailscalehost
	when the LAN path is demonstrably not working (no beacon reply heard
	AND neither mqtt client connected) and a fallback host is configured.
	Never blocks -- if Tailscalehost is blank, this is a no-op and the
	component simply stays disconnected until the LAN broker comes back,
	same as before this fallback existed."""
	try:
		ts_host = cfg.par.Tailscalehost.eval()
	except Exception:
		return
	if not ts_host or cfg.par.Brokerhost.eval() == ts_host:
		return
	mqtt_ingest = cfg.op('mqtt_ingest')
	mqtt_device = cfg.op('mqtt_device')
	any_connected = (
		(mqtt_ingest is not None and mqtt_ingest.isConnected) or
		(mqtt_device is not None and mqtt_device.isConnected))
	if any_connected or (now - _last_beacon_reply) < _TAILSCALE_FAILOVER_S:
		return
	cfg.par.Brokerhost.val = ts_host
	cfg.par.Beaconstatus.val = 'fallback: Tailscale %s (LAN unreachable %.0fs)' % (
		ts_host, now - _last_beacon_reply)
	print('[GAIA Beacon] LAN unreachable for %.0fs, falling back to Tailscale host: %s' % (
		now - _last_beacon_reply, ts_host))


def onReceive(dat, rowIndex, message, bytes, peer):
	"""UDP Out DAT callback, one byte at a time -- see the framing note
	above for why this isn't a complete message per call."""
	global _rx_buffer
	if not _enabled(dat.parent()):
		_rx_buffer = ''
		return
	_rx_buffer += message
	if len(_rx_buffer) > _RX_BUFFER_MAX:
		_rx_buffer = ''
		return
	try:
		reply = json.loads(_rx_buffer)
	except (ValueError, TypeError):
		return  # not a complete JSON message yet, keep buffering
	_rx_buffer = ''
	_apply_reply(dat.parent(), reply)


def _apply_reply(cfg, reply):
	global _last_beacon_reply
	if reply.get('service') != 'gaia-core':
		return
	host = reply.get('mqtt_host')
	if not host:
		return
	_last_beacon_reply = time.time()

	changed = cfg.par.Brokerhost.eval() != host
	if changed:
		cfg.par.Brokerhost.val = host

	stamp = time.strftime('%H:%M:%S')
	cfg.par.Beaconstatus.val = 'auto: %s (beacon @ %s, %s)' % (
		host, reply.get('hostname', '?'), stamp)
	if changed:
		print('[GAIA Beacon] Brokerhost -> %s' % host)
	return
