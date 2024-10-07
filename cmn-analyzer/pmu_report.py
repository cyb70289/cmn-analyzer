import csv
import logging
import os
import pickle
import random
from typing import Dict

from pmu_trace import Packet, PacketBuffer


logger = logging.getLogger(__name__)


class _Flit:
    type = 'na'
    fields = {}

    def __init__(self, packet:Packet) -> None:
        self._values:Dict[str, int] = {}
        for field_name, field_bitrange in self.fields.items():
            self._values[field_name] = packet[field_bitrange]

    def value(self, field_name:str) -> int:
        return self._values[field_name]


# XXX: assume MPAM enabled
class _ReqFlit(_Flit):
    type='req'
    fields = {
        'srcid': (15, 25),
        'tgtid': (4, 14),
        'opcode': (62, 68),
        'txnid': (26, 37),
        'lpid': (86, 90),
        'addr': (110, 161),
        'cycle': (128+48, 128+63),
    }


class _RspFlit(_Flit):
    type = 'rsp'
    fields = {
        'srcid': (15, 25),
        'tgtid': (4, 14),
        'opcode': (38, 42),
        'txnid': (26, 37),
        'dbid': (54, 65),
        'cbusy': (51, 53),
        'cycle': (128+48, 128+63),
    }


# XXX: assume MPAM enabled
class _SnpFlit(_Flit):
    type = 'snp'
    fields = {
        'srcid': (4, 14),
        'opcode': (50, 54),
        'txnid': (15, 26),
        'addr': (70, 118),
        'cycle': (128+48, 128+63),
    }


class _DatFlit(_Flit):
    type = 'dat'
    fields = {
        'srcid': (15, 25),
        'tgtid': (4, 14),
        'opcode': (49, 52),
        'txnid': (26, 37),
        'homenid': (38, 48),
        'dbid': (65, 76),
        'cbusy': (62, 64),
        'cycle': (128+48, 128+63),
    }


def trace_report(args) -> None:
    fn = args.input if args.input else 'trace.data'
    # file format defined in _TracePMU.save_packets()
    # it's a list of dict, each dict describes an event, with info and packets
    with open(fn, 'rb') as file:
        events = pickle.load(file)
    os.makedirs(args.out_dir, exist_ok=True)
    for event in events:
        flit_cls = {
            'req': _ReqFlit,
            'rsp': _RspFlit,
            'snp': _SnpFlit,
            'dat': _DatFlit,
        }[event['channel']]
        csv_filename = f'{args.out_dir}/{event["name"]}-{args.sample}.csv'
        with open(csv_filename, 'w', newline='') as file:
            csv_writer = csv.writer(file)
            fields = list(flit_cls.fields.keys())
            csv_writer.writerow(flit_cls.fields.keys())
            packets:PacketBuffer = event['packets']
            if not packets: continue
            if args.sample == 'header' or packets.size <= args.max_records:
                indices = range(0, min(packets.size, args.max_records))
            elif args.sample == 'tail':
                indices = range(packets.size - args.max_records, packets.size)
            elif args.sample == 'evenly':
                step = packets.size // args.max_records
                indices = range(0, step*args.max_records, step)
            elif args.sample == 'random':
                indices = random.sample(range(packets.size), args.max_records)
                indices.sort()
            else:
                assert False
            print(f'write {len(indices):,} records to {csv_filename} ...')
            for index in indices:
                flit = flit_cls(packets.get_packet(index))
                values = [flit.value(field) for field in fields]
                csv_writer.writerow(values)
        # print top 25 lines for quick review
        if args.verbose:
            with open(csv_filename, 'r', newline='') as file:
                csv_reader = csv.reader(file)
                for i, row in enumerate(csv_reader):
                    if i == 25: break
                    print(row)
            print('-'*80)
