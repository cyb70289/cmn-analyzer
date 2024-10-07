import logging
import re
import signal
from abc import ABC, abstractmethod
from typing import Dict, Generator, List, Tuple

import flit.event as flit
from cmn_iodrv import CmnIodrv
from cmn_mesh import Mesh, NodeCFG, NodeMXP, NodeDTC


logger = logging.getLogger(__name__)


class Event(ABC):
    '''
    exported members:
    - mesh         int
    - xp_nid       int
    - port         int
    - channel      str:req|rsp|snp|dat
    - chn_sel      int:  0|  1|  2|  3
    - direction    str:up|down
    - group        int
    - matches      dict(str,str)
    - wp_val_mask  (int,int)
    - name         str
    '''
    def __init__(self, event_str:str) -> None:
        logging.info(f'parse event "{event_str}"')
        self._parse_event_str(event_str.lower())
        self._verify_args()
        self.wp_val_mask = self._calc_wp_val_mask()

    @abstractmethod
    def save_pmu_info(self, *args, **kwargs): pass

    def _parse_event_str(self, event_str:str) -> None:
        # mandatory args
        mesh = None
        xp_nid = None
        port = None
        channel = None
        direction = None
        # optional args
        group = None
        matches = {}
        # cmn0/xp=10,up,port=0,channel=req,opcode=all,group=0,resp=1,datasrc=7/
        event_str = event_str.lower()
        assert event_str[:3] == 'cmn'
        parts = event_str.strip('/').split('/')
        mesh = int(parts[0][3:])
        for item in parts[1].split(','):
            if '=' in item:
                key, value = item.split('=')
                if key == 'xp':
                    if xp_nid is None: xp_nid = int(value, 0)
                    else: raise Exception('duplicated xp=n')
                elif key == 'port':
                    if port is None: port = int(value, 0)
                    else: raise Exception('duplicated port=n')
                elif key == 'group':
                    if group is None: group = int(value, 0)
                    else: raise Exception('duplicated group=n')
                elif key == 'channel':
                    if channel is None: channel = value
                    else: raise Exception('duplicated channel=n')
                    valid_channels = ('req', 'rsp', 'snp', 'dat')
                    if channel not in valid_channels:
                        raise Exception(f'invalid channel: {channel}, '
                                        f'must be in {valid_channels}')
                else:
                    if key not in matches: matches[key] = value
                    else: raise Exception(f'duplicated {key}=v')
            elif item in ('up', 'down'):
                if direction is None: direction = item
                else: raise Exception('duplicated up|down')
            else:
                raise Exception(f'invalid item "{item}"')
        # make sure mandatory args are provided
        if xp_nid is None: raise Exception('missing xp=nid')
        if port is None: raise Exception('missing port=n')
        if channel is None: raise Exception('missing channel=req|rsp|snp|dat')
        if direction is None: raise Exception('missing up|down')
        # optional args
        if group is None: group = 0
        # quick validatation
        assert mesh >= 0
        assert 0 <= port < 6
        assert 0 <= group < 3
        # populate exported variables
        self.mesh, self.xp_nid, self.port = mesh, xp_nid, port
        self.channel, self.direction, self.group = channel, direction, group
        self.matches = matches
        self.chn_sel = {'req':0, 'rsp':1, 'snp':2, 'dat':3}[channel]
        # construct event name: cmn0-xp100-port1-up-grp0-req-opcode-lpid0-...
        self.name = f'cmn{mesh}-xp{xp_nid}-port{port}-{direction}' \
                    f'-grp{group}-{channel}-'
        if 'opcode' in self.matches:
            self.name += self.matches['opcode']
        else:
            self.name += 'all'
        for k, v in self.matches.items():
            if k != 'opcode':
                self.name += f'-{k}{v}'  # v must be a number

    def _calc_wp_val_mask(self) -> Tuple[int, int]:
        value, mask = \
                flit.get_wp_val_mask(self.channel, self.group, self.matches)
        logging.info(f'wp_val=0x{(value & ((1<<64)-1)):016x}, '
                     f'wp_mask=0x{(mask & ((1<<64)-1)):016x}')
        return value, mask

    def _verify_args(self) -> None:
        if self.direction == 'up' and 'srcid' in self.matches:
            raise Exception('only download watchpoint supports srcid')
        if self.direction == 'down' and 'tgtid' in self.matches:
            raise Exception('only upload watchpoint supports tgtid')


class DTC(ABC):
    def __init__(self, dtc_node:NodeDTC) -> None:
        self.dtc_node = dtc_node
        self.active_counters = 0

    def next_counter(self) -> int:
        free_counter_index = self.active_counters
        if free_counter_index >= 8:
            raise Exception('no dtc counter available')
        self.active_counters += 1
        return free_counter_index

    @abstractmethod
    def configure(self) -> None:
        pass

    # only available in dtc domain0
    def enable0(self) -> None:
        assert self.dtc_node.domain == 0
        # enable dtc
        por_dt_dtc_ctl = self.dtc_node.read_off(0xA00)
        if por_dt_dtc_ctl[0] == 0:
            por_dt_dtc_ctl[0] = 1  # dt_en
            self.dtc_node.write_off(0x0A00, por_dt_dtc_ctl.value)


