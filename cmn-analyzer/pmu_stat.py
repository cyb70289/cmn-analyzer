from __future__ import annotations

import logging
import time
from typing import cast, Any, Generator, List, Tuple, Union

from cmn_pmu import DTC, DTM, Event, PMU, start_profile


logger = logging.getLogger(__name__)


class _StatEvent(Event):
    # save pmu info for profiling
    def save_pmu_info(self, dtm:_StatDTM, wp_index:int, dtc_counter_index:int):
        self.pmu_info = (dtm, wp_index, dtc_counter_index)


class _StatDTC(DTC):
    def configure(self) -> None:
        super().configure()
        # clear counter on snapshot
        por_dt_pmcr = self.dtc_node.read_off(0x2100)
        por_dt_pmcr[5] = 1  # cntr_rst
        self.dtc_node.write_off(0x2100, por_dt_pmcr.value)

    def enable0(self) -> None:
        # enable pmu
        por_dt_pmcr = self.dtc_node.read_off(0x2100)
        if por_dt_pmcr[0] == 0:
            por_dt_pmcr[0] = 1  # pmu_en
            self.dtc_node.write_off(0x2100, por_dt_pmcr.value)
        # enable dtc
        super().enable0()


class _StatDTM(DTM):
    def configure(self, event:Event) -> Any:
        # configure watchpoint
        wp_index = super().configure(event)
        # program por_dtm_pmu_config
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

    def enable(self) -> None:
        # enable pmu
        por_dtm_pmu_config = self.xp_node.read_off(0x2210)
        if por_dtm_pmu_config[0] == 0:
            por_dtm_pmu_config[0] = 1  # pmu_en
            self.xp_node.write_off(0x2210, por_dtm_pmu_config.value)
        # enable dtm (must be last)
        super().enable()

    def read_pmu_counter(self, wp_index:int, dtc_counter_index:int) -> int:
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


class _StatPMU(PMU):
    Event = _StatEvent
    DTM = _StatDTM
    DTC = _StatDTC

    @staticmethod
    def exit_handler(signal, frame) -> None:
        _StatPMU().reset()
        exit(0)

    def __new__(cls, *args, **kwargs):
        return super().__new__(cls, *args, **kwargs)

    # snapshot and yield event statistics
    def snapshot(self, events:List[_StatEvent]) \
            -> Generator[Tuple[str, int], None, None]:
        # set por_dt_pmsrr.ss_req to trigger snapshot
        for _, dtc in self.dtcs.items():
            if dtc.dtc_node.domain == 0:
                dtc.dtc_node.write_off(0x2130, 1)
        # iterate all events
        for event in events:
            dtm, wp_index, dtc_counter_index = event.pmu_info
            counter = dtm.read_pmu_counter(wp_index, dtc_counter_index)
            yield event.name, counter


def profile_stat(args) -> None:
    if args.timeout > 0:
        print(f'stop in {args.timeout} msec')
    else:
        print('press ctrl-c to stop')
    # start profiling
    pmu, events = start_profile(args, _StatPMU)
    pmu = cast(_StatPMU, pmu)
    events = [cast(_StatEvent, event) for event in events]
    try:
        # configure dtm
        for event in events:
            dtm = pmu.get_dtm(event.mesh, event.xp_nid)
            dtm.configure(event)
        # configure dtc
        for _, dtc in pmu.dtcs.items():
            dtc.configure()
        # start counting
        pmu.enable()
        # output statistics periodically
        iterations = args.timeout // args.interval
        interval_sec = args.interval / 1000.0
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
    finally:
        pmu.reset()
