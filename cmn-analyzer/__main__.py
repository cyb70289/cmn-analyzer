import argparse
import logging
from iodrv import CmnIodrv
from mesh import Mesh


logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(description='CMN Analyzer')
    parser.add_argument('mesh', type=int, nargs='?', default=0,
                        help='CMN mesh id')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose logging')
    args = parser.parse_args()
    return args


def main():
    args = parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format='%(levelname)s:%(module)s:%(message)s')

    iodrv = CmnIodrv(args.mesh)
    mesh = Mesh(iodrv)
    logging.info(f'CMN mesh{args.mesh} probed')


if __name__ == "__main__":
    main()
