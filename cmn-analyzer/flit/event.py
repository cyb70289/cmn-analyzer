import csv
import os
from typing import Any, Dict, Tuple, Generator


# returns a generator iterates all opcodes for a channel
def _get_opcode_gen(channel:str) -> Generator[Any, Any, Any]:
    channel = channel.lower()
    this_dir = os.path.dirname(os.path.abspath(__file__))
    fn = os.path.join(this_dir, 'opcode700.csv')
    with open(fn, 'r') as f:
        csv_reader = csv.reader(f)
        # skip header
        next(csv_reader)
        for _channel, opcode, cmd, _ in csv_reader:
            if _channel.lower() == channel:
                yield int(opcode, 0), cmd


# get specific opcode
def _get_opcode(channel:str, opcode_cmd:str) -> int:
    # opcode can be number(opcode) or string(command)
    try:
        opcode = int(opcode_cmd, 0)
        cmd = '__N/A__'
    except ValueError:
        opcode = -999
        cmd = opcode_cmd.lower()

    gen = _get_opcode_gen(channel)
    for _opcode, _cmd in gen:
        if _opcode == opcode or _cmd.lower() == cmd:
            return _opcode
    raise Exception(f'invalid opcode "{opcode_cmd}" for channel "{channel}"')


# generate wp_val and wp_mask for a match group field
def _get_value_mask(channel:str, group:int, field:str, value:int) \
        -> Tuple[int, int]:
    def bitrange_to_value_mask(value:int, bit_range:str) -> Tuple[int, int]:
        bit_low, bit_high = bit_range.split(':')
        bit_low = int(bit_low, 0)
        bit_high = int(bit_high, 0)
        assert bit_low <= bit_high
        mask = (1 << (bit_high + 1)) - (1 << bit_low)
        _value = value << bit_low
        if (mask | _value) != mask:
            raise Exception(f'value out of bit range: {field}={value}')
        return _value, mask

    this_dir = os.path.dirname(os.path.abspath(__file__))
    fn = os.path.join(this_dir, 'matchgrp700.csv')
    with open(fn, 'r') as f:
        csv_reader = csv.reader(f)
        # skip header row
        next(csv_reader)
        for _channel, _group, _field, bit_range in csv_reader:
            if _channel.lower() != channel.lower():
                continue
            if int(_group, 0) != group:
                continue
            if field.lower() not in _field.lower().split('|'):
                continue
            return bitrange_to_value_mask(value, bit_range)
    raise Exception(f'invalid "{field}": channel={channel},group={group}')


# calculate wp_val, wp_mask per event
def get_wp_val_mask(channel:str, group:int, matches:Dict[str,Any]) \
        -> Tuple[int,int]:
    _value, _mask = 0, 0
    for field, value in matches.items():
        if field == 'opcode':
            value = _get_opcode(channel, value)
        else:
            try:
                value = int(value, 0)
            except ValueError:
                raise Exception(f'invalid value: {field}={value}')
        value, mask = _get_value_mask(channel, group, field, value)
        assert (mask & _mask) == 0
        _value |= value
        _mask |= mask
    return _value, ~_mask
