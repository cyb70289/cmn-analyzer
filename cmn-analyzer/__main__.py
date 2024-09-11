import argparse
import json
import logging
import sys
from pprint import pprint

from iodrv import CmnIodrv
from mesh import Mesh


logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description='CMN Analyzer')
    parser.add_argument('mesh', type=int, nargs='?', default=0,
                        help='CMN mesh id')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='enable verbose logging')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('-o', '--output', type=str, metavar='file',
                       help='save mesh info to a JSON file')
    group.add_argument('-i', '--input', type=str, metavar='file',
                       help='read mesh info from JSON file')
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
    if args.verbose:
        logging.debug('======= mesh information =======')
        logging.debug(info_json)
    if args.output:
        with open(args.output, 'w') as f:
            f.write(info_json)
        logging.info(f'Saved mesh info to {args.output}')
        exit(0)


def main():
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='%(levelname)s:%(module)s:%(message)s')
    if args.input:
        mesh_info = load_mesh_info(args)
    else:
        iodrv = CmnIodrv(args.mesh)
        mesh = Mesh(iodrv)
        logging.info(f'CMN mesh{args.mesh} probed')
        mesh_info = generate_mesh_info(mesh, args)


if __name__ == "__main__":
    main()
