from mem2serial import mem2serial

mem_ready = 0
mem_rdata = 0xDEADBEEF
serial_i = 0
en_i = 0

def cycle(dut):
    dut.cycle_clock(
        mem_ready,
        mem_rdata,
        serial_i,
        en_i
        )
    dut.serializer.print_state()
    input()


dut = mem2serial()

cycle(dut)
dut.serializer.print_state()
print("done")

mem_ready = 1
while dut.serializer.tmsg_cnt != 0:
    cycle(dut)
    mem_ready = 0
    mem_rdata = 0

cycle(dut)



