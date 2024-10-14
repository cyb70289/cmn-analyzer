## NOTES
This tool controls CMN registers directly in user space. It conflicts with
arm-cmn kernel driver. Do not profile CMN with perf and cmn-analyzer at the
same time. Also, don't run two instances of cmn-analyzer, unless they are
profiling different CMN mesh.

Though cmn-analyzer resets all registers to default value when exits, chances
are some settings may violate arm-cmn driver. If the Linux perf tool behaves
abnormally at CMN profiling (e.g., all zero values) after cmn-analyzer runs,
unload and reload arm-cmn kernel driver should fix the issue.

## Software modules
```
                     +--------------+
                     | cmn-analyzer |
                     |  python code |
                     +--------------+
                     |   iolib.so   |
                     +-----^^-------+
                           ||
                   +-------vv-------------+
                  /    CMN registers     /<------+
                 / mapped to user space /        |
user mode       +----------^^----------+         |
                           ||                    |
---------------------------||--------------------+---------------------
                           ||           +--------v--------+
kernel mode                ||           | cmn-analyzer.ko |
                   +-------vv--------+  +--------^--------+
                  /  CMN hardware   /            |
                 /  register space /<------------+
                +-----------------+
```

### cmn-analyzer
Python code counts and traces CMN flits per user inputs.

### iolib.so
A simple library implemented in C. It's called by python code to read/write
memory mapped registers safely.

### cmn-analyzer.ko
A kernel module maps CMN hardware registers to user space, so the python code
can directly read/write CMN registers.

## Build & Run

### Build ko and so
Run `make` to build both cmn-analyzer.ko and iolib.so.
Make sure kernel module build environment is ready (e.g., kernel headers).

### Load kernel module
`$ sudo insmod ko/cmn-analyzer.ko`

### Run cmn-analyzer
```
# dump mesh info
`$ ./cmn-analyzer.sh info -h`

# count flits like "perf stat"
`$ ./cmn-analyzer.sh stat -h`

# trace flits
`$ ./cmn-analyzer.sh trace -h`

# analyse trace logs
`$ ./cmn-analyzer.sh report -h`
```

## Event format
Specify watchpoint events to be counted or traced by `-e event1 -e event2 ...`.

Event must be in the form `cmnX/k1=v1,k2=v2,.../`.

