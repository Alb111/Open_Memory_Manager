from dataclasses import dataclass, field
from bidir_serializer import bidir_serializer
from collections import deque

@dataclass
class input_packet:
    num_pins : int = 1
    maxlen : int = 32

    req_i    : bool = 0
    serial_i : list = field(default_factory=list)
    rready_i : bool = 1
    tvalid_i : bool = 0
    tdata_i  : deque = field(default_factory=deque)

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

def cycle(dut0 : bidir_serializer, dut1 : bidir_serializer, input0 : input_packet, input1 : input_packet):

    dut0.cycle_clock(
        req_i=input0.req_i,
        serial_i=input0.serial_i,
        rready_i=input0.rready_i,
        tvalid_i=input0.tvalid_i,
        tdata_i=input0.tdata_i,
    )
    dut1.cycle_clock(
        req_i=input1.req_i,
        serial_i=input1.serial_i,
        rready_i=input1.rready_i,
        tvalid_i=input1.tvalid_i,
        tdata_i=input1.tdata_i,
    )
    assert (dut1.driving & dut0.driving) == 0, "bidir_serializer test: both sides driving at the same time"

    if dut1.driving:
        serial_io = dut1.serial_io
    elif dut0.driving:
        serial_io = dut0.serial_io
    else:
        serial_io = [0]*input0.num_pins

    input0.serial_i = serial_io
    input1.serial_i = serial_io
    input0.req_i = dut1.req_o
    input1.req_i = dut0.req_o
    print(f"\n\n---- After Clockedge ----")
    dut0.print_state()
    dut1.print_state()
    print(f"\nserial_io: {serial_io}")

def test_send(dut0 : bidir_serializer, dut1 : bidir_serializer, input0 : input_packet, input1 : input_packet):
    message = 0xDEADBEEF
    input0.tdata_i = bstr_to_deque(message, len=32, maxlen=input0.tdata_i.maxlen)
    input0.tvalid_i = 1

    cycle(dut0, dut1, input0, input1)

    input0.tdata_i.clear()
    input0.tvalid_i = 0

    cycle(dut0, dut1, input0, input1)

    while dut1.state == "receive":
        cycle(dut0, dut1, input0, input1)
    
    assert deque_to_bstr(dut1.rdata_o) == message, "test_send: message was corrupted"

    cycle(dut0, dut1, input0, input1)

def test_receive(dut0 : bidir_serializer, dut1 : bidir_serializer, input0 : input_packet, input1 : input_packet):
    message = 0xDEADBEEF
    input1.tdata_i = bstr_to_deque(message, len=32, maxlen=input1.tdata_i.maxlen)
    input1.tvalid_i = 1

    cycle(dut0, dut1, input0, input1)

    input1.tdata_i.clear()
    input1.tvalid_i = 0

    cycle(dut0, dut1, input0, input1)

    while dut0.state == "receive":
        cycle(dut0, dut1, input0, input1)
    
    assert deque_to_bstr(dut0.rdata_o) == message, "test_receive: message was corrupted"

    cycle(dut0, dut1, input0, input1)

def test_const_send(dut0 : bidir_serializer, dut1 : bidir_serializer, input0 : input_packet, input1 : input_packet):
    message = 0xDEADBEEF
    input0.tdata_i = bstr_to_deque(message, len=32, maxlen=input0.tdata_i.maxlen)
    input0.tvalid_i = 1

    cycle(dut0, dut1, input0, input1)
    cycle(dut0, dut1, input0, input1)

    while dut1.state == "receive":
        cycle(dut0, dut1, input0, input1)
    
    assert deque_to_bstr(dut1.rdata_o) == message, "test_const_send: message was corrupted"

    cycle(dut0, dut1, input0, input1)

    input0.tdata_i.clear()
    input0.tvalid_i = 0

    while dut1.state == "receive":
        cycle(dut0, dut1, input0, input1)
    
    assert deque_to_bstr(dut1.rdata_o) == message, "test_const_send: message was corrupted"

    cycle(dut0, dut1, input0, input1)

def test_const_send_receive(dut0 : bidir_serializer, dut1 : bidir_serializer, input0 : input_packet, input1 : input_packet):
    message0 = 0xDEADBEEF
    message1 = 0xBEEFDEAD

    input0.tdata_i = bstr_to_deque(message0, len=32, maxlen=input0.tdata_i.maxlen)
    input0.tvalid_i = 1
    input1.tdata_i = bstr_to_deque(message1, len=32, maxlen=input1.tdata_i.maxlen)
    input1.tvalid_i = 1

    for _ in range(2):
        cycle(dut0, dut1, input0, input1)
        cycle(dut0, dut1, input0, input1)
        while dut0.state == "receive":
            cycle(dut0, dut1, input0, input1)

        assert deque_to_bstr(dut0.rdata_o) == message1, "test_const_send_receive: message0 was corrupted"
        
        cycle(dut0, dut1, input0, input1)

        while dut1.state == "receive":
            cycle(dut0, dut1, input0, input1)
        
        assert deque_to_bstr(dut1.rdata_o) == message0, "test_const_send_receive: message1 was corrupted"

    
    input0.tdata_i.clear()
    input0.tvalid_i = 0
    input1.tdata_i.clear()
    input1.tvalid_i = 0

    cycle(dut0, dut1, input0, input1)
    cycle(dut0, dut1, input0, input1)

def run_tests(num_pins = 1, tmsg_max=32, rmsg_max=32):
    dut0 = bidir_serializer(num_pins, 0, tmsg_max, rmsg_max)
    dut1 = bidir_serializer(num_pins, 1, rmsg_max, tmsg_max)

    input0 = input_packet(num_pins=num_pins, maxlen=32, serial_i=[0]*num_pins, tdata_i=deque([], maxlen=tmsg_max))
    input1 = input_packet(num_pins=num_pins, maxlen=32, serial_i=[0]*num_pins, tdata_i=deque([], maxlen=rmsg_max))

    cycle(dut0, dut1, input0, input1)

    test_send(dut0, dut1, input0, input1)
    test_receive(dut0, dut1, input0, input1)
    test_const_send(dut0, dut1, input0, input1)
    test_const_send_receive(dut0, dut1, input0, input1)

def main():
    run_tests(1)
    print("All tests passed")

if __name__ == "__main__":
    main()