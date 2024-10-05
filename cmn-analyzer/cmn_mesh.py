from __future__ import annotations

import logging
from typing import Dict, List, Tuple

from cmn_iodrv import CmnRegister


logger = logging.getLogger(__name__)

# por_xxx_node_info
_node_type = {
    0x0001: 'NodeDN',           # DVM
    0x0002: 'NodeCFG',          # CFG
    0x0003: 'NodeDTC',          # DTC
    0x0004: 'NodeHNI',          # HN-I
    0x0005: 'NodeHNF',          # HN-F
    0x0006: 'NodeMXP',          # XP
    0x0007: 'NodeSBSX',         # SBSX
    0x0008: 'NodeHNF_MPAM_S',   # HN-F_MPAM_S
    0x0009: 'NodeHNF_MPAM_NS',  # HN-F_MPAN_NS
    0x000A: 'NodeRNI',          # RN-I
    0x000D: 'NodeRND',          # RN-D
    0x000F: 'NodeRN_SAM',       # RN-SAM
    0x0011: 'NodeHN_P',         # HN-P (no document)
    0x0103: 'NodeCCG_RA',       # CCG_RA
    0x0104: 'NodeCCG_HA',       # CCG_HA
    0x0105: 'NodeCCLA',         # CCLA
    0x0106: 'NodeCCLA_RNI',     # CCLA_RNI (no document)
    0x1000: 'NodeAPB',          # APB
}

# por_mxp_device_port_connect_info_p0-5
_device_type = {
    0b00000: 'Reserved',
    0b00001: 'RN-I',
    0b00010: 'RN-D',
    0b00011: 'Reserved',
    0b00100: 'RN-F_CHIB',
    0b00101: 'RN-F_CHIB_ESAM',
    0b00110: 'RN-F_CHIA',
    0b00111: 'RN-F_CHIA_ESAM',
    0b01000: 'HN-T',
    0b01001: 'HN-I',
    0b01010: 'HN-D',
    0b01011: 'HN-P',
    0b01100: 'SN-F_CHIC',
    0b01101: 'SBSX',
    0b01110: 'HN-F',
    0b01111: 'SN-F_CHIE',
    0b10000: 'SN-F_CHID',
    0b10001: 'CXHA',
    0b10010: 'CXRA',
    0b10011: 'CXRH',
    0b10100: 'RN-F_CHID',
    0b10101: 'RN-F_CHID_ESAM',
    0b10110: 'RN-F_CHIC',
    0b10111: 'RN-F_CHIC_ESAM',
    0b11000: 'RN-F_CHIE',
    0b11001: 'RN-F_CHIE_ESAM',
    0b11010: 'Reserved',
    0b11011: 'Reserved',
    0b11100: 'MTSX',
    0b11101: 'HN-V',
    0b11110: 'CCG',
    0b11111: 'Reserved',
}


class _NodeBase:
    '''
    exported members:
    - parent:     xp parent is mesh, node parent is xp
    - node_id:    cmn node id
    - logical_id: cmn logical id
    - p:          port id
    - d:          device id
    internal members:
    - _iodrv:     io driver to read cmn registers
    - _reg_base:  base address of node register space
    '''
    type = 'NA'
    def __init__(self, parent, node_info, reg_base:int) -> None:
        self.parent = parent
        self._iodrv = parent._iodrv
        self._reg_base = reg_base
        # por_xxx_node_info
        self.node_id = node_info[16, 31]
        assert self.node_id < 4096
        self.logical_id = node_info[32, 47]
        # por_xxx_child_info
        child_info = self.read_off(0x80)
        self._child_count = child_info[0, 15]
        self._child_ptr_offset = child_info[16, 31]

    # extract port/device no from node_id, not used by CFG and MXP
    def update_port_device_no(self, port_count) -> None:
        pd = self.node_id & 7
        if port_count <= 2:
            p, d = pd >> 2, pd & 3
        else:
            p, d = pd >> 1, pd & 1
        self.p, self.d = p, d

    # read at node offset
    def read_off(self, reg:int) -> CmnRegister:
        return self._iodrv.read(self._reg_base + reg)

    # write at node offset
    def write_off(self, reg:int, value:int) -> None:
        self._iodrv.write(self._reg_base + reg, value)


class NodeDN(_NodeBase): type = 'DVM'
class NodeHNI(_NodeBase): type = 'HN-I'
class NodeHNF(_NodeBase): type = 'HN-F'
class NodeSBSX(_NodeBase): type = 'SBSX'
class NodeHNF_MPAM_S(_NodeBase): type = 'HN-F_MPAM_S'
class NodeHNF_MPAM_NS(_NodeBase): type = 'HN-F_MPAN_NS'
class NodeRNI(_NodeBase): type = 'RN-I'
class NodeRND(_NodeBase): type = 'RN-D'
class NodeRN_SAM(_NodeBase): type = 'RN-SAM'
class NodeHN_P(_NodeBase): type = 'HN-P'
class NodeCCG_RA(_NodeBase): type = 'CCG_RA'
class NodeCCG_HA(_NodeBase): type = 'CCG_HA'
class NodeCCLA(_NodeBase): type = 'CCLA'
class NodeCCLA_RNI(_NodeBase): type = 'CCLA_RNI'
class NodeAPB(_NodeBase): type = 'APB'


