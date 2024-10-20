import ctypes
import logging
import os
import pickle
import shutil
import struct
import time
from typing import cast, Any, Dict, Generator, List, Tuple, Union

from pmu_base import DTC, DTM, Event, PMU, start_profile


logger = logging.getLogger(__name__)


class Packet:
    # one trace packet (control flit) contains 3 x 64bits
    size = 3 * 8

    def __init__(self, data:bytearray) -> None:
        self._data = data

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


class PacketBuffer:
    chunk_memory_size:int = 4 * 1024 * 1024  # 4MiB chunk
    packets_per_chunk:int = chunk_memory_size // Packet.size
    max_offset:int = packets_per_chunk * Packet.size

    def __init__(self) -> None:
        buffer = bytearray(self.chunk_memory_size)
        self._current_base = \
            ctypes.addressof(ctypes.c_char.from_buffer(buffer, 0))
        self._current_offset = 0
        self.buffers = [buffer]
        # number of packets in buffers
        self.size = 0

    # return a raw pointer address to store next packet
    def next_packet_ptr(self) -> int:
        if self._current_offset >= self.max_offset:
            buffer = bytearray(self.chunk_memory_size)
            self.buffers.append(buffer)
            self._current_base = \
                ctypes.addressof(ctypes.c_char.from_buffer(buffer, 0))
            self._current_offset = 0
        offset = self._current_offset
        self.size += 1
        self._current_offset += Packet.size
        return self._current_base + offset

    def get_packet(self, index:int) -> Packet:
        # XXX: index is not validated here
        buffer_index, offset = divmod(index, self.packets_per_chunk)
        buffer = self.buffers[buffer_index]
        offset *= Packet.size
        return Packet(buffer[offset:offset+Packet.size])


class _TraceEvent(Event):
    def __init__(self, event_str:str) -> None:
        super().__init__(event_str)
        self.packets = PacketBuffer()

    # save pmu info for profiling
    def save_pmu_info(self, dtm:'_TraceDTM', wp_index:int) -> None:
        self.pmu_info = (dtm, wp_index)


class _TraceDTC(DTC):
    def configure(self) -> None:
        super().configure()
        # enable cycle count in trace packet
        por_dt_trace_control = self.dtc_node.read_off(0x0A30)
        por_dt_trace_control[8] = 1  # cc_enable
        self.dtc_node.write_off(0x0A30, por_dt_trace_control.value)


class _TraceDTM(DTM):
    def configure(self, event:Event) -> Any:
        event = cast(_TraceEvent, event)
        # configure watchpoint
        wp_index = super().configure(event)
        # program por_dtm_wp0-3_config to trace control flit with cycle count
        por_dtm_wp_config = self.xp_node.read_off(0x21A0+24*wp_index)
        por_dtm_wp_config[10] = 1          # wp_pkt_gen
        por_dtm_wp_config[11, 13] = 0b100  # wp_pkt_type
        por_dtm_wp_config[14] = 1          # wp_cc_en
        self.xp_node.write_off(0x21A0+24*wp_index, por_dtm_wp_config.value)
        # enable trace fifo
        por_dtm_control = self.xp_node.read_off(0x2100)
        por_dtm_control[3] = 1      # trace_no_atb
        self.xp_node.write_off(0x2100, por_dtm_control.value)
        # save pmu info to event object
        event.save_pmu_info(self, wp_index)

    def enable_tracetag(self) -> None:
        por_dtm_control = self.xp_node.read_off(0x2100)
        por_dtm_control[1] = 1  # trace_tag_enable
        self.xp_node.write_off(0x2100, por_dtm_control.value)


