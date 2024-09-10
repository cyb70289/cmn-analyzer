from __future__ import annotations

import logging
from typing import Dict, List, Tuple


logger = logging.getLogger(__name__)

# por_xxx_node_info
_node_type = {
    0x0001: '_NodeDN',          # DVM
    0x0002: '_NodeCFG',         # CFG
    0x0003: '_NodeDTC',         # DTC
    0x0004: '_NodeHNI',         # HN-I
    0x0005: '_NodeHNF',         # HN-F
    0x0006: '_NodeMXP',         # XP
    0x0007: '_NodeSBSX',        # SBSX
    0x0008: '_NodeHNF_MPAM_S',  # HN-F_MPAM_S
    0x0009: '_NodeHNF_MPAM_NS', # HN-F_MPAN_NS
    0x000A: '_NodeRNI',         # RN-I
    0x000D: '_NodeRND',         # RN-D
    0x000F: '_NodeRN_SAM',      # RN-SAM
    0x0011: '_NodeHN_P',        # HN-P (no document)
    0x0103: '_NodeCCG_RA',      # CCG_RA
    0x0104: '_NodeCCG_HA',      # CCG_HA
    0x0105: '_NodeCCLA',        # CCLA
    0x0106: '_NodeCCLA_RNI',    # CCLA_RNI (no document)
    0x1000: '_NodeAPB',         # APB
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
        self.node_id = node_info.bits(16, 31)
        assert self.node_id < 4096
        self.logical_id = node_info.bits(32, 47)
        # por_xxx_child_info
        child_info = self._iodrv.read(reg_base + 0x80)
        self._child_count = child_info.bits(0, 15)
        self._child_ptr_offset = child_info.bits(16, 31)

    # extract port/device no from node_id, not used by CFG and MXP
    def update_port_device_no(self, port_count) -> None:
        pd = self.node_id & 7
        if port_count <= 2:
            p, d = pd >> 2, pd & 3
        else:
            p, d = pd >> 1, pd & 1
        self.p, self.d = p, d


class _NodeDN(_NodeBase): type = 'DVM'
class _NodeDTC(_NodeBase): type = 'DTC'
class _NodeHNI(_NodeBase): type = 'HN-I'
class _NodeHNF(_NodeBase): type = 'HN-F'
class _NodeSBSX(_NodeBase): type = 'SBSX'
class _NodeHNF_MPAM_S(_NodeBase): type = 'HN-F_MPAM_S'
class _NodeHNF_MPAM_NS(_NodeBase): type = 'HN-F_MPAN_NS'
class _NodeRNI(_NodeBase): type = 'RN-I'
class _NodeRND(_NodeBase): type = 'RN-D'
class _NodeRN_SAM(_NodeBase): type = 'RN-SAM'
class _NodeHN_P(_NodeBase): type = 'HN-P'
class _NodeCCG_RA(_NodeBase): type = 'CCG_RA'
class _NodeCCG_HA(_NodeBase): type = 'CCG_HA'
class _NodeCCLA(_NodeBase): type = 'CCLA'
class _NodeCCLA_RNI(_NodeBase): type = 'CCLA_RNI'
class _NodeAPB(_NodeBase): type = 'APB'


class _NodeCFG(_NodeBase):
    '''
    exported members:
    - xps[x][y]: 2D array saves all cross points in mesh
      * xdim = len(xps)
      * ydim = len(xps[0])
      * xps[i][j] -> _NodeMXP at mesh coordinate (i, j)
    '''
    type = 'CFG'
    def __init__(self, parent, node_info) -> None:
        super().__init__(parent, node_info, reg_base=0)
        xp_list = self._probe_xp()
        self.xps = self._xp_list_to_array(xp_list)

    def _probe_xp(self) -> List[_NodeMXP]:
        xp_list = []
        logging.debug(f'found {self._child_count} cross points')
        for i in range(self._child_count):
            child_ptr_offset = self._child_ptr_offset + i*8
            child_ptr = self._iodrv.read(child_ptr_offset)
            xp_node_offset = child_ptr.bits(0, 29)
            is_external = child_ptr.bits(31, 31)
            if is_external:
                logger.warning('ignore external node from root')
                continue
            xp_node_info = self._iodrv.read(xp_node_offset)
            assert xp_node_info.bits(0, 15) == 0x0006  # XP
            xp_list.append(_NodeMXP(self, xp_node_info, xp_node_offset))
        return xp_list

    def _xp_list_to_array(self, xp_list) -> List[List[_NodeMXP]]:
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


class _NodeMXP(_NodeBase):
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
    '''
    type = 'XP'
    def __init__(self, parent, node_info, reg_base:int) -> None:
        logging.debug('Probing cross point ...')
        super().__init__(parent, node_info, reg_base)
        # least 3 bits (port, device) of XP node id must be 0
        assert (self.node_id & 7) == 0
        logging.debug(f'nodeid = {self.node_id}')
        port_count = node_info.bits(48, 51)
        logging.debug(f'ports = {port_count}')
        # port_devs: [('dev_type', dev_count)], dev_count may be 0
        self.port_devs = self._probe_ports(port_count, reg_base)
        # _child_nodes: [_NodeHNF(), _NodeRND(), ...], RNF/SNF not included
        self._child_nodes = self._probe_devices(reg_base)
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
                logging.warning('ignore out of bound child node '
                                f'at XP{self.node_id} port{node.p} '
                                f'device{node.d} {node.type}')
                continue
            logging.debug(f'child{i}: p={node.p}, d={node.d}, '
                          f'dev_type={self.port_devs[node.p][0]}, '
                          f'node_type={node.type}')
            child_nodes[(node.p, node.d)].append(node)
        return child_nodes

    def _probe_ports(self, port_count:int, reg_base:int) \
        -> List[Tuple[str, int]]:
        # XXX: shall we scan all the 6 port? it depends on whether there will
        #      be "holes"? e.g., port0 and port2 has device, but not port1
        port_devs = []
        for i in range(port_count):
            # por_mxp_device_port_connect_info_p0-5
            port_conn_info = self._iodrv.read(reg_base + 8 + i*8)
            # fail loud if device type not suported
            dev_type = _device_type[port_conn_info.bits(0, 4)]
            # por_mxp_p0-5_info
            port_info = self._iodrv.read(reg_base + 0x900 + i*16)
            dev_count = port_info.bits(0, 2)
            port_devs.append((dev_type, dev_count))
            if dev_count > 0:
                # strip extensions for log output: RN-F_CHID_ESAM -> RN-F
                dev_type = dev_type.split('_', 1)[0]
                logging.debug(f'p{i}: {dev_type}, {dev_count}')
        return port_devs

    def _probe_devices(self, reg_base:int) -> List[_NodeBase]:
        logging.debug(f'childs = {self._child_count}')
        nodes = []
        for i in range(self._child_count):
            child_ptr_off = reg_base + self._child_ptr_offset + i*8
            child_ptr = self._iodrv.read(child_ptr_off)
            dev_node_offset = child_ptr.bits(0, 29)
            is_external = child_ptr.bits(31, 31)
            if is_external:
                logger.warning(f'XP{self.node_id}:ignore external node')
                continue
            dev_node_info = self._iodrv.read(dev_node_offset)
            dev_node_type = dev_node_info.bits(0, 15)
            if dev_node_type not in _node_type:
                logger.warning(f'XP{self.node_id}:ignore unknown node type '
                               f'0x{dev_node_type:04X}')
                continue
            dev_node_class_name = _node_type[dev_node_type]
            dev_node_class = globals()[dev_node_class_name]
            dev_node = dev_node_class(self, dev_node_info, dev_node_offset)
            nodes.append(dev_node)
        return nodes


class Mesh:
    def __init__(self, iodrv) -> None:
        self._iodrv = iodrv
        node_info = iodrv.read(0)
        assert node_info.bits(0, 15) == 0x0002  # CFG
        self.root_node = _NodeCFG(self, node_info)

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
