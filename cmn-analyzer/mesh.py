import logging
from typing import Any, List, Tuple


logger = logging.getLogger(__name__)

# cannot use class directly as they are not defined yet, use class name instead
_node_type = {
    0x0001: "_NodeDN",          # DVM
    0x0002: "_NodeCFG",         # CFG
    0x0003: "_NodeDTC",         # DTC
    0x0004: "_NodeHNI",         # HN-I
    0x0005: "_NodeHNF",         # HN-F
    0x0006: "_NodeMXP",         # XP
    0x0007: "_NodeSBSX",        # SBSX
    0x0008: "_NodeHNF_MPAM_S",  # HN-F_MPAM_S
    0x0009: "_NodeHNF_MPAM_NS", # HN-F_MPAN_NS
    0x000A: "_NodeRNI",         # RN-I
    0x000D: "_NodeRND",         # RN-D
    0x000F: "_NodeRN_SAM",      # RN-SAM
    0x0011: "_NodeHN_P",        # HN-P (no document)
    0x0103: "_NodeCCG_RA",      # CCG_RA
    0x0104: "_NodeCCG_HA",      # CCG_HA
    0x0105: "_NodeCCLA",        # CCLA
    0x0106: "_NodeCCLA_RNI",    # CCLA_RNI (no document)
    0x1000: "_NodeAPB",         # APB
}

_device_type = {
    0b00000: "Reserved",
    0b00001: "RN-I",
    0b00010: "RN-D",
    0b00011: "Reserved",
    0b00100: "RN-F_CHIB",
    0b00101: "RN-F_CHIB_ESAM",
    0b00110: "RN-F_CHIA",
    0b00111: "RN-F_CHIA_ESAM",
    0b01000: "HN-T",
    0b01001: "HN-I",
    0b01010: "HN-D",
    0b01011: "HN-P",
    0b01100: "SN-F_CHIC",
    0b01101: "SBSX",
    0b01110: "HN-F",
    0b01111: "SN-F_CHIE",
    0b10000: "SN-F_CHID",
    0b10001: "CXHA",
    0b10010: "CXRA",
    0b10011: "CXRH",
    0b10100: "RN-F_CHID",
    0b10101: "RN-F_CHID_ESAM",
    0b10110: "RN-F_CHIC",
    0b10111: "RN-F_CHIC_ESAM",
    0b11000: "RN-F_CHIE",
    0b11001: "RN-F_CHIE_ESAM",
    0b11010: "Reserved",
    0b11011: "Reserved",
    0b11100: "MTSX",
    0b11101: "HN-V",
    0b11110: "CCG",
    0b11111: "Reserved",
}

class _NodeBase:
    def __init__(self, parent, node_info, reg_base:int) -> None:
        self.parent = parent
        self.iodrv = parent.iodrv
        self.reg_base = reg_base
        # por_xxx_node_info
        self.node_id = node_info.bits(16, 31)
        self.logical_id = node_info.bits(32, 47)
        # por_xxx_child_info
        child_info = self.iodrv.read(reg_base + 0x80)
        self.child_count = child_info.bits(0, 15)
        self.child_ptr_offset = child_info.bits(16, 31)

class _NodeDN(_NodeBase): type = "DVM"
class _NodeDTC(_NodeBase): type = "DTC"
class _NodeHNI(_NodeBase): type = "HN-I"
class _NodeHNF(_NodeBase): type = "HN-F"
class _NodeSBSX(_NodeBase): type = "SBSX"
class _NodeHNF_MPAM_S(_NodeBase): type = "HN-F_MPAM_S"
class _NodeHNF_MPAM_NS(_NodeBase): type = "HN-F_MPAN_NS"
class _NodeRNI(_NodeBase): type = "RN-I"
class _NodeRND(_NodeBase): type = "RN-D"
class _NodeRN_SAM(_NodeBase): type = "RN-SAM"
class _NodeHN_P(_NodeBase): type = "HN-P"
class _NodeCCG_RA(_NodeBase): type = "CCG_RA"
class _NodeCCG_HA(_NodeBase): type = "CCG_HA"
class _NodeCCLA(_NodeBase): type = "CCLA"
class _NodeCCLA_RNI(_NodeBase): type = "CCLA_RNI"
class _NodeAPB(_NodeBase): type = "APB"

class _NodeCFG(_NodeBase):
    type = "CFG"
    def __init__(self, parent, node_info) -> None:
        super().__init__(parent, node_info, reg_base=0)
        self.xp_list = []
        # scan xp
        logging.debug(f'found {self.child_count} cross points')
        for i in range(self.child_count):
            child_ptr_offset = self.child_ptr_offset + i*8
            child_ptr = self.iodrv.read(child_ptr_offset)
            xp_node_offset = child_ptr.bits(0, 29)
            is_external = child_ptr.bits(31, 31)
            if is_external:
                logger.warning('ignore external node from root')
                continue
            xp_node_info = self.iodrv.read(xp_node_offset)
            assert xp_node_info.bits(0, 15) == 0x0006  # XP
            self.xp_list.append(_NodeMXP(self, xp_node_info, xp_node_offset))