class NodeCFG(_NodeBase):
    '''
    exported members:
    - xps[x][y]: 2D array saves all cross points in mesh
      * xdim = len(xps)
      * ydim = len(xps[0])
      * xps[i][j] -> NodeMXP at mesh coordinate (i, j)
      * is_multi_dtm -> multiple dtm in xp with more than 2 ports
    '''
    type = 'CFG'
    def __init__(self, parent, node_info) -> None:
        super().__init__(parent, node_info, reg_base=0)
        xp_list = self._probe_xp()
        self.xps = self._xp_list_to_array(xp_list)
        self.multi_dtm_enabled = self._multi_dtm_enabled()

    def _probe_xp(self) -> List[NodeMXP]:
        xp_list = []
        logging.debug(f'found {self._child_count} cross points')
        for i in range(self._child_count):
            child_ptr_offset = self._child_ptr_offset + i*8
            child_ptr = self.read_off(child_ptr_offset)
            xp_node_offset = child_ptr[0, 29]
            is_external = child_ptr[31]
            if is_external:
                logger.warning('ignore external node from root')
                continue
            xp_node_info = self.read_off(xp_node_offset)
            assert xp_node_info[0, 15] == 0x0006  # XP
            xp_list.append(NodeMXP(self, xp_node_info, xp_node_offset))
        return xp_list

    def _xp_list_to_array(self, xp_list) -> List[List[NodeMXP]]:
        def _get_mesh_dimension() -> Tuple[int, int]:
            # XXX: dirty knowledge from linux arm-cmn driver
            # - x-dim = xp.logical_id if xp.node_id == 8
            # - x-dim = 1 if not exists(xp.node_id == 8)
            xdim = 1
            for xp in xp_list:
                if xp.node_id == 8:
                    xdim = xp.logical_id
                    break
            ydim = len(xp_list) // xdim
            assert xdim * ydim == len(xp_list)
            assert 0 < xdim <= 16
            assert 0 < ydim <= 16
            return xdim, ydim

        xdim, ydim = _get_mesh_dimension()
        logging.debug(f'dimension: x = {xdim}, y = {ydim}')
        # caclulate x, y for all cross points and populate xps[x,y] 2D array
        xps = [[None] * ydim for _ in range(xdim)]
        for xp in xp_list:
            xp.update(xdim, ydim)
            xps[xp.x][xp.y] = xp
        return xps   # type: ignore

    def _multi_dtm_enabled(self) -> bool:
        multi_dtm_enabled = self.read_off(0x900)[63]
        if multi_dtm_enabled:
            logging.warning('detected multiple dtm, unsupported')
        return multi_dtm_enabled != 0


