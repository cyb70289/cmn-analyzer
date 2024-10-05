import ctypes
import glob
import mmap
import os
from typing import Tuple, Union


class CmnRegister:
    def __init__(self, value:int) -> None:
        self._value = value

    @property
    def value(self) -> int:
        return self._value

    # get bits in [start, end], *inclusive*
    def __getitem__(self, bit_range:Union[Tuple[int, int], int]) -> int:
        if isinstance(bit_range, int):
            start, end = bit_range, bit_range
        else:
            start, end = bit_range
        assert start <= end
        value = self._value >> start
        bit_length = end - start + 1
        bit_mask = (1 << bit_length) - 1
        return value & bit_mask

    # set bits in [start, end], *inclusive*
    def __setitem__(self, bit_range:Union[Tuple[int, int], int],
                    value:int) -> None:
        if isinstance(bit_range, int):
            start, end = bit_range, bit_range
        else:
            start, end = bit_range
        assert start <= end
        assert value < (1 << (end-start+1))
        if start == 0 and end == 63:
            new_value = value
        else:
            mask = (1 << (end+1)) - (1 << start)
            new_value = (self._value & ~mask) | (value << start)
        self._value = new_value


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
        # - void ioread_raw(uint64_t reg_addr, uint64_t value_addr)
        lib.ioread_raw.argtypes = [ctypes.c_uint64, ctypes.c_uint64]
        lib.ioread_raw.restype = None
        # map the device register space
        base = lib.iommap(dev_file.encode('ascii'), size, readonly)
        return lib, base, size

    def read(self, reg:int) -> CmnRegister:
        assert reg + 8 <= self.size
        val = self.lib.ioread(self.base + reg)
        return CmnRegister(val)

    def write(self, reg:int, value:int) -> None:
        assert reg + 8 <= self.size
        self.lib.iowrite(self.base + reg, value)

    def read_raw(self, reg:int, ptr) -> None:
        self.lib.ioread_raw(self.base + reg, ptr)
