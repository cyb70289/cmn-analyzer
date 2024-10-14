import json
import logging
import time

from cmn_iodrv import CmnIodrv
from cmn_mesh import Mesh, NodeDTC


logger = logging.getLogger(__name__)


def dump_mesh_info(args, mesh) -> None:
    mesh_info = mesh.info()
    if args.output:
        info_json = json.dumps(mesh_info, indent=2)
        with open(args.output, 'w') as f:
            f.write(info_json)
        logger.info(f'Saved mesh info to {args.output}')
    else:
        # TODO: visualize cmn
        pass


def probe_mesh_freq(mesh) -> None:
    print('Probe CMN frequency... ', end='', flush=True)
    try:
        # check frequency by reading por_dt_pmccntr register on DTC
        dtc0 = mesh.dtcs[0]
        # enable dtc, pmu
        dtc0.write_off(0x0A00, 1)  # por_dt_dtc_ctl.dt_en = 1
        dtc0.write_off(0x2100, 1)  # por_dt_pmcr.pmu_en = 1
        # count por_dt_pmccntr increments for one second
        start = dtc0.read_off(0x2040)
        time.sleep(1)
        end = dtc0.read_off(0x2040)
        freq = end[0, 39] - start[0, 39]
        if freq < 0:
            freq += 1 << 40
        print(f'{freq/1000_000_000:.3f} GHz')
    except KeyboardInterrupt:
        pass
    finally:
        dtc0.write_off(0x0A00, 0)  # por_dt_dtc_ctl.dt_en = 0
        dtc0.write_off(0x2100, 0)  # por_dt_pmcr.pmu_en = 0


def cmn_info(args) -> None:
    iodrv = CmnIodrv(args.mesh)
    mesh = Mesh(iodrv)
    logger.info(f'CMN mesh{args.mesh} probed')
    dump_mesh_info(args, mesh)
    probe_mesh_freq(mesh)
