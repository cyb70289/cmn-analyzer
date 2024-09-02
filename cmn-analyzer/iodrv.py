import glob
import mmap
import os
import struct
import typing


class _cmn_register:
    def __init__(self, reg_val:int) -> None:
        self._reg_val = reg_val

    # extract bits at position `start` to `end`, inclusive
    def bits(self, start:int, end:int) -> int:
        assert end >= start
        reg_val = self._reg_val >> start
        bit_length = end - start + 1
        bit_mask = (1 << bit_length) - 1
        return reg_val & bit_mask


class CmnIodrv:
    def __init__(self, mesh_id):
        dev_files = glob.glob(f'/dev/armcmn:CMN{mesh_id}:*')
        if not dev_files:
            raise Exception('Failed to find cmn device file')
        if len(dev_files) > 1:
            raise Exception('Duplicated cmn device files found')
        # /dev/armcmn:CMN0:140000000:40000000
        dev_file = dev_files[0]
        size = int(dev_file.split(':')[-1], 16)
        with open(dev_file, 'rb') as f:
            self.io_base = mmap.mmap(f.fileno(), size, prot=mmap.PROT_READ)
        self.io_size = size

    def read(self, reg) -> int:
        assert reg + 8 <= self.io_size
        data = self.io_base[reg:reg+8]
        reg_val = struct.unpack('<Q', data)[0]
        return _cmn_register(reg_val)