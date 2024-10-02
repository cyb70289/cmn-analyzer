import logging
import re
import signal
import time
from typing import Any, Dict, Generator, List, Tuple

import flit.event as flit
from iodrv import CmnIodrv
from mesh import Mesh, NodeCFG, NodeMXP, NodeDTC
from trace import Packet


logger = logging.getLogger(__name__)


class _Event:
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
    - pmu_info     (dtm, dtm_wp_index, dtc_counter_index)
    - packets      [trace packet]
    '''
    def __init__(self, event_str:str) -> None:
        logging.info(f'parse event "{event_str}"')
        self._parse_event_str(event_str.lower())
        self._verify_args()
        self.wp_val_mask = self._get_wp_val_mask()
        self.packets:List[Packet] = []

    # save pmu info for profiling
    def save_pmu_info(self, dtm, wp_index:int, dtc_counter_index:int) -> None:
        self.pmu_info = (dtm, wp_index, dtc_counter_index)

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

    def _get_wp_val_mask(self) -> Tuple[int, int]:
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


class _DTC:
    def __init__(self, dtc_node:NodeDTC) -> None:
        self.dtc_node = dtc_node
        self.active_counters = 0

    def next_counter(self) -> int:
        free_counter_index = self.active_counters
        if free_counter_index >= 8:
            raise Exception('no DTC counter available')
        self.active_counters += 1
        return free_counter_index

    def configure(self, cmd:str) -> None:
        # clear counter on snapshot
        if cmd == 'stat':
            por_dt_pmcr = self.dtc_node.read_off(0x2100)
            por_dt_pmcr[5] = 1  # cntr_rst
            self.dtc_node.write_off(0x2100, por_dt_pmcr.value)
        # enable cycle count in trace packet
        elif cmd == 'trace':
            por_dt_trace_control = self.dtc_node.read_off(0x0A30)
            por_dt_trace_control[8] = 1  # cc_enable
            self.dtc_node.write_off(0x0A30, por_dt_trace_control.value)

    # enable settings only available in domain0
    def enable0(self, cmd:str) -> None:
        assert self.dtc_node.domain == 0
        # enable pmu
        if cmd == 'stat':
            por_dt_pmcr = self.dtc_node.read_off(0x2100)
            if por_dt_pmcr[0] == 0:
                por_dt_pmcr[0] = 1  # pmu_en
                self.dtc_node.write_off(0x2100, por_dt_pmcr.value)
        # enable dtc
        por_dt_dtc_ctl = self.dtc_node.read_off(0xA00)
        if por_dt_dtc_ctl[0] == 0:
            por_dt_dtc_ctl[0] = 1  # dt_en
            self.dtc_node.write_off(0x0A00, por_dt_dtc_ctl.value)


class _DTM:
    def __init__(self, xp_node:NodeMXP, dtc:_DTC, dtc0:_DTC) -> None:
        # XXX: multiple DTM not supported yet
        cfg_node = xp_node.parent
        n_ports = len(xp_node.port_devs)
        if cfg_node.multi_dtm_enabled and n_ports > 2:
            raise Exception('multiple DTM unsuppported')
        self.xp_node = xp_node
        self.dtc = dtc
        self.dtc0 = dtc0
        self.wp_in_use = [False]*4

    def configure(self, event:_Event, cmd:str) -> None:
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
        if cmd == 'trace':
            # trace control flit with cycle count
            por_dtm_wp_config[10] = 1               # wp_pkt_gen
            por_dtm_wp_config[11, 13] = 0b100       # wp_pkt_type
            por_dtm_wp_config[14] = 1               # wp_cc_en
        self.xp_node.write_off(0x21A0+24*wp_index, por_dtm_wp_config.value)
        # enable trace fifo
        if cmd == 'trace':
            por_dtm_control = self.xp_node.read_off(0x2100)
            por_dtm_control[3] = 1  # trace_no_atb
            self.xp_node.write_off(0x2100, por_dtm_control.value)
        # program por_dtm_pmu_config
        dtc_counter_index = -1
        if cmd == 'stat':
            por_dtm_pmu_config = self.xp_node.read_off(0x2210)
            # - set watchpoint as PMU counter input
            pmevcnt_input_sel_bitrange = (32+wp_index*8, 39+wp_index*8)
            por_dtm_pmu_config[pmevcnt_input_sel_bitrange] = wp_index
            # - pair 16bit DTM counter with 32bit DTC counter to 48bit
            pmevcnt_paired = por_dtm_pmu_config[4, 7]
            por_dtm_pmu_config[4, 7] = pmevcnt_paired | (1 << wp_index)
            dtc_counter_index = self.dtc.next_counter()
            pmevcnt_global_num_bitrange = (16+wp_index*4, 18+wp_index*4)
            por_dtm_pmu_config[pmevcnt_global_num_bitrange] = dtc_counter_index
            # - set por_dtm_pmu_config.cntr_rst to clear counter on shapshot
            por_dtm_pmu_config[8] = 1
            self.xp_node.write_off(0x2210, por_dtm_pmu_config.value)
        # save pmu info to event object
        event.save_pmu_info(self, wp_index, dtc_counter_index)

    # must be called after configure(), configure DTM of first event
    def configure_trace(self, enable_tracetag:bool) -> None:
        por_dtm_control = self.xp_node.read_off(0x2100)
        # any XP sets trace_no_atb enables trace fifo
        por_dtm_control[3] = 1  # trace_no_atb
        if enable_tracetag:
            por_dtm_control[1] = 1  # trace_tag_enable
        self.xp_node.write_off(0x2100, por_dtm_control.value)

    def enable_tracetag(self) -> None:
        por_dtm_control = self.xp_node.read_off(0x2100)
        por_dtm_control[1] = 1  # trace_tag_enable
        self.xp_node.write_off(0x2100, por_dtm_control.value)

    def enable(self, cmd:str) -> None:
        # enable pmu
        if cmd == 'stat':
            por_dtm_pmu_config = self.xp_node.read_off(0x2210)
            if por_dtm_pmu_config[0] == 0:
                por_dtm_pmu_config[0] = 1  # pmu_en
                self.xp_node.write_off(0x2210, por_dtm_pmu_config.value)
        # enable dtm (must be last)
        por_dtm_control = self.xp_node.read_off(0x2100)
        if por_dtm_control[0] == 0:
            por_dtm_control[0] = 1  # dtm_en
            self.xp_node.write_off(0x2100, por_dtm_control.value)

    def read_pmu_counter(self, wp_index, dtc_counter_index) -> int:
        # wait for dtc pmu counter ready
        timeout_ms = 100
        while True:
            # poll por_dt_pmssr.ss_status
            ss_status = self.dtc.dtc_node.read_off(0x2128)[0, 8]
            if ss_status & (1 << dtc_counter_index) != 0:
                break
            if timeout_ms == 0:
                raise Exception('timeout wait for DTC snapshot done')
            time.sleep(0.001)
            timeout_ms -= 1
        # read, combine counters from dtm and dtc shadow registers
        por_dtm_pmevcntsr = self.xp_node.read_off(0x2240)
        dtm_counter = por_dtm_pmevcntsr[wp_index*16, 15+wp_index*16]
        # dtc_counter_index -> por_dt_pmevcntsr register address
        # 0,1 -> 0x2050, 2,3 -> 0x2060, 4,5 -> 2070, 6,7 -> 0x2080
        reg_addr = 0x2050 + dtc_counter_index // 2 * 16
        por_dt_pmevcntsr = self.dtc.dtc_node.read_off(reg_addr)
        start_bit_pos = dtc_counter_index % 2 * 32
        dtc_counter = por_dt_pmevcntsr[start_bit_pos, start_bit_pos+31]
        # combine counters
        return (dtc_counter << 16) | dtm_counter


class _PMU:
    # singleton
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(_PMU, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self) -> None:
        # mesh key is cmn index
        self.meshes:Dict[int, Mesh] = {}
        # dtms key is (cmn index, xp nodeid)
        self.dtms:Dict[Tuple[int,int], _DTM] = {}
        # dtcs key is (cmn index, dtc domain)
        self.dtcs:Dict[Tuple[int,int], _DTC] = {}

    def get_mesh(self, cmn_index:int) -> Mesh:
        if cmn_index not in self.meshes:
            iodrv = CmnIodrv(cmn_index, readonly=False)
            self.meshes[cmn_index] = Mesh(iodrv)
            logging.info(f'CMN mesh{cmn_index} probed')
        return self.meshes[cmn_index]

    def get_dtm(self, cmn_index:int, xp_nid:int) -> _DTM:
        if (cmn_index, xp_nid) not in self.dtms:
            mesh = self.get_mesh(cmn_index)
            xp_node = mesh.xps[xp_nid]
            dtc = self.get_dtc(cmn_index, xp_node.dtc_domain)
            dtc0 = self.get_dtc(cmn_index, 0)
            self.dtms[(cmn_index, xp_nid)] = _DTM(xp_node, dtc, dtc0)
            logging.debug(f'DTM probed at cmn{cmn_index} nodeid={xp_nid}')
        return self.dtms[(cmn_index, xp_nid)]

    def get_dtc(self, cmn_index:int, dtc_domain:int) -> _DTC:
        if (cmn_index, dtc_domain) not in self.dtcs:
            dtc_node = self.get_mesh(cmn_index).dtcs[dtc_domain]
            self.dtcs[(cmn_index, dtc_domain)] = _DTC(dtc_node)
            logging.debug(f'DTC probed at cmn{cmn_index} domain={dtc_domain}')
        return self.dtcs[(cmn_index, dtc_domain)]

    # sequence: dtm, dtc0
    def enable(self, cmd:str) -> None:
        for _, dtm in self.dtms.items():
            dtm.enable(cmd)
        for _, dtc in self.dtcs.items():
            if dtc.dtc_node.domain == 0:
                dtc.enable0(cmd)

    # reset all DTM and DTC in used meshes
    def reset(self) -> None:
        for _, mesh in self.meshes.items():
            # dtc0 is reset first
            for dtc_node in mesh.dtcs:
                dtc_node.reset()
            for xp_col in mesh.root_node.xps:
                for xp_node in xp_col:
                    xp_node.reset()

    # snapshot and yield event statistics
    def snapshot(self, events) -> Generator[[str, int], None, None]:
        # 4.4.9.2 program PMU snapshot
        # - set por_dt_pmsrr.ss_req to trigger snapshot
        for _, dtc in self.dtcs.items():
            if dtc.dtc_node.domain == 0:
                dtc.dtc_node.write_off(0x2130, 1)
        # iterate all events
        for event in events:
            dtm, wp_index, dtc_counter_index = event.pmu_info
            counter = dtm.read_pmu_counter(wp_index, dtc_counter_index)
            yield event.name, counter

    # check and copy trace packets to event trace buffer
    def trace(self, events) -> None:
        for event in events:
            dtm, wp_index, _ = event.pmu_info
            por_dtm_fifo_entry_ready = dtm.xp_node.read_off(0x2118)
            if por_dtm_fifo_entry_ready[wp_index]:
                por_dtm_fifo_entry_0 = dtm.xp_node.read_off(0x2120+wp_index*24)
                por_dtm_fifo_entry_1 = dtm.xp_node.read_off(0x2128+wp_index*24)
                por_dtm_fifo_entry_2 = dtm.xp_node.read_off(0x2130+wp_index*24)
                event.packets.append(Packet(por_dtm_fifo_entry_0.value,
                                            por_dtm_fifo_entry_1.value,
                                            por_dtm_fifo_entry_2.value))
                dtm.xp_node.write_off(0x2118, 1 << wp_index)


def _reset_pmu(signal, frame) -> None:
    _PMU().reset()
    exit(0)


def _profile_stat(args, pmu:_PMU, events:List[_Event]) -> None:
    if args.timeout > 0:
        print(f'stop in {args.timeout} msec')
    else:
        print('press ctrl-c to stop')
    iterations = args.timeout // args.interval
    interval_sec = args.interval / 1000.0
    # configure dtm
    for event in events:
        dtm = pmu.get_dtm(event.mesh, event.xp_nid)
        dtm.configure(event, args.cmd)
    # configure dtc
    for _, dtc in pmu.dtcs.items():
        dtc.configure(args.cmd)
    # start counting
    pmu.enable(args.cmd)
    # output statistics periodically
    next_time = time.time()
    while args.timeout <= 0 or iterations > 0:
        next_time += interval_sec
        sleep_duration = next_time - time.time()
        if sleep_duration > 0:
            time.sleep(sleep_duration)
        else:
            logger.warning('run time exceeds stat interval')
            next_time = time.time()
        print('-'*80)
        counters = pmu.snapshot(events)
        for ev_name, ev_counter in counters:
            print(f'{ev_name[:64]:<65}{ev_counter:>15,}')
        iterations -= 1


def _profile_trace(args, pmu:_PMU, events:List[_Event]) -> None:
    msg = f'stop when recorded packet size reaches {args.max_size}MiB, or '
    if args.timeout > 0:
        msg += f'after {args.timeout} msec'
    else:
        msg += 'ctrl-c to stop immediately'
    print(msg)
    iterations = int(args.timeout / args.interval)
    interval_sec = args.interval / 1000.0
    if args.tracetag:
        # invalidate wp_val and wp_mask for all events except the first
        # one as only the first event triggers tracetag
        for event in events[1:]:
            if event.matches:
                logger.warning(f'matchgroup ignored: {event.matches}')
            event.wp_val_mask = (0, 0)
    # configure dtm
    for event in events:
        dtm = pmu.get_dtm(event.mesh, event.xp_nid)
        dtm.configure(event, args.cmd)
    # enable tracetag for first event
    if args.tracetag:
        event0_dtm, _, _ = events[0].pmu_info
        event0_dtm.enable_tracetag()
    # configure dtc
    for _, dtc in pmu.dtcs.items():
        dtc.configure(args.cmd)
    # start tracing
    pmu.enable(args.cmd)
    # busy poll trace fifo and output statistics periodically
    last_counts = [0] * len(events)
    while args.timeout <= 0 or iterations > 0:
        next_time = time.time() + interval_sec
        while time.time() < next_time:
            pmu.trace(events)
        print('-'*80)
        for i, event in enumerate(events):
            count = len(event.packets)
            print(f'{event.name[:64]:<65}{(count-last_counts[i]):>15,}')
            last_counts[i] = count
        iterations -= 1


def profile(args) -> None:
    if args.interval < 100 or args.interval > 100_000:
        raise Exception('interval must be within 100 to 100_000 msec')
    if 0 < args.timeout < args.interval:
        raise Exception('profile timeout less then report interval')
    # -e cmn0/xp=10,.../,cmn1/xp=20,.../ -e cmn2/xp=30,.../
    events:List[_Event] = []
    for events_str in args.event:
        if not re.match(r'^(cmn\d+/[^/]*/)(,cmn\d+/[^/]*/)*$',
                        events_str, re.IGNORECASE):
            raise Exception(f'invalid event {events_str}')
        # find all patterns of the form "cmnX/.../"
        for event_str in re.findall(r'cmn\d+/[^/]+/',
                                    events_str, re.IGNORECASE):
            events.append(_Event(event_str))
    if not events:
        raise Exception('no valid event found')
    # populate pmu singleton
    pmu = _PMU()
    for event in events:
        pmu.get_dtm(event.mesh, event.xp_nid)
    # cleanup possible pending operations
    pmu.reset()
    # show profiling time and report interval
    print('='*80)
    print('start profiling ...')
    print(f'report statistics once per {args.interval} msec')
    # register cleanup signal handlers
    signal.signal(signal.SIGINT, _reset_pmu)
    signal.signal(signal.SIGTERM, _reset_pmu)
    # start profiling
    try:
        if args.cmd == 'stat':
            _profile_stat(args, pmu, events)
        elif args.cmd == 'trace':
            _profile_trace(args, pmu, events)
        else:
            raise Exception(f'unknown command {args.cmd}')
    finally:
        pmu.reset()
