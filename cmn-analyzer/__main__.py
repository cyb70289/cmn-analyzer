import argparse
import json
import logging
import sys
from argparse import RawTextHelpFormatter
from pprint import pprint

from iodrv import CmnIodrv
from mesh import Mesh
from pmu import profile


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
                             metavar='num', help='CMN mesh id')
    group = info_parser.add_mutually_exclusive_group()
    group.add_argument('-o', '--output', type=str, metavar='file',
                       help='save mesh info to a JSON file')
    group.add_argument('-i', '--input', type=str, metavar='file',
                       help='read mesh info from JSON file')
    # args for both "stat" and "trace"
    stat_trace_parser = \
        argparse.ArgumentParser(add_help=False)
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
    stat_trace_parser.add_argument('-I', '--interval', type=int, default=1000,
                                   metavar='ms', help='print interval')
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
    args = parser.parse_args()
    return args


def load_mesh_info(args):
    with open(args.input, 'r') as file:
        json_data = file.read()
    mesh_info = json.loads(json_data)
    logging.info(f'Loaded mesh info from {args.input}')
    if args.verbose:
        pprint(mesh_info, indent=2)
    return mesh_info


def generate_mesh_info(mesh, args) -> None:
    mesh_info = mesh.info()
    info_json = json.dumps(mesh_info, indent=2)
    if args.output:
        with open(args.output, 'w') as f:
            f.write(info_json)
        logging.info(f'Saved mesh info to {args.output}')
        exit(0)


def main():
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='%(levelname)s:%(module)s:%(message)s')
    if args.cmd == 'info':
        if args.input:
            mesh_info = load_mesh_info(args)
        else:
            iodrv = CmnIodrv(args.mesh, readonly=True)
            mesh = Mesh(iodrv)
            logging.info(f'CMN mesh{args.mesh} probed')
            mesh_info = generate_mesh_info(mesh, args)
    elif args.cmd == 'stat' or args.cmd == 'trace':
        profile(args)


if __name__ == "__main__":
    main()
