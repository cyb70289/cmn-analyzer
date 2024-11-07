'''
Generated from below prompt, with minor manual changes

I have a csv file like below, column "addr" is physical address in hex
format. I only care about lines if opcode contains "Read".
<csv>
srcid,tgtid,txnid,opcode,lpid,mpam,addr,cycle
141,649,32,ReadNotSharedDirty,0,1,1003cbda9580,18885
141,665,32,WriteEvictOrEvict,0,1,100340665700,46512
141,272,33,ReadNotSharedDirty,0,1,10016fcf5e80,62130
141,665,34,ReadNotSharedDirty,0,1,10034071d840,8958
141,417,36,ReadNotSharedDirty,0,1,10034074cb40,19616
......
</csv>

Write python code, given this file and a process id, find the count of pa
belong to each va entry in /proc/pid/maps

Follow below steps:
- convert pa to 4k aligned page frame address, sort and find unique frames,
  record the count of each frame
- for each pa, find va per pa from /proc/pid/page_maps, and get the entry in
  /proc/pid/maps by va
  NOTE: to improve efficiency to find va per pa, you can initially scan
        /proc/pid/maps to find mapped va pages, for each va page, search
        /proc/pid/page_maps to find pa per va, then create a pa to va map
- return counts of related pa for each /proc/pid/maps entry
  e.g., if 8 pa are found belong to below maps entry, prepend 8 to the entry
  "8, aaaac4640000-aaaac4777000 r-xp 00000000 103:02 50594870 /usr/bin/bash"
- sort the output by pa count in reverse order
'''

import csv
import os
import sys
from collections import defaultdict
from typing import Dict, List, Tuple


# count occurences of page frames
# e.g., pa_count[0x10002000] = 8, pa_count[0x10003000] = 5
def read_pa_file(filename)-> Dict[int, int]:
    pa_counts = defaultdict(int)
    with open(filename, 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            if 'Read' in row['opcode']:
                pa = int(row['addr'], 16)
                page_frame = pa >> 12
                pa_counts[page_frame] += 1
    return pa_counts


# get address range for each entry in /proc/pid/maps
# e.g., entry = "ffff87b59000-ffff885a9000 rwxp 00000000 00:00 0"
#       return item = (0xffff87b59000, 0xffff885a9000, entry copied)
def read_proc_maps(pid) -> List[Tuple[int, int, str]]:
    maps = []
    with open(f'/proc/{pid}/maps', 'r') as f:
        for line in f:
            parts = line.strip().split()
            start, end = map(lambda x: int(x, 16), parts[0].split('-'))
            maps.append((start, end, line.strip()))
    return maps


# return a dict maps pa to va
def read_page_maps(pid, va_start, va_end) -> Dict[int, int]:
    pa_to_va = {}
    with open(f'/proc/{pid}/pagemap', 'rb') as f:
        for va in range(va_start, va_end, 4096):
            f.seek((va // 4096) * 8)
            data = f.read(8)
            if data:
                pfn = int.from_bytes(data, byteorder='little') & ((1 << 55) - 1)
                if pfn:
                    pa_to_va[pfn] = va
    return pa_to_va


def process_pa_file(pa_filename, pid):
    print(f'scanning pa in {pa_filename} ...')
    pa_counts = read_pa_file(pa_filename)
    print(f'found {len(pa_counts)} distinct pa')

    print(f'reading va ranges in /proc/{pid}/maps ...')
    maps = read_proc_maps(pid)
    print(f'found {len(maps)} map entries')

    pa_to_va_map = {}
    print(f'creating pa to va map for all va ranges ...')
    for start, end, _ in maps:
        pa_to_va_map.update(read_page_maps(pid, start, end))
    print(f'mapped {len(pa_to_va_map)} pa pages to va')

    known_pa, unknown_pa = 0, 0
    # map_counts: key = entry in /proc/pid/maps,  value = [count, pages]
    # - count: how many times this va entry occurs in all captured pa
    # - pages: how many distinct pa pages are accessed from this va entry
    map_counts = defaultdict(lambda: [0, 0])
    for pa, count in pa_counts.items():
        if pa in pa_to_va_map:
            known_pa += 1
            va = pa_to_va_map[pa]
            for start, end, map_entry in maps:
                if start <= va < end:
                    map_counts[map_entry][0] += count
                    map_counts[map_entry][1] += 1
                    break
        else:
            unknown_pa += 1
    print(f'processed {known_pa} pa, ignored {unknown_pa} pa')

    result = []
    result.append(' count, pages, mapentry')
    for map_entry, (count, pages) in map_counts.items():
        result.append(f'{count:>6}, {pages:>5}, {map_entry}')

    result.sort(key=lambda x: int(x.split(',')[0]), reverse=True)
    return result


def main():
    if os.sysconf('SC_PAGE_SIZE') != 4096:
        print('the script only support 4K page size')
        sys.exit(1)
    if os.geteuid() != 0:
        print('must run as root')
        sys.exit(1)
    if len(sys.argv) != 3:
        print('Usage: sudo python3 pa-stat.py <csv-file> <pid>')
        sys.exit(1)

    pa_filename = sys.argv[1]
    pid = sys.argv[2]

    result = process_pa_file(pa_filename, pid)
    print('=============================================================')
    for line in result:
        print(line)


if __name__ == "__main__":
    main()
