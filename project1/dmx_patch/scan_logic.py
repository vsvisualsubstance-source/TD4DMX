"""DMX scan logic -- turns the Art-Net DAT poll table (artnet_nodes) into the
`ports` table: one row per DMX OUTPUT port found on the network, with the
Art-Net address (net/subnet/universe) the patch needs to send to it.

`ports` keeps every port ever seen (online=0 when missing from the last scan)
so a rig patched to a node that is momentarily off keeps its configuration.

Art-Net 4 (ArtPollReply): PortTypes bit7 = port can output DMX; SwOut low
nibble = universe; NetSwitch / SubSwitch = net / subnet; Status1 bit1 =
node is RDM capable. RDM itself is not implemented (no RDM node to test on).
"""
import ast
import time

COLUMNS = ['port_id', 'label', 'ip', 'node', 'port', 'net', 'subnet', 'universe', 'rdm', 'online', 'last_seen']


def _bytes(cell):
	try:
		v = ast.literal_eval(str(cell))
		return [int(x) for x in v]
	except Exception:
		return []


def _int(cell, default=0):
	try:
		return int(float(str(cell)))
	except Exception:
		return default


def scan():
	comp = parent()
	nodes = op('artnet_nodes')
	nodes.par.localaddress = comp.par.Localaddress.eval()
	comp.par.Scanstatus = 'scanning...'
	nodes.par.poll.pulse()


def on_poll_complete():
	comp = parent()
	nodes = op('artnet_nodes')
	ports = op('ports')
	if ports.numRows == 0 or ports[0, 0] is None or ports[0, 0].val != 'port_id':
		ports.clear()
		ports.appendRow(COLUMNS)

	known = {ports[r, 'port_id'].val: r for r in range(1, ports.numRows)}
	for r in range(1, ports.numRows):
		ports[r, 'online'] = 0

	now = time.strftime('%Y-%m-%d %H:%M:%S')
	n_nodes = 0
	rdm_nodes = []
	head = [c.val for c in nodes.row(0)] if nodes.numRows else []
	for r in range(1, nodes.numRows):
		row = {h: nodes[r, h].val for h in head}
		n_nodes += 1
		ip = row.get('ip', '')
		name = row.get('lname') or row.get('sname') or ip
		net = _int(row.get('netswitch'))
		sub = _int(row.get('subswitch'))
		rdm = 1 if (_int(row.get('status1')) & 0x02) else 0
		if rdm:
			rdm_nodes.append(name)
		ptypes = _bytes(row.get('porttypes'))
		swout = _bytes(row.get('swout'))
		nports = _int(row.get('nports'))
		for i in range(min(nports, len(ptypes), 4)):
			if not (ptypes[i] & 0x80):
				continue  # not a DMX output port
			uni = (swout[i] & 0x0F) if i < len(swout) else 0
			pid = '%s:%d' % (ip, i + 1)
			label = '%s - porta %d - U %d:%d:%d (%s)' % (name, i + 1, net, sub, uni, ip)
			values = [pid, label, ip, name, i + 1, net, sub, uni, rdm, 1, now]
			if pid in known:
				for c, v in zip(COLUMNS, values):
					ports[known[pid], c] = v
			else:
				ports.appendRow(values)

	online = sum(1 for r in range(1, ports.numRows) if ports[r, 'online'].val == '1')
	comp.par.Nodesfound = n_nodes
	comp.par.Portsonline = online
	comp.par.Scanstatus = '%s: %d nodi, %d porte online, RDM: %s' % (
		now, n_nodes, online, ', '.join(rdm_nodes) if rdm_nodes else 'nessun nodo RDM')
	# let Gaia see the new port list (enum options of dmx_<rig>_output_port)
	svc = comp.parent().op('gaia_services/dmx_services')
	if svc is not None:
		try:
			svc.module.publish_matrix()
		except Exception as e:
			debug('publish_matrix after scan failed:', e)
