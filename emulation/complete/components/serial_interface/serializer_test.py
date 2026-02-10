from serializer import serializer

dut = serializer(32, 32)
dut2 = serializer(32, 32)
en_i = 0
tvalid_i = 0
rready_i = 1
tdata_i = [1,1,1,0,0,0,0,1,1,0,0,0,0,0,0,1,1,0,0,0,0,0,0,1,1,0,0,0,0,1,0,1]
tmsg_len = 30

dut.cycle_clock(en_i, dut2.serial_io, tvalid_i, rready_i, tdata_i, tmsg_len)
dut2.cycle_clock(dut.en_o, dut.serial_io, 0, 1, [0]*32, 32)
dut.print_state()
dut2.print_state()
input("Press to start transmission")
tvalid_i = 1
while dut.tmsg_cnt != 0:
    dut.cycle_clock(en_i, dut2.serial_io, tvalid_i, rready_i, tdata_i, tmsg_len)
    dut2.cycle_clock(dut.en_o, dut.serial_io, 0, 0, [0]*32, 32)
    print("Dut 1:")
    dut.print_state() 
    print("Dut 2:")
    dut2.print_state() 
    tvalid_i = 0
    tdata_i = [0] * 32
    input()

for i in range(2):
    dut.cycle_clock(en_i, dut2.serial_io, tvalid_i, rready_i, tdata_i, tmsg_len)
    dut2.cycle_clock(dut.en_o, dut.serial_io, 0, 1, [0]*32, 32)
    print("Dut 1:")
    dut.print_state() 
    print("Dut 2:")
    dut2.print_state()
    input()  