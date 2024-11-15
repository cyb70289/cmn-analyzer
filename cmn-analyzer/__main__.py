import argparse
import json
import logging
from argparse import RawTextHelpFormatter

from cmn_info import cmn_info
from pmu_stat import pmu_stat
from pmu_trace import pmu_trace
from pmu_report import pmu_report


logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description='CMN Analyzer')
    subparsers = parser.add_subparsers(dest='cmd', required=True)
    # common args
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument('-v', '--verbose', action='store_true',
                               help='enable verbose logging')
    # args only for "info"
    info_parser = subparsers.add_parser('info', help='dump mesh info',
                                        parents=[common_parser])
    info_parser.add_argument('-m', '--mesh', type=int, default=0,
                             metavar='num', help='CMN mesh id (default 0)')
    info_parser.add_argument('-o', '--output', type=str, metavar='file',
                             help='save mesh info to a JSON file')
    # args for both "stat" and "trace"
    stat_trace_parser = argparse.ArgumentParser(add_help=False)
    event_help = (
        'watchpoint events: -e event1,event2 -e event3 ...\n'
        'examples:\n'
        '-e cmn0/xp=8,port=1,up,group=0,channel=req/\n'
        '-e cmn1/xp=0,port=0,down,group=1,channel=dat,opcode=compdata/\n'
        '-e cmn0/xp=8,port=1,up,group=0,channel=rsp,tgtid=100/\n'
        '-e cmn0/xp=8,port=1,up,channel=req/,cmn1/xp=0,port=0,down,channel=dat/'
    )
    stat_trace_parser.add_argument('-e', '--event', type=str, metavar='event',
                                   action='append', required=True,
                                   help=event_help)
    stat_trace_parser.add_argument('-I', '--interval', type=int,
                                   default=1000, metavar='msec',
                                   help='report interval (default 1000 ms)')
    stat_trace_parser.add_argument('-t', '--timeout', type=int,
                                   default=0, metavar='msec',
                                   help='run time in ms (default no stop)')
    stat_parser = \
        subparsers.add_parser('stat', help='count events',
                              parents=[common_parser, stat_trace_parser],
                              formatter_class=RawTextHelpFormatter)
    trace_parser = \
        subparsers.add_parser('trace', help='trace events',
                              parents=[common_parser, stat_trace_parser],
                              formatter_class=RawTextHelpFormatter)
    # args only for "trace"
    trace_parser.add_argument('--tracetag', action='store_true',
                              help='enable tracetag, triggered by first event')
    trace_parser.add_argument('--max-size', type=int, default=64, metavar='MB',
                              help='maximal packet size to stop tracing'
                                   ' (default 64MB)')
    trace_parser.add_argument('-o', '--output', type=str,
                              metavar='file', default='trace.data',
                              help='filename to save trace log'
                                   ' (default "trace.data")')
    # args only for "report"
    report_parser = subparsers.add_parser('report', help='analyze trace log',
                                          parents=[common_parser],
                                          formatter_class=RawTextHelpFormatter)
    report_parser.add_argument('-i', '--input', type=str,
                               metavar='file', default='trace.data',
                               help='trace log file (default "trace.data")')
    report_parser.add_argument('-o', '--out-dir', type=str,
                               metavar='dir', default='__csv__',
                               help='csv output dir (default "__csv__")')
    report_parser.add_argument('-n', '--max-records', type=int,
                               metavar='num', default=1000,
                               help='max records per event (default 1000)\n'
                                    'specify "-n 0" to dump all records')
    report_parser.add_argument('-s', '--sample', type=str,
                               metavar='method', default='header',
                               choices=('header', 'tail', 'evenly', 'random'),
                               help='sampling method (default "header")\n'
                                    '- header: select starting records\n'
                                    '- tail:   select ending records\n'
                                    '- evenly: select records evenly\n'
                                    '- random: select records randomly')
    return parser.parse_args()


def main():
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='%(levelname)s:%(module)s:%(message)s')
    if args.cmd == 'info':
        cmn_info(args)
    elif args.cmd == 'stat':
        pmu_stat(args)
    elif args.cmd == 'trace':
        pmu_trace(args)
    elif args.cmd == 'report':
        pmu_report(args)


if __name__ == "__main__":
    main()