class NodeMXP(_NodeBase):
    '''
    exported members:
    - port_devs[]: type and number of devices connected to all ports
      * len(port_devs) -> number of ports with devices connected
      * port_devs[i]   -> (_device_type:str, device_count:int) at i-th port
      * NOTE: device_count may be 0, ignore these devices
    - x, y: coordinate of this xp in mesh
    - child_nodes: a dict tells child nodes associated with a device
      * multiple child nodes can be found for a single device
        NOTE: por_mxp_p0-5_info says there's one device attached to a port
              but there can be multiple child nodes to that port/device
              e.g., a HN-F device can have three nodes associated:
                    HN-F, HN-F_MPAM_S and HN-F_MPAM_NS
      * key = (port_id, device_id)
      * val = list of child nodes for this device, may be empty for SNF/RNF
    - dtc_domain: dtc domain this MXP belongs to
    '''
    type = 'XP'
    def __init__(self, parent, node_info, reg_base:int) -> None:
        logging.debug('Probing cross point ...')
        super().__init__(parent, node_info, reg_base)
        # least 3 bits (port, device) of XP node id must be 0
        assert (self.node_id & 7) == 0
        logging.debug(f'nodeid = {self.node_id}')
        port_count = node_info[48, 51]
        logging.debug(f'ports = {port_count}')
        # dtc domain
        self.dtc_domain = self._get_dtc_domain()
        logging.debug(f'dtc = {self.dtc_domain}')
        # port_devs: [('dev_type', dev_count)], dev_count may be 0
        self.port_devs = self._probe_ports(port_count)
        # _child_nodes: [_NodeHNF(), _NodeRND(), ...], RNF/SNF not included
        self._child_nodes = self._probe_devices()
        logging.debug('---------------------------')

    def get_dev_node_id(self, p:int, d:int) -> int:
        port_count = len(self.port_devs)
        if port_count <= 2:
            assert 0 <= p <= 1 and 0 <= d <= 3
            node_id = (p << 2) | d
        else:
            assert 0 <= p <= 3 and 0 <= d <= 1
            node_id = (p << 1) | d
        node_id += self.node_id
        # verify node_id against info from child node
        # NOTE: SNF, RNF may not have related child node
        child_nodes = self.child_nodes[(p, d)]
        if child_nodes:
            assert node_id == child_nodes[0].node_id
        return node_id

    def update(self, xdim:int, ydim:int) -> None:
        logging.debug(f'Updating cross point {self.node_id} ...')
        self.x, self.y = self._update_xypd(xdim, ydim)
        # child_nodes: {(port_id, dev_id): [nodes]}
        self.child_nodes = self._populate_child_nodes()
        logging.debug('~~~~~~~~~~~~~~~~~~~~~~~~~~~')

    def reset(self) -> None:
        # clear registers
        zero_regs = (
            0x2100,                                  # por_dtm_control(stop dt)
            0x2210,                                  # por_dtm_pmu_config
            0x2000,                                  # por_mxp_pmu_event_sel
            0x21A0, 0x21A0+24, 0x21A0+48, 0x21A0+72, # por_dtm_wp0-3_config
            0x21A8, 0x21A8+24, 0x21A8+48, 0x21A8+72, # por_dtm_wp0-3_val
            0x21B0, 0x21B0+24, 0x21B0+48, 0x21B0+72, # por_dtm_wp0-3_mask
            0x2220,                                  # por_dtm_pmevcnt
            0x2240,                                  # por_dtm_pmevcntsr
        )
        for reg in zero_regs:
            self.write_off(reg, 0)
        # clear por_dtm_fifo_entry_ready
        self.write_off(0x2118, 0b1111)

    # calculate x,y of all cross points and p,d for all child nodes
    def _update_xypd(self, xdim:int, ydim:int) -> Tuple[int, int]:
        xshift = (max(xdim, ydim) - 1).bit_length()
        if xshift < 2: xshift = 2
        xy_id = self.node_id >> 3
        x = xy_id >> xshift
        y = xy_id & ((1 << xshift) - 1)
        logging.debug(f'x = {x}, y = {y}')
        for node in self._child_nodes:
            node.update_port_device_no(len(self.port_devs))
        return x, y

    def _populate_child_nodes(self) -> Dict[Tuple[int, int], List[_NodeBase]]:
        child_nodes = {}
        for p, (dev_type, dev_count) in enumerate(self.port_devs):
            logging.debug(f'port{p}: type={dev_type}, dev_count={dev_count}')
            for d in range(dev_count):
                child_nodes[(p, d)] = []
        for i, node in enumerate(self._child_nodes):
            if (node.p, node.d) not in child_nodes:
                logging.debug('ignore out of bound child node '
                                f'at XP{self.node_id} port{node.p} '
                                f'device{node.d} {node.type}')
                continue
            logging.debug(f'child{i}: p={node.p}, d={node.d}, '
                          f'dev_type={self.port_devs[node.p][0]}, '
                          f'node_type={node.type}')
            child_nodes[(node.p, node.d)].append(node)
        return child_nodes

    def _probe_ports(self, port_count:int) \
        -> List[Tuple[str, int]]:
        # XXX: shall we scan all the 6 port? it depends on whether there will
        #      be "holes"? e.g., port0 and port2 has device, but not port1
        port_devs = []
        for i in range(port_count):
            # por_mxp_device_port_connect_info_p0-5
            port_conn_info = self.read_off(8 + i*8)
            # fail loud if device type not suported
            dev_type = _device_type[port_conn_info[0, 4]]
            # por_mxp_p0-5_info
            port_info = self.read_off(0x900 + i*16)
            dev_count = port_info[0, 2]
            port_devs.append((dev_type, dev_count))
            if dev_count > 0:
                # strip extensions for log output: RN-F_CHID_ESAM -> RN-F
                dev_type = dev_type.split('_', 1)[0]
                logging.debug(f'p{i}: {dev_type}, {dev_count}')
        return port_devs

    def _probe_devices(self) -> List[_NodeBase]:
        logging.debug(f'childs = {self._child_count}')
        nodes = []
        for i in range(self._child_count):
            child_ptr = self.read_off(self._child_ptr_offset + i*8)
            dev_node_offset = child_ptr[0, 29]
            is_external = child_ptr[31]
            if is_external:
                logger.warning(f'XP{self.node_id}:ignore external node')
                continue
            dev_node_info = self._iodrv.read(dev_node_offset)
            dev_node_type = dev_node_info[0, 15]
            if dev_node_type not in _node_type:
                logger.warning(f'XP{self.node_id}:ignore unknown node type '
                               f'0x{dev_node_type:04X}')
                continue
            dev_node_class_name = _node_type[dev_node_type]
            dev_node_class = globals()[dev_node_class_name]
            dev_node = dev_node_class(self, dev_node_info, dev_node_offset)
            nodes.append(dev_node)
        return nodes

    def _get_dtc_domain(self) -> int:
        # XXX: por_dtm_unit_info is only for port 0,1, should check
        # por_dtm_unit_info_dt1-3 for port 2~7.
        # BUT, why will ports under same XP belongs to different DTC?
        por_dtm_unit_info = self.read_off(0x960)
        return por_dtm_unit_info[0, 1]