class _TracePMU(PMU):
    Event = _TraceEvent
    DTM = _TraceDTM
    DTC = _TraceDTC

    killed = False

    @staticmethod
    def sigterm_handler(signal, frame) -> None:
        _TracePMU.killed = True
        exit(0)

    def __new__(cls, *args, **kwargs):
        return super().__new__(cls, *args, **kwargs)

    def __init__(self) -> None:
        super().__init__()
        self.events:List[_TraceEvent]

    # FIXME: don't know why, but the first packet is always stale
    def skip_first_packet(self, events) -> None:
        for event in events:
            timeout_ms = 10
            dtm, wp_index = event.pmu_info
            while True:
                por_dtm_fifo_entry_ready = dtm.xp_node.read_off(0x2118)
                if por_dtm_fifo_entry_ready[wp_index] or timeout_ms == 0:
                    dtm.xp_node.write_off(0x2118, 1 << wp_index)
                    break
                time.sleep(0.001)
                timeout_ms -= 1

    # check and copy trace packets to event trace buffer
    def trace(self, events) -> None:
        for event in events:
            dtm, wp_index = event.pmu_info
            por_dtm_fifo_entry_ready = dtm.xp_node.read_off(0x2118)
            if por_dtm_fifo_entry_ready[wp_index]:
                # copy por_dtm_fifo_entry_0,1,2 directly to packer buffer
                ptr = event.packets.next_packet_ptr()
                dtm.xp_node.read_off_raw(0x2120+wp_index*24, ptr)
                dtm.xp_node.read_off_raw(0x2128+wp_index*24, ptr+8)
                dtm.xp_node.read_off_raw(0x2130+wp_index*24, ptr+16)
                # clear ready bit to receive packet again
                dtm.xp_node.write_off(0x2118, 1 << wp_index)

    def save_packets(self, out_file:str) -> None:
        print('='*80)
        if os.path.isfile(out_file):
            backup_filename = f'{out_file}.old'
            shutil.move(out_file, backup_filename)
        print(f'save packets to {out_file} ...')
        pk_data = []
        total_packets = 0;
        for event in self.events:
            data = {
                'name': event.name,
                'mesh': event.mesh,
                'xp_nid': event.xp_nid,
                'port': event.port,
                'channel': event.channel,
                'direction': event.direction,
                'match_groups': event.match_groups,
                'packets': event.packets if event.packets.size > 0 else None
            }
            pk_data.append(data)
            total_packets += event.packets.size
        with open(out_file, 'wb') as file:
            pickle.dump(pk_data, file)
        file_size = os.path.getsize(out_file)
        print(f'total packets:{total_packets:,}, file size:{file_size:,}')


def pmu_trace(args) -> None:
    # start profiling
    pmu, events = start_profile(args, _TracePMU)
    pmu = cast(_TracePMU, pmu)
    events = [cast(_TraceEvent, event) for event in events]
    msg = f'stop when recorded packet size reaches {args.max_size}MB, or '
    if args.timeout > 0:
        msg += f'after {args.timeout} msec'
    else:
        msg += 'ctrl-c to stop immediately'
    print(msg)
    # save events to pmu singleton to save packets on exit
    pmu.events = events
    if args.tracetag:
        # invalidate wp_val and wp_mask for all events except the first
        # one as only the first event triggers tracetag
        for event in events[1:]:
            for group, matches in event.match_groups.items():
                if matches:
                    logger.warning(f'ignored matchgroup{group}: {matches}')
                event.wp_val_masks[group] = (0, 0)
            # reconstruct event name to make clear wp val and mask are ignored
            event.name = f'cmn{event.mesh}-xp{event.xp_nid}-port{event.port}' \
                         f'-{event.direction}-{event.channel}-tracetag'
    try:
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
        # start tracing, drop first packet
        pmu.enable()
        pmu.skip_first_packet(events)
        # busy poll trace fifo and output statistics periodically
        iterations = args.timeout // args.interval
        interval_sec = args.interval / 1000.0
        max_packets = args.max_size*1000*1000 / Packet.size
        last_counts = [0] * len(events)
        while args.timeout <= 0 or iterations > 0:
            next_time = time.time() + interval_sec
            while time.time() < next_time:
                pmu.trace(events)
            print('-'*80)
            total_packets = 0
            for i, event in enumerate(events):
                count = event.packets.size
                print(f'{event.name[:64]:<65}{(count-last_counts[i]):>15,}')
                last_counts[i] = count
                total_packets += count
            if total_packets >= max_packets:
                logger.info('file size reached limit, stop tracing')
                # finally block will save the trace logs
                exit(0)
            iterations -= 1
    except KeyboardInterrupt:
        pass
    finally:
        if not pmu.killed:
            pmu.save_packets(args.output)
        pmu.reset()
