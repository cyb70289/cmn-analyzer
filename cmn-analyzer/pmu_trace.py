from __future__ import annotations

import logging
import struct
import time
from typing import cast, Any, List, Tuple, TypeVar, Union

from cmn_pmu import DTC, DTM, Event, PMU, start_profile


logger = logging.getLogger(__name__)


class Packet:
    def __init__(self, a, b, c):
        self._data = struct.pack('<QQQ', a, b, c)

    # get bits in [start, end], *inclusive*
    def __getitem__(self, bit_range:Union[Tuple[int, int], int]) -> int:
        def get_bits_in_byte(byte:int, start_bit:int, stop_bit:int) -> int:
            if start == 0 and stop == 7:
                return byte
            mask = (1 << (stop_bit + 1)) - (1 << start_bit)
            return (byte & mask) >> start_bit

        if isinstance(bit_range, int):
            start, stop = bit_range, bit_range
        else:
            start, stop = bit_range
        if start < 0 or stop > 191 or start > stop:
            raise IndexError("bit range out of bounds")

        start_byte, start_bit = divmod(start, 8)
        stop_byte, stop_bit = divmod(stop, 8)

        result = 0
        for byte_index in range(stop_byte, start_byte-1, -1):
            start_bit_, stop_bit_ = 0, 7
            if byte_index == start_byte:
                start_bit_ = start_bit
            if byte_index == stop_byte:
                stop_bit_ = stop_bit
            result <<= (stop_bit_ - start_bit_ + 1)
            result |= get_bits_in_byte(self._data[byte_index],
                                       start_bit_, stop_bit_)
        return result


class _TraceEvent(Event):
    def __init__(self, event_str:str) -> None:
        super().__init__(event_str)
        self.packets:List[Packet] = []

    # save pmu info for profiling
    def save_pmu_info(self, dtm:_TraceDTM, wp_index:int) -> None:
        self.pmu_info = (dtm, wp_index)


class _TraceDTC(DTC):
    def configure(self) -> None:
        super().configure()
        # enable cycle count in trace packet
        por_dt_trace_control = self.dtc_node.read_off(0x0A30)
        por_dt_trace_control[8] = 1  # cc_enable
        self.dtc_node.write_off(0x0A30, por_dt_trace_control.value)

    def enable0(self) -> None:
        # enable dtc
        super().enable0()


class _TraceDTM(DTM):
    def configure(self, event:Event) -> Any:
        # configure watchpoint
        wp_index = super().configure(event)
        # program por_dtm_wp0-3_config to trace control flit with cycle count
        por_dtm_wp_config = self.xp_node.read_off(0x21A0+24*wp_index)
        por_dtm_wp_config[10] = 1               # wp_pkt_gen
        por_dtm_wp_config[11, 13] = 0b100       # wp_pkt_type
        por_dtm_wp_config[14] = 1               # wp_cc_en
        self.xp_node.write_off(0x21A0+24*wp_index, por_dtm_wp_config.value)
        # enable trace fifo
        por_dtm_control = self.xp_node.read_off(0x2100)
        por_dtm_control[3] = 1  # trace_no_atb
        self.xp_node.write_off(0x2100, por_dtm_control.value)
        # save pmu info to event object
        event.save_pmu_info(self, wp_index)

    def enable_tracetag(self) -> None:
        por_dtm_control = self.xp_node.read_off(0x2100)
        por_dtm_control[1] = 1  # trace_tag_enable
        self.xp_node.write_off(0x2100, por_dtm_control.value)

    def enable(self) -> None:
        super().enable()


class _TracePMU(PMU):
    Event = _TraceEvent
    DTM = _TraceDTM
    DTC = _TraceDTC

    @staticmethod
    def exit_handler(signal, frame) -> None:
        _TracePMU().reset()
        exit(0)

    def __new__(cls, *args, **kwargs):
        return super().__new__(cls, *args, **kwargs)

    # check and copy trace packets to event trace buffer
    def trace(self, events) -> None:
        for event in events:
            dtm, wp_index = event.pmu_info
            por_dtm_fifo_entry_ready = dtm.xp_node.read_off(0x2118)
            if por_dtm_fifo_entry_ready[wp_index]:
                por_dtm_fifo_entry_0 = dtm.xp_node.read_off(0x2120+wp_index*24)
                por_dtm_fifo_entry_1 = dtm.xp_node.read_off(0x2128+wp_index*24)
                por_dtm_fifo_entry_2 = dtm.xp_node.read_off(0x2130+wp_index*24)
                event.packets.append(Packet(por_dtm_fifo_entry_0.value,
                                            por_dtm_fifo_entry_1.value,
                                            por_dtm_fifo_entry_2.value))
                dtm.xp_node.write_off(0x2118, 1 << wp_index)


def profile_trace(args) -> None:
    msg = f'stop when recorded packet size reaches {args.max_size}MiB, or '
    if args.timeout > 0:
        msg += f'after {args.timeout} msec'
    else:
        msg += 'ctrl-c to stop immediately'
    print(msg)
    # start profiling
    pmu, events = start_profile(args, _TracePMU)
    pmu = cast(_TracePMU, pmu)
    events = [cast(_TraceEvent, event) for event in events]
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
        dtm.configure(event)
    # enable tracetag for first event
    if args.tracetag:
        event0_dtm, _ = events[0].pmu_info
        event0_dtm.enable_tracetag()
    # configure dtc
    for _, dtc in pmu.dtcs.items():
        dtc.configure()
    # start tracing
    pmu.enable()
    # busy poll trace fifo and output statistics periodically
    iterations = args.timeout // args.interval
    interval_sec = args.interval / 1000.0
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
