from prv2serial import prv2serial

mem_valid = 0
mem_instr = 0
mem_addr = 0xDEADBEEF
mem_wdata = 0xDEADBEEF
mem_wstrb = 0x1
serial_i = 0
en_i = 0

def cycle(dut):
    dut.cycle_clock(
        mem_valid, 
        mem_instr, 
        mem_addr, 
        mem_wdata,
        mem_wstrb,
        serial_i,
        en_i
        )
    dut.serializer.print_state()
    input()


dut = prv2serial()

cycle(dut)
dut.serializer.print_state()
print("done")

mem_valid = 1
while dut.serializer.tmsg_cnt != 0:
    cycle(dut)
    mem_valid = 0
    mem_addr = 0
    mem_wdata = 0

cycle(dut)



