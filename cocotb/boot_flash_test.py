import os
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge, ClockCycles
from cocotb_tools.runner import get_runner
 
 
sim     = os.getenv("SIM", "icarus")
pdk_root = os.getenv("PDK_ROOT", Path("~/.ciel").expanduser())
pdk     = os.getenv("PDK", "gf180mcuD")
scl     = os.getenv("SCL", "gf180mcu_fd_sc_mcu7t5v0")
gl      = os.getenv("GL", False)
slot    = os.getenv("SLOT", "1x1")
 
hdl_toplevel = "boot_wrapper"
 
BOOT_IMAGE = [(i & 0xFF) ^ 0xA5 for i in range(512)]
 
# JEDEC ID for S25FL128L:  Manufacturer=0x01  Type=0x60  Capacity=0x18
JEDEC_MANUF = 0x01
JEDEC_MEM_TYPE = 0x60
JEDEC_CAPACITY = 0x18
 
 
def write_boot_image_mem():
    sim_build = Path(__file__).resolve().parent / "sim_build"
    sim_build.mkdir(exist_ok=True)
    out = sim_build / "boot_image.mem"
    with open(out, "w") as f:
        f.write("@000000\n")
        for byte in BOOT_IMAGE:
            f.write(f"{byte:02X}\n")
    return out
 
 
def expected_word(word_index):
    #return expected 32-bit SRAM word for a given word index
    b = BOOT_IMAGE[word_index * 4 : word_index * 4 + 4]
    return b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)
 
 

def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())
 
 
async def apply_reset(dut, cycles=40_000):
    dut.reset_ni.value      = 0
    dut.pass_thru_en_i.value = 0
    await ClockCycles(dut.clk_i, cycles)
    dut.reset_ni.value = 1
    await Timer(1, unit="ns")
 
 
async def wait_for_boot_done(dut, timeout_cycles=500_000):
    #poll boot_done_o; return true on success, false on timeout
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk_i)
        if dut.boot_done_o.value == 1:
            return True
    return False
 
 
async def spi_transfer_byte(dut, byte_out):
    received = 0
    for bit in range(7, -1, -1):
        dut.spi_mosi.value = (byte_out >> bit) & 1
        await Timer(50, unit="ns")
        dut.spi_sck.value = 1
        await Timer(10, unit="ns")
        # flash_so can be Z while flash is receiving — treat Z as 0
        raw = dut.flash_so.value
        miso_bit = int(raw) if raw.is_resolvable else 0
        received = (received << 1) | miso_bit
        await Timer(40, unit="ns")
        dut.spi_sck.value = 0
        await Timer(50, unit="ns")
    return received
 
 
async def spi_read_jedec(dut):
    dut.flash_csb.value = 0                              
    await Timer(100, unit="ns")
    await spi_transfer_byte(dut, 0x9F)
    manuf = await spi_transfer_byte(dut, 0x00)
    mem_type = await spi_transfer_byte(dut, 0x00)
    capacity = await spi_transfer_byte(dut, 0x00)
    dut.flash_csb.value = 1                              
    await Timer(100, unit="ns")
    return manuf, mem_type, capacity
 
 
# test 1 — Reset: outputs are inactive while reset is held
@cocotb.test()
async def test_reset_inactive(dut):
    print("\n=== TEST 1: reset holds outputs inactive ===")
 
    start_clock(dut)
    dut.reset_ni.value = 0
    dut.pass_thru_en_i.value = 0
 
    await ClockCycles(dut.clk_i, 10)
    await Timer(1, unit="ns")
 
    print(f"  sram_wr_en_o = {int(dut.sram_wr_en_o.value)}  (expected 0)")
    print(f"  cores_en_o = {int(dut.cores_en_o.value)}   (expected 0)")
    print(f"  boot_done_o = {int(dut.boot_done_o.value)}  (expected 0)")
 
    assert dut.sram_wr_en_o.value == 0, "sram_wr_en must be 0 during reset"
    assert dut.cores_en_o.value == 0, "cores_en must be 0 during reset"
    assert dut.boot_done_o.value == 0, "boot_done must be 0 during reset"
 
    print(" *** PASS")
 
 
# test 2 — JEDEC Device ID
@cocotb.test()
async def test_jedec_id(dut):
    print("\n=== TEST 2: JEDEC device ID via pass-through ===")
 
    start_clock(dut)
 
    # hold boot controller in reset during this test
    dut.reset_ni.value = 0
    dut.pass_thru_en_i.value = 1   # programmer takes the SPI bus
    dut.spi_sck.value = 0
    dut.spi_mosi.value = 0
    dut.flash_csb.value = 1
 
    # wait long enough for flash power-up (SPEEDSIM: ~300 µs = 30 000 cycles)
    await ClockCycles(dut.clk_i, 40_000)
    await Timer(1, unit="ns")
 
    manuf, mem_type, capacity = await spi_read_jedec(dut)
 
    print(f"  Manufacturer ID: {hex(manuf)}(expected {hex(JEDEC_MANUF)})")
    print(f"  Memory type: {hex(mem_type)}(expected {hex(JEDEC_MEM_TYPE)})")
    print(f"  Capacity: {hex(capacity)} (expected {hex(JEDEC_CAPACITY)})")
 
    assert manuf == JEDEC_MANUF,    \
        f"Wrong manufacturer ID: got {hex(manuf)}, expected {hex(JEDEC_MANUF)}"
    assert mem_type == JEDEC_MEM_TYPE, \
        f"Wrong memory type: got {hex(mem_type)}, expected {hex(JEDEC_MEM_TYPE)}"
    assert capacity == JEDEC_CAPACITY, \
        f"Wrong capacity byte: got {hex(capacity)}, expected {hex(JEDEC_CAPACITY)}"
 
    print("  *** PASS — S25FL128L correctly identified")


 
# runner
def boot_ctrl_runner():
    proj_path = Path(__file__).resolve().parent
 
    # Generate the boot image .mem file before building
    mem_path = write_boot_image_mem()
    print(f"[runner] wrote {mem_path}")
 
    sources = [
        proj_path / "../src/housekeeping/spi_engine.sv",
        proj_path / "../src/housekeeping/boot_fsm.sv",
        proj_path / "../src/housekeeping/housekeeping_top.sv",
        proj_path / "../src/housekeeping/cypress_model/s25fl128l.v",
        proj_path / "../src/housekeeping/boot_wrapper.sv",
    ]
 
    build_args = []
    if sim == "icarus":
        build_args = []
    if sim == "verilator":
        build_args = []
 
    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel="boot_wrapper",
        always=True,
        build_args=build_args,
        waves=True,
    )
    runner.test(
        hdl_toplevel="boot_wrapper",
        test_module="boot_flash_test",
        waves=True,
    )
 
 
if __name__ == "__main__":
    boot_ctrl_runner()
 
