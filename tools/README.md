## pa-stat.py

This script counts SLC reads for each section of a process.

As an example, suppose we are running large_code_c microbenchamrk and want to
learn details of the SLC reads, e.g., is the SLC read for code fetching? which
code section (private code? libc.so?) is reload from SLC more often, etc.

Brief steps:
- capture the request channel trace data, which contains physical address
- pick only read requests, find virtual address per physical address

NOTE: this script currently only counts SLC reads for each section, didn't
report the virtual addresses, though the information is all available.

### run test
Make sure to bind test to specific CPUs, so we can capture CMN flits from the
RN-F node. Otherwise, we must caputre flits for all the HN-F nodes.
```
# make sure code is not in page cache
$ sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'
# bind test to CPU1
$ numactl -m0 -C1 ~/marma/large_code_c/LargeCodeCacheMain
```

### capture request flits
*NOTE: assume CPU1 is under CMN xp 136, port 1.*
```
# capture all uploaded request flits from CPU1
$ ./cmn-analyzer.sh trace -e cmn0/xp=136,port=1,up,channel=req/ --max-size 20

================================================================================
start profiling ...
report statistics once per 1000 msec
stop when recorded packet size reaches 20MB, or ctrl-c to stop immediately
--------------------------------------------------------------------------------
cmn0-xp136-port1-up-req                                                  180,038
--------------------------------------------------------------------------------
cmn0-xp136-port1-up-req                                                  180,059
--------------------------------------------------------------------------------
cmn0-xp136-port1-up-req                                                  181,440
--------------------------------------------------------------------------------
cmn0-xp136-port1-up-req                                                  179,798
--------------------------------------------------------------------------------
cmn0-xp136-port1-up-req                                                  179,754
INFO:pmu_trace:file size reached limit, stop tracing
================================================================================
save packets to trace.data ...
total packets:901,089, file size:25,166,230
```

### convert trace data to csv
```
# dump all traced flits to csv
$ ./cmn-analyzer.sh report -n 0
write 901,089 records to __csv__/cmn0-xp136-port1-up-req-header.csv ...
```

### count SLC reads for each section
```
# must run as root to lookup /proc/pid/pagemap
$ sudo python3 tools/pa-stat.py __csv__/cmn0-xp136-port1-up-req-header.csv `pgrep LargeCodeCache`

 count, pages, map entry
210721,  4103, aaaaabdf0000-aaaaad1b9000 r-xp 00000000 103:02 12605946                  /home/cyb/marma/large_code_c/LargeCodeCacheMain
115875,    78, aaaaad1d1000-aaaaad21f000 rw-p 00000000 00:00 0
  1339,     1, aaaaad1d0000-aaaaad1d1000 rw-p 013d0000 103:02 12605946                  /home/cyb/marma/large_code_c/LargeCodeCacheMain
    28,     1, ffffa7e90000-ffffa7e92000 rw-p 00190000 103:02 50598608                  /usr/lib/aarch64-linux-gnu/libc.so.6
    16,     3, ffffa7cf0000-ffffa7e77000 r-xp 00000000 103:02 50598608                  /usr/lib/aarch64-linux-gnu/libc.so.6
    14,     1, aaaaad1cf000-aaaaad1d0000 r--p 013cf000 103:02 12605946                  /home/cyb/marma/large_code_c/LargeCodeCacheMain
     3,     1, ffffe9dc3000-ffffe9de4000 rw-p 00000000 00:00 0                          [stack]
```
Each line is copied from /proc/pid/maps, with two columns prepended
- count: how many times addresses within this va range are loaded from SLC
- pages: how many distinct physical pages belong to this va range are loaded from SLC

NOTE: normally, "pages * 4k" should be approximately equal to the size of va range.
There may be considerable gap for PGO optimized code. E.g., though the code size is
big, but PGO moves hot code close to each other.

From above output, most SLC reads are for code section "r-xp".
