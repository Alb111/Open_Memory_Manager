import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
import random

# golden model
from emulation.complete.memory import MemoryController


# ----------------------------
# Helper Functions
# ----------------------------

async def start_clock(dut, freq_mhz=50):
    clock = Clock(dut.clk, 1 / freq_mhz * 1000, units="ns")
    cocotb.start_soon(clock.start())


async def reset(dut, duration_ns=100):
    dut.rst_n.value = 0
    dut.mem_valid.value = 0
    await Timer(duration_ns, units="ns")
    await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


async def axi_write(dut, addr, data, wstrb):
    dut.mem_addr.value = addr
    dut.mem_wdata.value = data
    dut.mem_wstrb.value = wstrb
    dut.mem_valid.value = 1

    # Wait for ready handshake
    while True:
        await RisingEdge(dut.clk)
        if dut.mem_ready.value == 1:
            break

    dut.mem_valid.value = 0
    await RisingEdge(dut.clk)


async def axi_read(dut, addr):
    dut.mem_addr.value = addr
    dut.mem_wstrb.value = 0
    dut.mem_valid.value = 1

    while True:
        await RisingEdge(dut.clk)
        if dut.mem_ready.value == 1:
            rdata = int(dut.mem_rdata.value)
            break

    dut.mem_valid.value = 0
    await RisingEdge(dut.clk)

    return rdata


# ----------------------------
# Main Test
# ----------------------------

@cocotb.test()
async def test_mem_ctrl_against_golden(dut):

    golden: MemoryController = MemoryController()

    await start_clock(dut)
    await reset(dut)

    NUM_TRANSACTIONS = 100

    for i in range(NUM_TRANSACTIONS):

        addr = random.randint(0, 512)
        data = random.randint(0, 0xFFFF)
        wstrb = random.randint(1, 0xF)

        # write to DUT
        await axi_write(dut, addr, data, wstrb)
        # Apply to golden model
        await golden.write(addr, data, wstrb)


        # read written data
        dut_rdata = await axi_read(dut, addr)
        golden_rdata = await golden.read(addr)
        # compare golden and dut
        assert dut_rdata == golden_rdata, \
            f"Read mismatch at addr {addr:#x}: DUT={dut_rdata:#x}, GOLDEN={golden_rdata:#x}"


    cocotb.log.info("All transactions matched golden model!")
