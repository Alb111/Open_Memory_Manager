from dataclasses import dataclass, field
from unidir_serializer import tserializer, rserializer
from collections import deque

@dataclass
class tinput_packet:
    maxlen : int = 32

    valid_i : bool = 0
    data_i  : deque = field(default_factory=deque)

@dataclass
class rinput_packet:
    maxlen : int = 32

    en_i     : bool = 0
    serial_i : list = field(default_factory=list)

    ready_i : bool = 0


def cycle(tdut: tserializer, rdut : rserializer, tinput : tinput_packet, rinput : rinput_packet):
    input()
    tdut.cycle_clock(
        data_i=tinput.data_i,
        valid_i=tinput.valid_i
    )
    rdut.cycle_clock(
        en_i=rinput.en_i,
        serial_i=rinput.serial_i,
        ready_i=rinput.ready_i
    )

    rinput.en_i = tdut.en_o
    rinput.serial_i = tdut.serial_o

    tdut.print_state()
    rdut.print_state()

def bstr_to_deque(bstr : int, len : int, maxlen : int) -> deque:
    output = deque([], maxlen=maxlen)
    for _ in range(len):
        output.appendleft(bstr & 1)
        bstr >>= 1
    return output

def deque_to_bstr(deque) -> int:
    output = 0
    while deque:
        output = (output << 1) | deque.popleft()
    return output

def test_send(tdut: tserializer, rdut : rserializer, tinput : tinput_packet, rinput : rinput_packet):
    msg = 0xDEADBEEF
    tinput.data_i = bstr_to_deque(msg, 32, tinput.maxlen)
    tinput.valid_i = 1

    cycle(tdut, rdut, tinput, rinput)
    cycle(tdut, rdut, tinput, rinput)

    tinput.data_i.clear()
    tinput.valid_i = 0

    while rdut.state == "receive":
        cycle(tdut, rdut, tinput, rinput)

    assert deque_to_bstr(rdut.data_o) == msg, "test_send: message was corrupted" 
    assert rdut.valid_o == 1, "test_send: message finished sending but valid_o isn't high"

    rinput.ready_i = 1
    cycle(tdut, rdut, tinput, rinput)
    rinput.ready_i = 0

    assert rdut.valid_o == 0, "test_send: data was received but valid_o didn't go low"

    
def test_const_send(tdut: tserializer, rdut : rserializer, tinput : tinput_packet, rinput : rinput_packet):
    msg = 0xDEADBEEF
    tinput.data_i = bstr_to_deque(msg, 32, tinput.maxlen)
    tinput.valid_i = 1
    rinput.ready_i = 1

    cycle(tdut, rdut, tinput, rinput)
    cycle(tdut, rdut, tinput, rinput)

    while rdut.state == "receive":
        cycle(tdut, rdut, tinput, rinput)

    assert deque_to_bstr(rdut.data_o) == msg, "test_const_send: message was corrupted" 
    assert rdut.valid_o == 1, "test_const_send: message finished sending but valid_o isn't high"
    
    cycle(tdut, rdut, tinput, rinput)

    tinput.valid_i = 0

    while rdut.state == "receive":
        cycle(tdut, rdut, tinput, rinput)

    assert deque_to_bstr(rdut.data_o) == msg, "test_const_send: message was corrupted" 
    assert rdut.valid_o == 1, "test_const_send: message finished sending but valid_o isn't high"
    cycle(tdut, rdut, tinput, rinput)

    rinput.ready_i = 0
    cycle(tdut, rdut, tinput, rinput)

    assert rdut.valid_o == 0, "test_const_send: data was received but valid_o didn't go low"

def run_tests(num_pins : int, max_size : int):
    tdut = tserializer(num_pins=num_pins, data_size=max_size)
    rdut = rserializer(num_pins=num_pins, data_size=max_size)
    tinput = tinput_packet(maxlen=max_size, valid_i=0, data_i=deque([], maxlen=max_size))
    rinput = rinput_packet(maxlen=max_size, en_i=0, serial_i=[0] * num_pins, ready_i = 0)

    cycle(tdut, rdut, tinput, rinput)

    test_send(tdut, rdut, tinput, rinput)
    test_const_send(tdut, rdut, tinput, rinput)


def main():
    run_tests(1, 32)

if __name__ == "__main__":
    main()