class NodeDTC(_NodeBase):
    'exported member: domain'
    type = 'DTC'
    def __init__(self, parent, node_info, reg_base:int) -> None:
        super().__init__(parent, node_info, reg_base)
        self.domain = node_info[32, 33]

    def reset(self) -> None:
        # clear registers
        zero_regs = (
            0x0A00,                         # por_dt_dtc_ctl (stop dt)
            0x2100,                         # por_dt_pmcr    (stop pmu)
            0x0A30,                         # por_dt_trace_control
            0x2000, 0x2010, 0x2020, 0x2030, # por_dt_pmevcntAB-GH
            0x2040,                         # por_dt_pmccntr
            0x2050, 0x2060, 0x2070, 0x2080, # por_dt_pmevcntsrAB-GH
            0x2090,                         # por_dt_pmccntrsr
        )
        for reg in zero_regs:
            self.write_off(reg, 0)
        # set por_dt_pmovsr_clr[8:0] to clear counter overflow status
        self.write_off(0x2210, 0b1_1111_1111)


class Mesh:
    '''
    export members:
    - root_node: cfg rootnode
    - xps{nid:xp}: maps nodeid to NodeMXP
    - dtcs[]: list of HN-D/T nodes, indexed by DTC domain
              every XP belongs to one DTC domain (xp.dtc_domain)
    '''
    def __init__(self, iodrv) -> None:
        self._iodrv = iodrv
        node_info = iodrv.read(0)
        assert node_info[0, 15] == 0x0002  # CFG
        self.root_node = NodeCFG(self, node_info)
        self.xps = self._build_xp_dict(self.root_node)
        self.dtcs = self._build_dtc_list(self.root_node)

    def info(self):
        '''
        return mesh_info = {
          'dim': {'x': 2, 'y': 2},
          'xp': [[xp00, xp01], [xp10, xp11]]
        }         |
                  |
                  +-> {
                        'x': 0,
                        'y': 0,
                        'node_id': 0,
                        'ports': [port0, port1],
                      }           |
                                  |
                                  +-> {
                                        'type': 'RN-F',
                                        'devices': [dev0, dev1]
                                      }             |
                                                    |
                                                    +-> {
                                                            'p': 0,
                                                            'd': 0,
                                                            'node_id': 0,
                                                        }
        '''
        mesh_info = {}
        xps = self.root_node.xps
        mesh_info['dim'] = {'x': len(xps), 'y': len(xps[0])}
        xp_list = []
        for x, col in enumerate(xps):
            xp_list.append([])
            for y, xp in enumerate(col):
                xp_info = {
                    'x': xp.x,
                    'y': xp.y,
                    'node_id': xp.node_id,
                    'ports': [],
                }
                for p, port_dev in enumerate(xp.port_devs):
                    port_type, dev_count = port_dev
                    port_info = {
                        'type': port_type,
                        'devices': [],
                    }
                    for d in range(dev_count):
                        port_info['devices'].append({
                            'p': p,
                            'd': d,
                            'node_id': xp.get_dev_node_id(p, d),
                        })
                    xp_info['ports'].append(port_info)
                xp_list[x].append(xp_info)
        mesh_info['xp'] = xp_list
        return mesh_info

    def _build_xp_dict(self, root_node) -> Dict[int, NodeMXP]:
        xps = {}
        for xp_col in root_node.xps:
            for xp in xp_col:
                xps[xp.node_id] = xp
        return xps

    def _build_dtc_list(self, root_node) -> List[NodeDTC]:
        dtcs = []
        max_dtc_domain = -1
        # find all nodes with type = DTC
        for xp_col in root_node.xps:
            for xp in xp_col:
                max_dtc_domain = max(max_dtc_domain, xp.dtc_domain)
                for _, nodes in xp.child_nodes.items():
                    for node in nodes:
                        if node.type == 'DTC':
                            dtcs.append(node)
        assert(max_dtc_domain+1 == len(dtcs))
        # sort by dtc domain
        dtcs.sort(key=lambda dtc: dtc.domain)
        return dtcs
