"""DMX interfaces other than Art-Net (Enttec USB Pro / Pro Mk2 / Generic
Serial). One row of the `interfaces` table = one physical interface = one
DMX universe:

  id          short name (usb1); its port in `ports` is "usb:<id>"
  label       free text shown in the port menus
  type        DMX Out CHOP Interface: enttecusbpro | enttecusbpromk2 | serial
  device      DMX Out CHOP Device ('*' = the first one found)
  serialport  COM port, type serial only
  universe    Plancia universe (1-based, U1 = Art-Net 0:0:0) it outputs
  enabled     1 = send

Every interface is a row of `ports` (kind usb, net 0 / subnet 0 / universe-1,
online = its DMX Out connected to the device) so fixtures can be patched to
it, and it OUTPUTS the whole Plancia universe: every sendable fixture on any
port of that universe, Art-Net or USB. A show patched on an Art-Net node at
U1 plays on a USB interface set to U1 without repatching.

Art-Net still goes through select_artnet -> dmx_out + routing (ports of kind
artnet only). The per-interface ops select_<id> -> dmxout_<id> (tag
dmx_iface) are created / updated / removed by sync() from the table.

Localaddress is machine specific: ensure_local_address() replaces a value
that is not an address of this PC with one on the Art-Net network
(2.x.x.x, else 10.x.x.x, else '' = OS default).
"""
import time

TYPES = ('enttecusbpro', 'enttecusbpromk2', 'serial')
TAG = 'dmx_iface'
NO_DEVICE = 'Could not connect'
# ops of interface i at (X_SELECT, Y0 - i * DY) and (X_OUT, ...)
X_SELECT, X_OUT, Y0, DY = 2000, 2400, -1200, 200


def _flag(v):
	return str(v).strip().lower() in ('1', 'true', 'on', 'yes')


def _int(v, default=0):
	try:
		return int(float(str(v)))
	except Exception:
		return default


def interfaces():
	"""[{id, name, label, type, device, serialport, universe, enabled}]."""
	t = op('interfaces')
	out = []
	if t is None or t.numRows < 2:
		return out
	head = [c.val for c in t.row(0)]
	for r in range(1, t.numRows):
		g = {h: t[r, h].val.strip() for h in head}
		iid = g.get('id', '')
		if not iid:
			continue
		typ = g.get('type') or 'enttecusbpro'
		out.append({
			'id': iid, 'name': tdu.validName(iid), 'label': g.get('label') or iid,
			'type': typ if typ in TYPES else 'enttecusbpro',
			'device': g.get('device') or '*', 'serialport': g.get('serialport', ''),
			'universe': max(1, _int(g.get('universe'), 1)), 'enabled': _flag(g.get('enabled'))})
	return out


def port_id(iid):
	return 'usb:%s' % iid


def stream_name(ifc):
	"""universe_build channel feeding this interface."""
	return 'usb_%s' % ifc['name']


def ensure_ports_schema(ports, columns):
	"""Header of `ports` = columns; adds a missing `kind` column (old tables
	only had Art-Net rows)."""
	if ports.numRows == 0 or ports[0, 0] is None or ports[0, 0].val != 'port_id':
		ports.clear()
		ports.appendRow(columns)
		return
	if ports[0, 'kind'] is None:
		ports.appendCol(['kind'] + ['artnet'] * (ports.numRows - 1))


def _connected(out):
	return bool(out.par.active.eval()) and NO_DEVICE not in out.warnings()


