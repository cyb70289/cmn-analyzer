import ctypes
import glob
import mmap
import os
import struct
from typing import Tuple


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
    def __init__(self, mesh_id:int, readonly:bool):
        dev_files = glob.glob(f'/dev/armcmn:CMN{mesh_id}:*')
        if not dev_files:
            raise Exception('cmn device file not found, '
                'is cmn-analyzer.ko loaded?')
        if len(dev_files) > 1:
            raise Exception('duplicated cmn device files found')
        # /dev/armcmn:CMN0:140000000:40000000
        dev_file = dev_files[0]
        size = int(dev_file.split(':')[-1], 16)
        # load iolib.so and mmap register space
        self.lib, self.base, self.size = self._mmap(dev_file, size, readonly)

    def _mmap(self, dev_file:str, size:int, readonly:bool):
        # load iolib.so
        my_dir = os.path.dirname(os.path.abspath(__file__))
        lib_path = os.path.join(my_dir, '../iolib/iolib.so')
        if not os.path.exists(lib_path):
            raise Exception('iolib.so not found, is it built?')
        lib = ctypes.CDLL(lib_path)
        # define arguments and return types of iolib functions
        # - uint64_t iommap(const char *dev_path, uint64_t size, int readonly)
        lib.iommap.argtypes = [ctypes.c_char_p, ctypes.c_uint64, ctypes.c_int]
        lib.iommap.restype = ctypes.c_uint64
        # - uint64_t ioread(uint64_t addr)
        lib.ioread.argtypes = [ctypes.c_uint64]
        lib.ioread.restype = ctypes.c_uint64
        # - void iowrite(uint64_t addr, uint64_t value)
        lib.iowrite.argtypes = [ctypes.c_uint64, ctypes.c_uint64]
        lib.iowrite.restype = None
        # map the device register space
        base = lib.iommap(dev_file.encode('ascii'), size, readonly)
        return lib, base, size

    def read(self, reg:int) -> _cmn_register:
        assert reg + 8 <= self.size
        val = self.lib.ioread(self.base + reg)
        return _cmn_register(val)

    def write(self, reg:int, bit_range:Tuple[int, int], val:int) -> None:
        start, end = bit_range
        assert 0 <= start <= end <= 63
        assert val < (1 << (end-start+1))
        mask = (1 << (start+1)) - (1 << end)
        if start == 0 and end == 63:
            new_val = val
        else:
            original_val = self.lib.ioread(self.base + reg)
            new_val = (original_val & ~mask) | (val << start)
        self.lib.iowrite(self.base + reg, new_val)