class DTM(ABC):
    def __init__(self, xp_node:NodeMXP, dtc:DTC, dtc0:DTC) -> None:
        cfg_node = xp_node.parent
        n_ports = len(xp_node.port_devs)
        if cfg_node.multi_dtm_enabled and n_ports > 2:
            raise Exception('multiple dtm not suppported')
        self.xp_node = xp_node
        self.dtc = dtc
        self.dtc0 = dtc0
        self.wp_in_use = [False]*4

    @abstractmethod
    def configure(self, event:Event) -> int:
        # get free wachpoint, 0,1:upload, 2,3:download
        wp_index = 0 if event.direction == 'up' else 2
        if self.wp_in_use[wp_index]:
            wp_index += 1
        if self.wp_in_use[wp_index]:
            raise Exception('no watchpoint available')
        self.wp_in_use[wp_index] = True
        # program por_dtm_wp0-3_val, por_dtm_wp0-3_mask
        wp_val, wp_mask = event.wp_val_mask
        self.xp_node.write_off(0x21A8+24*wp_index, wp_val)
        self.xp_node.write_off(0x21B0+24*wp_index, wp_mask)
        # program por_dtm_wp0-3_config
        por_dtm_wp_config = self.xp_node.read_off(0x21A0+24*wp_index)
        assert event.port < len(self.xp_node.port_devs)
        por_dtm_wp_config[1, 3] = event.chn_sel     # wp_chn_sel
        por_dtm_wp_config[0] = event.port & 1       # wp_dev_sel
        por_dtm_wp_config[17, 18] = event.port >> 1 # wp_dev_sel2
        por_dtm_wp_config[4, 5] = event.group       # wp_grp
        self.xp_node.write_off(0x21A0+24*wp_index, por_dtm_wp_config.value)
        return wp_index

    # must be called last
    def enable(self) -> None:
        # enable dtm (cannot modify dtm registers after dtm_en is set)
        por_dtm_control = self.xp_node.read_off(0x2100)
        if por_dtm_control[0] == 0:
            por_dtm_control[0] = 1  # dtm_en
            self.xp_node.write_off(0x2100, por_dtm_control.value)


class PMU(ABC):
    # singleton
    _instance = None

    @staticmethod
    @abstractmethod
    def sigterm_handler(signal, frame): pass

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(PMU, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self) -> None:
        # mesh key is cmn index
        self.meshes:Dict[int, Mesh] = {}
        # dtms key is (cmn index, xp nodeid)
        self.dtms:Dict[Tuple[int,int], DTM] = {}
        # dtcs key is (cmn index, dtc domain)
        self.dtcs:Dict[Tuple[int,int], DTC] = {}

    def get_mesh(self, cmn_index:int) -> Mesh:
        if cmn_index not in self.meshes:
            iodrv = CmnIodrv(cmn_index, readonly=False)
            self.meshes[cmn_index] = Mesh(iodrv)
            logging.info(f'cmn{cmn_index} probed')
        return self.meshes[cmn_index]

    def get_dtm(self, cmn_index:int, xp_nid:int) -> DTM:
        if (cmn_index, xp_nid) not in self.dtms:
            mesh = self.get_mesh(cmn_index)
            xp_node = mesh.xps[xp_nid]
            dtc = self.get_dtc(cmn_index, xp_node.dtc_domain)
            dtc0 = self.get_dtc(cmn_index, 0)
            # "DTM" attribute only defined in derived class
            dtm = self.DTM(xp_node, dtc, dtc0)  # type: ignore
            self.dtms[(cmn_index, xp_nid)] = dtm
            logging.debug(f'dtm probed at cmn{cmn_index} nodeid={xp_nid}')
        return self.dtms[(cmn_index, xp_nid)]

    def get_dtc(self, cmn_index:int, dtc_domain:int) -> DTC:
        if (cmn_index, dtc_domain) not in self.dtcs:
            dtc_node = self.get_mesh(cmn_index).dtcs[dtc_domain]
            # "DTC" attribute only defined in derived class
            dtc = self.DTC(dtc_node)  # type: ignore
            self.dtcs[(cmn_index, dtc_domain)] = dtc
            logging.debug(f'dtc probed at cmn{cmn_index} domain={dtc_domain}')
        return self.dtcs[(cmn_index, dtc_domain)]

    # sequence: dtm, dtc0
    def enable(self) -> None:
        for _, dtm in self.dtms.items():
            dtm.enable()
        for _, dtc in self.dtcs.items():
            if dtc.dtc_node.domain == 0:
                dtc.enable0()

    # reset all DTM and DTC in used meshes
    def reset(self) -> None:
        for _, mesh in self.meshes.items():
            # dtc0 is reset first
            for dtc_node in mesh.dtcs:
                dtc_node.reset()
            for xp_col in mesh.root_node.xps:
                for xp_node in xp_col:
                    xp_node.reset()


def start_profile(args, pmu_cls) -> Tuple[PMU, List[Event]]:
    if args.interval < 100 or args.interval > 100_000:
        raise Exception('interval must be within 100 to 100_000 msec')
    if 0 < args.timeout < args.interval:
        raise Exception('profile timeout less then report interval')
    # -e cmn0/xp=10,.../,cmn1/xp=20,.../ -e cmn2/xp=30,.../
    events:List[Event] = []
    for events_str in args.event:
        if not re.match(r'^(cmn\d+/[^/]*/)(,cmn\d+/[^/]*/)*$',
                        events_str, re.IGNORECASE):
            raise Exception(f'invalid event {events_str}')
        # find all patterns of the form "cmnX/.../"
        for event_str in re.findall(r'cmn\d+/[^/]+/',
                                    events_str, re.IGNORECASE):
            events.append(pmu_cls.Event(event_str))
    if not events:
        raise Exception('no valid event found')
    # populate pmu singleton
    pmu = pmu_cls()
    for event in events:
        pmu.get_dtm(event.mesh, event.xp_nid)
    # cleanup possible pending operations
    pmu.reset()
    # register cleanup signal handlers
    signal.signal(signal.SIGTERM, pmu_cls.sigterm_handler)
    # start profiling
    print('='*80)
    print('start profiling ...')
    print(f'report statistics once per {args.interval} msec')
    return pmu, events