def sync_outputs():
	"""select_<id> -> dmxout_<id> for every row of `interfaces`; removes the
	ops of rows that are gone."""
	home = parent()
	src = op('universe_build')
	wanted = set()
	for i, ifc in enumerate(interfaces()):
		n = ifc['name']
		sel = op('select_' + n)
		if sel is None:
			sel = home.create(selectCHOP, 'select_' + n)
			sel.tags.add(TAG)
		out = op('dmxout_' + n)
		if out is None:
			out = home.create(dmxoutCHOP, 'dmxout_' + n)
			out.tags.add(TAG)
			for d in list(out.docked):  # routing table: Art-Net/sACN only
				d.destroy()
		wanted.update((sel.name, out.name))
		y = Y0 - i * DY
		sel.nodeX, sel.nodeY, out.nodeX, out.nodeY = X_SELECT, y, X_OUT, y
		if not sel.inputs or sel.inputs[0] != src:
			sel.inputConnectors[0].connect(src)
		if not out.inputs or out.inputs[0] != sel:
			out.inputConnectors[0].connect(sel)
		sel.par.channames = stream_name(ifc)
		out.par.interface = ifc['type']
		out.par.format = 'packetperchan'
		out.par.routingtable = ''
		out.par.rate.expr = 'parent().par.Rate'
		if ifc['type'] == 'serial':
			out.par.serialport = ifc['serialport']
		try:
			out.par.device = ifc['device']
		except Exception as e:
			debug('dmxout_%s device %r: %s' % (n, ifc['device'], e))
		if ifc['enabled']:
			out.par.active.expr = 'parent().par.Output'
		else:
			out.par.active = False
	for o in home.findChildren(tags=[TAG], depth=1):
		if o.name not in wanted:
			o.destroy()


def sync_ports(probe=True):
	"""One `ports` row (kind usb) per interface; rows of removed interfaces
	are dropped (their fixtures show no_port). probe=False keeps the previous
	online flag (a DMX Out just (re)configured has not cooked yet)."""
	ports = op('ports')
	cols = op('scan_logic').module.COLUMNS
	ensure_ports_schema(ports, cols)
	now = time.strftime('%Y-%m-%d %H:%M:%S')
	keep = set()
	for ifc in interfaces():
		pid = port_id(ifc['id'])
		keep.add(pid)
		out = op('dmxout_' + ifc['name'])
		row = ports.row(pid)
		last = ports[pid, 'last_seen'].val if row else ''
		if probe:
			online = 1 if (ifc['enabled'] and out is not None and _connected(out)) else 0
		else:
			online = 1 if (ifc['enabled'] and row and ports[pid, 'online'].val == '1') else 0
		values = {'port_id': pid, 'ip': '', 'node': ifc['label'], 'port': 1,
			'label': '%s - USB - U 0:0:%d' % (ifc['label'], ifc['universe'] - 1),
			'net': 0, 'subnet': 0, 'universe': ifc['universe'] - 1, 'rdm': 0,
			'online': online, 'last_seen': now if online else last, 'kind': 'usb'}
		if not row:
			ports.appendRow([values.get(c, '') for c in cols])
		else:
			for c in cols:
				ports[pid, c] = values.get(c, '')
	for r in range(ports.numRows - 1, 0, -1):
		if ports[r, 'kind'].val == 'usb' and ports[r, 'port_id'].val not in keep:
			ports.deleteRow(r)


def ensure_local_address():
	"""Localaddress valid on THIS PC (see module doc). Returns it."""
	comp = parent()
	cur = str(comp.par.Localaddress.eval()).strip()
	addrs = list(op('dmx_out').par.localaddress.menuNames)
	if not cur or not addrs or cur in addrs:
		return cur
	pick = next((a for a in addrs if a.startswith('2.')), None) \
		or next((a for a in addrs if a.startswith('10.')), '')
	comp.par.Localaddress = pick
	debug('Localaddress %s non e\' di questo PC -> %s' % (cur, pick or 'default OS'))
	return pick


def refresh_status():
	"""USB online flags follow the device connection (a DMX Out reports it
	only after cooking, hence the delay from sync)."""
	sync_ports()


def sync():
	"""Everything above: called on start, on `interfaces` edits, after scan."""
	ensure_local_address()
	sync_outputs()
	sync_ports(probe=False)
	run("op('interface_logic').module.refresh_status()", fromOP=me, delayFrames=30)