### Example
**cmn0/xp=8,port=0,up,group=0,channel=dat,opcode=compdata,resp=1,datasrc=7/**

### Mandatory args
```
- cmn0: cmn id
- xp=8: cross point node id
- up|down: watch upload or download flits
- group=0|1|2: select match group
- channel=req|rsp|snp|dat: select request, response, snoop or data channel
```

### Optional args
```
- opcode="value": check cmn-analyzer/flits/opcode700.csv for opcode per channel,
                  "value" can be number or command string (case insensitive)
                  e.g., opcode=CompData, opcode=compdata, opcode=0x04
- "field"="value": check cmn-analyzer/flits/matchgrp700.csv for field names per
                   group and channel,
                   "field" is case insensitive, "value" must be number
                   if field has multiple names, any name matches this field
                   e.g., to match request channel group0 field "SRCIC|TGTID"
                   * cmn0/...,up,...,tgtid=8/ matches tgtid for upload flit
                   * cmn0/...,down,...,srcid=8/ matches srcid for download flit
```

## Count flits
Similar to perf stat, it counts flits per watchpoint settings.

### Example
**CPU0(xp=136,port=1) updates cache line uniquely held by CPU2(nodeid=268)**

Below command counts ReadUnique flits from CPU0 to HN-F nodes through request
channel, and CompData flits from CPU2 to CPU0 through data channel.

```
$ ./cmn-analyzer.sh stat \
      -e cmn0/xp=136,port=1,up,channel=req,opcode=ReadUnique/ \
      -e cmn0/xp=136,port=1,down,channel=dat,opcode=CompData,srcid=268/ \
      --timeout 3000
start profiling ...
report statistics once per 1000 msec
stop in 3000 msec
--------------------------------------------------------------------------------
cmn0-xp136-port1-up-grp0-req-readunique                               12,389,303
cmn0-xp136-port1-down-grp0-dat-compdata-srcid268                      24,778,578
--------------------------------------------------------------------------------
cmn0-xp136-port1-up-grp0-req-readunique                               12,386,729
cmn0-xp136-port1-down-grp0-dat-compdata-srcid268                      24,773,326
--------------------------------------------------------------------------------
cmn0-xp136-port1-up-grp0-req-readunique                               12,386,917
cmn0-xp136-port1-down-grp0-dat-compdata-srcid268                      24,773,678
```

## Trace flits
cmn-analyzer can trace and log control flits to disk for later analysis. This
is very useful in practice. E.g., to find the physical address of ReadNoSnp
requests to an SNF node.

cmm-analyzer polls DTM register por_dtm_fifo_entry to read traced flits. Only
one flit can be saved in that register. If there are large volumns of matched
flits, only small portion of them can be captured and saved.

TraceTag is supported by cmn-analyzer. In that mode, the first event triggers
tracetag generation for later packets in same transaction. For other events,
watchpoint matches are ignored (wp_val and wp_mask are reset to 0), they will
be matched by tracetag.

**NOTE: TraceTag is not fully functional**

TraceTag is useful to measure transaction latency. It's necessary to capture
a flit pair (the request flit and response or data flit). The approach is to
enable sample profile in DTM by programming por_dtm_pmsirr with appropriate
reload counter value. It's supposed to capture one flit (with tracetag=1) per
reload counter flits to help identify paired flits clearly.

Unfortunately, it does NOT work in my test. Still see flooding flits overflow
trace buffer very fast. And confusingly, I never see flits with tracetag=1, but
the tracetag function looks work correctly. E.g., program RN-F upload requests
in WP0, program RN-F download data in WP2 with impossible matching condition
wp_val = wp_mask = 0; WP2 observes data flits only if WP0 enables tracetag.

### Example
**CPU0(xp=136,port=1) updates cache line uniquely held by CPU2(nodeid=268)**

### Case1: traces CPU0 upload flits through request channel

```
# trace all requests sent from CPU0
$ ./cmn-analyzer.sh trace \
      -e cmn0/xp=136,port=1,up,channel=req/ \
      --timeout 3000
start profiling ...
report statistics once per 1000 msec
stop when recorded packet size reaches 64MB, or after 3000 msec
--------------------------------------------------------------------------------
cmn0-xp136-port1-up-grp0-req-all                                         170,922
--------------------------------------------------------------------------------
cmn0-xp136-port1-up-grp0-req-all                                         170,525
--------------------------------------------------------------------------------
cmn0-xp136-port1-up-grp0-req-all                                         172,219
--------------------------------------------------------------------------------
save packets to trace.data ...
total packets:513,666, file size:12,583,264

# dump the first 5 records from trace log for quick review
# most flits are ReadUnique requests from CPU0 to some HN-F node
$ ./cmn-analyzer.sh report -n 5 -v
['srcid', 'tgtid', 'txnid', 'opcode', 'lpid', 'mpam', 'addr', 'cycle']
['140', '777', '129', 'ReadUnique', '0', '1', '10003ab19000', '3167']
['140', '777', '129', 'ReadUnique', '0', '1', '10003ab19000', '33969']
['140', '777', '128', 'ReadUnique', '0', '1', '10003ab19000', '51159']
['140', '777', '128', 'ReadUnique', '0', '1', '10003ab19000', '65376']
['140', '777', '129', 'ReadUnique', '0', '1', '10003ab19000', '12388']
```

### Case2: trace CPU0 ReadUnique requests and correspondent CompData flits
```
# trace CPU0 ReadUnique and downloads, enable tracetag
$ ./cmn-analyzer.sh trace \
      -e cmn0/xp=136,port=1,up,channel=req,opcode=ReadUnique/ \
      -e cmn0/xp=136,port=1,down,channel=dat/ \
      --tracetag \
      --max-size 16
start profiling ...
report statistics once per 1000 msec
stop when recorded packet size reaches 16MB, or ctrl-c to stop immediately
--------------------------------------------------------------------------------
cmn0-xp136-port1-up-grp0-req-readunique                                   88,829
cmn0-xp136-port1-down-dat-tracetag                                        88,827
--------------------------------------------------------------------------------
cmn0-xp136-port1-up-grp0-req-readunique                                   89,248
cmn0-xp136-port1-down-dat-tracetag                                        89,250
--------------------------------------------------------------------------------
cmn0-xp136-port1-up-grp0-req-readunique                                   89,308
cmn0-xp136-port1-down-dat-tracetag                                        89,309
--------------------------------------------------------------------------------
cmn0-xp136-port1-up-grp0-req-readunique                                   88,187
cmn0-xp136-port1-down-dat-tracetag                                        88,185
--------------------------------------------------------------------------------
save packets to trace.data ...
total packets:711,143, file size:25,166,393

# parse trace log and save first 2000 events to csv files
$ ./cmn-analyzer.sh report -n 2000
write 2000 records to __csv__/cmn0-xp136-port1-up-grp0-req-readunique-header.csv
write 2000 records to __csv__/cmn0-xp136-port1-down-dat-tracetag-header.csv

# dump second event logs, we can see they are CompData flits from CPU2
$ head -n5 __csv__/cmn0-xp136-port1-down-dat-tracetag-header.csv
srcid,tgtid,txnid,opcode,homenid,dbid,resp,datasrc,cbusy,cycle
268,140,129,CompData,801,0,6,4,0,813
268,140,129,CompData,801,0,6,4,0,44886
268,140,129,CompData,801,0,6,4,0,6067
268,140,129,CompData,801,0,6,4,0,31440
```

## TODO
- erratum 3688582 (kampos-4761) mitigation
- calculate cmn frequency