class _NodeMXP(_NodeBase):
    type = "XP"
    def __init__(self, parent, node_info, reg_base:int) -> None:
        logging.debug('Probing cross point ...')
        super().__init__(parent, node_info, reg_base)
        assert (self.node_id & 7) == 0 and (self.node_id >> 11) == 0
        logging.debug(f'nodeid = {self.node_id}')
        port_count = node_info.bits(48, 51)
        logging.debug(f'ports = {port_count}')
        # ports: [("dev_type", dev_count)], dev_count may be 0
        self.ports = self._probe_ports(port_count, reg_base)
        # nodes: [_NodeHNF(), _NodeRND(), ...], RNF/SNF not in nodes
        self.nodes = self._probe_devices(reg_base)
        logging.debug('---------------------------')

    def _probe_ports(self, port_count:int, reg_base:int) \
        -> List[Tuple[str, int]]:
        # XXX: shall we scan all the 6 port? it depends on whether there will
        #      be "holes"? e.g., port0 and port2 has device, but not port1
        ports = []
        for i in range(port_count):
            # por_mxp_device_port_connect_info_p0-5
            port_conn_info = self.iodrv.read(reg_base + 8 + i*8)
            # XXX: fail loudly if device type not suported
            dev_type = _device_type[port_conn_info.bits(0, 4)]
            # por_mxp_p0-5_info
            port_info = self.iodrv.read(reg_base + 0x900 + i*16)
            dev_count = port_info.bits(0, 2)
            ports.append((dev_type, dev_count))
            if dev_count > 0:
                # strip extensions for log output: RN-F_CHID_ESAM -> RN-F
                dev_type = dev_type.split('_', 1)[0]
                logging.debug(f'p{i}: {dev_type}, {dev_count}')
        return ports

    def _probe_devices(self, reg_base:int) -> List[_NodeBase]:
        logging.debug(f'childs = {self.child_count}')
        nodes = []
        for i in range(self.child_count):
            child_ptr_off = reg_base + self.child_ptr_offset + i*8
            child_ptr = self.iodrv.read(child_ptr_off)
            dev_node_offset = child_ptr.bits(0, 29)
            is_external = child_ptr.bits(31, 31)
            if is_external:
                logger.warning(f'XP{self.node_id}:ignore external node')
                continue
            dev_node_info = self.iodrv.read(dev_node_offset)
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
        self.iodrv = iodrv
        node_info = iodrv.read(0)
        assert node_info.bits(0, 15) == 0x0002  # CFG
        self.root_node = _NodeCFG(self, node_info)

    # depth first search sub-nodes recursively
    @classmethod
    def _walk_node(cls, node, visitor):
        for child in node.children:
            cls._walk_node(child, visitor)
        visitor(node)

    def _get_xy_dim(self):
        # XXX: dirty knowledge from linux arm-cmn driver
        # - x-dim = xp.logical_id if xp.node_id == 8
        # - x-dim = 1 if not exists(xp.node_id == 8)
        class DimVisitor:
            def __init__(self):
                self.xdim = 1
                self.xp_count = 0
            def __call__(self, node):
                if node.type_name == _XpNode.type_name:
                    self.xp_count += 1
                    if node.nid == 8:
                        self.xdim = node.lid
        dim_visitor = DimVisitor()
        Mesh._walk_node(self.root_node, dim_visitor)
        self.xdim = dim_visitor.xdim
        self.ydim = dim_visitor.xp_count // self.xdim
        assert self.xdim * self.ydim == dim_visitor.xp_count
        assert 0 < self.xdim <= 16
        assert 0 < self.ydim <= 16
        logging.debug(f'xdim = {self.xdim}, ydim = {self.ydim}')

    # calculate x,y for each node, we CANNOT do it during the discovery process
    # because x,y dimension is not known until all XPs are probed, what a mess!
    def _calc_node_xy(self):
        class XyVisitor:
            def __call__(self, node):
                node.x, node.y = xy_from_nid(node.nid)
                assert 0 <= node.x < mesh.xdim
                assert 0 <= node.y < mesh.ydim
        mesh = self
        xy_bit_len = (max(self.xdim, self.ydim) - 1).bit_length()
        if xy_bit_len < 2: xy_bit_len = 2
        y_bit_range = (3, 3+xy_bit_len-1)
        x_bit_range = (3+xy_bit_len, 3+2*xy_bit_len-1)
        xy_from_nid = lambda nid: (_extract_bits(nid, *x_bit_range),
                                   _extract_bits(nid, *y_bit_range))
        Mesh._walk_node(self.root_node, XyVisitor())
