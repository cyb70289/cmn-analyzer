import struct
from typing import Tuple, Union


class Packet:
    def __init__(self, a, b, c):
        self._data = struct.pack('<QQQ', a, b, c)

    # get bits in [start, end], *inclusive*
    def __getitem__(self, bit_range:Union[Tuple[int, int], int]) -> int:
        def get_bits_in_byte(byte:int, start_bit:int, stop_bit:int) -> int:
            if start == 0 and stop == 7:
                return byte
            mask = (1 << (stop_bit + 1)) - (1 << start_bit)
            return (byte & mask) >> start_bit

        if isinstance(bit_range, int):
            start, stop = bit_range, bit_range
        else:
            start, stop = bit_range
        if start < 0 or stop > 191 or start > stop:
            raise IndexError("bit range out of bounds")

        start_byte, start_bit = divmod(start, 8)
        stop_byte, stop_bit = divmod(stop, 8)

        result = 0
        for byte_index in range(stop_byte, start_byte-1, -1):
            start_bit_, stop_bit_ = 0, 7
            if byte_index == start_byte:
                start_bit_ = start_bit
            if byte_index == stop_byte:
                stop_bit_ = stop_bit
            result <<= (stop_bit_ - start_bit_ + 1)
            result |= get_bits_in_byte(self._data[byte_index],
                                       start_bit_, stop_bit_)
        return result
