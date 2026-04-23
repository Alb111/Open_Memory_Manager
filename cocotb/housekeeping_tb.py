import os
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge, FallingEdge, ClockCycles
from cocotb_tools.runner import get_runner


sim = os.getenv("SIM", "icarus")
pdk_root = os.getenv("PDK_ROOT", Path("~/.ciel").expanduser())
pdk = os.getenv("PDK", "gf180mcuD")
scl = os.getenv("SCL", "gf180mcu_fd_sc_mcu7t5v0")
gl = os.getenv("GL", False)
slot = os.getenv("SLOT", "1x1")

hdl_toplevel = "boot_wrapper"

FLASH_DATA = [
    0xEF, 0xBE, 0xAD, 0xDE,   # word 0
    #DEADBEEF
    0xFE, 0xC0, 0xFE, 0xCA,   # word 1
    #CAFEC0FE
    0x12, 0x34, 0x56, 0x78,   # word 2
    #78563412
    0xAB, 0xCD, 0xEF, 0x61,   # word 3
    #01EFCDAB
    0x11, 0x22, 0x33, 0x44,   # word 4
    0x55, 0x66, 0x77, 0x88,   # word 5
    0x99, 0xAA, 0xBB, 0xCC,   # word 6
    0xDD, 0xEE, 0xFF, 0x19,   # word 7  (boot_size=32)
]

def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())

async def apply_reset(dut, cycles=5):
    dut.reset_ni.value = 0      # Pull low to reset
    dut.pass_thru_en_i.value = 0
    dut.spi_miso_i.value = 0
    await ClockCycles(dut.clk_i, cycles)
    dut.reset_ni.value = 1      # Pull high to run
    await Timer(1, unit="ns")


async def wait_for_boot_done(dut, timeout_cycles=50_000):
    """wait for boot_done_o. resturn True on success, False on timeout."""
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk_i)
        if dut.boot_done_o.value == 1:
            return True
    return False

async def wait_for_n_writes(dut, n, timeout_cycles=50_000):
    """wait until n SRAM write pulses have been seen. returns True on success."""
    write_count = 0
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk_i)
        if dut.sram_wr_en_o.value == 1:
            write_count += 1
            if write_count >= n:
                return True
    return False

async def flash_model(dut, num_bytes):
    """simualate a spi flash chip bit-stream"""
    # wait for csb to go low (transaction start)
    while dut.flash_csb_o.value != 0:
        await RisingEdge(dut.clk_i)

    # receive 1 cmd byte +3 addr bytes
    for _ in range(4 * 8):
        await RisingEdge(dut.spi_sck_o)   # ignore incoming bits

    # drive data bytes out on miso
    for byte_idx in range(num_bytes):
        byte_val = FLASH_DATA[byte_idx % len(FLASH_DATA)]

        for bit in range(7, -1, -1):    # msb first
            dut.spi_miso_i.value = (byte_val >> bit) & 1
            await RisingEdge(dut.spi_sck_o)   # hold until next rising edge

    dut.spi_miso_i.value = 0

def expected_word(word_index):
    """Compute the expected 32-bit SRAM word for a given word index."""
    b = FLASH_DATA[word_index * 4 : word_index * 4 + 4]
    return b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)



@cocotb.test()
async def test_reset(dut):
    print("\n=== test 1: reset ===")
    #sram_wr_en, cores_en, and boot_done = 0 and flash_csb =1

    start_clock(dut)
    
    dut.reset_ni.value = 0
    dut.pass_thru_en_i.value = 0    # top_pass_thru_en = 0
    dut.spi_miso_i.value = 0

    await ClockCycles(dut.clk_i, 3)
    await Timer(1, unit="ns")

    print(f"  sram_wr_en_o = {int(dut.sram_wr_en_o.value)}  (expected 0)")
    print(f"  cores_en_o = {int(dut.cores_en_o.value)}  (expected 0)")
    print(f"  boot_done_o = {int(dut.boot_done_o.value)}  (expected 0)")

    assert dut.sram_wr_en_o.value == 0,   "sram_wr_en should be 0 during reset"
    assert dut.cores_en_o.value == 0,   "cores_en should be 0 during reset"
    assert dut.boot_done_o.value == 0,   "boot_done should be 0 during reset"

    print(" *** PASS - reset holds outputs low")



@cocotb.test()
async def test_full_boot_sequence(dut):
    print("\n=== test 2: full boot seq ===")
    start_clock(dut)
    await apply_reset(dut)

    cocotb.start_soon(flash_model(dut, 32))

    # watch every clk cycle until boot_done, note each sram write
    sram_writes = []
    for _ in range(50_000):
        await RisingEdge(dut.clk_i)
        if dut.sram_wr_en_o.value == 1:
            sram_writes.append((int(dut.sram_addr_o.value), int(dut.sram_data_o.value)))
        if dut.boot_done_o.value == 1:
            break

    # check write count
    print(f"\n  SRAM writes got: {len(sram_writes)}  (expected 8)")
    assert len(sram_writes) == 8, \
        f"expected 8 word writes, got {len(sram_writes)}"

    # check each words addr and data
    print(f"  {'Word':<6} {'Addr got':<14} {'Addr expected':<16} {'Data got':<14} {'Data expected'}")
    for i, (addr, data) in enumerate(sram_writes):
        exp_addr = i * 4
        exp_data = expected_word(i)
        print(f"  {i:<6} {hex(addr):<14} {hex(exp_addr):<16} {hex(data):<14} {hex(exp_data)}")
        assert addr == exp_addr, f"Word {i}: addr wrong — got {hex(addr)}, expected {hex(exp_addr)}"
        assert data == exp_data, f"Word {i}: data wrong — got {hex(data)}, expected {hex(exp_data)}"

    # check handoff signals
    print(f"\n  boot_done_o = {int(dut.boot_done_o.value)}  (expected 1)")
    print(f"  cores_en_o = {int(dut.cores_en_o.value)}  (expected 1)")
    assert dut.boot_done_o.value == 1, "boot_done should be high"
    assert dut.cores_en_o.value == 1, "cores_en should be high"

    # confirm fms stays in done, singals hold
    await ClockCycles(dut.clk_i, 20)
    print(f"\n  20 cycles later — signals should still hold:")
    print(f"  boot_done_o = {int(dut.boot_done_o.value)}  (expected 1)")
    print(f"  cores_en_o = {int(dut.cores_en_o.value)}  (expected 1)")
    assert dut.boot_done_o.value == 1, "boot_done dropped — FSM left DONE state"
    assert dut.cores_en_o.value == 1, "cores_en dropped — FSM left DONE state"

    print(" *** PASS - full boot sequence works")


@cocotb.test()
async def test_mux_boot_mode(dut):
    print("\n=== test 3: mux boot mode (top_pass_thru_en = 0) ===")
    start_clock(dut)
    await apply_reset(dut)

    # chip_top holds top_pass_thru_en low so boot ctrl is active
    dut.pass_thru_en_i.value = 0
    print("  top_pass_thru_en = 0  (boot controller owns flash pins)")

    cocotb.start_soon(flash_model(dut, 32))
    done = await wait_for_boot_done(dut)

    print(f"  boot_done_o = {int(dut.boot_done_o.value)}  (expected 1)")
    assert done, \
        "boot timed out — pass_thru_en_i gating may be broken in boot mode"

    print("PASS")



@cocotb.test()
async def test_mux_passthrough_mode(dut):
    print("\n=== test 4: mux pass-thru mode (top_pass_thru_en = 1) ===")
    start_clock(dut)
    await apply_reset(dut)

    # chip_top asserts top_pass_thru_en so programmer takes over
    dut.pass_thru_en_i.value = 1
    print("  top_pass_thru_en = 1  (external programmer taking over)")
    print("  In hardware: chip_top would float SPI pins to Hi-Z")
    print("  In simulation: verifying boot controller goes silent")

    # ehck for 50 cycles, boot ctrl shudnt not do anything
    await ClockCycles(dut.clk_i, 50)
    await Timer(1, unit="ns")

    print(f"\n  boot_done_o = {int(dut.boot_done_o.value)}  (expected 0)")
    print(f"  cores_en_o = {int(dut.cores_en_o.value)}  (expected 0)")
    print(f"  sram_wr_en_o = {int(dut.sram_wr_en_o.value)}  (expected 0)")

    assert dut.boot_done_o.value == 0, "boot_done must stay 0 — boot controller should be in reset"
    assert dut.cores_en_o.value == 0, "cores_en must stay 0 — boot controller should be in reset"
    assert dut.sram_wr_en_o.value == 0, "sram_wr_en must stay 0 — no writes while in pass-through"

    print("PASS - passthru mode working")



@cocotb.test()
async def test_mid_boot_interrupt(dut):
    print("\n=== test 5: interrupt mid boot ===")
    start_clock(dut)
    await apply_reset(dut)   # top_pass_thru_en =0

    cocotb.start_soon(flash_model(dut, 32))

    # wait until word 4 has been written, halway done
    print("  top_pass_thru_en = 0  — boot running...")
    print("  waiting for word 4 to be written...")
    reached = await wait_for_n_writes(dut, 4)
    assert reached, "never reached 4 SRAM writes — boot didn't progress far enough"

    print("  word 4 written: chip_top now asserts top_pass_thru_en = 1 (mid-boot)")
    dut.pass_thru_en_i.value = 1   # chip_top takes over
    await Timer(1, unit="ns")   # let reset propogate

    # wait for 200 cycles, sram_wr_en shudnt pulse again
    print("  waiting for 200 cycles, should not be any more SRAM writes...")
    extra_writes = 0
    for _ in range(200):
        await RisingEdge(dut.clk_i)
        if dut.sram_wr_en_o.value == 1:
            extra_writes += 1

    print(f"  extra sram writes after interrupt = {extra_writes}  (expected 0)")
    assert extra_writes == 0, \
        f"fsm kept writing to SRAM after top_pass_thru_en asserted ({extra_writes} extra writes)"

    # boot shudnt have completed (only 4 of 8 words were written)
    print(f"  boot_done_o = {int(dut.boot_done_o.value)}  (expected 0 — boot was cut short)")
    assert dut.boot_done_o.value == 0, \
        "boot_done fired even though boot was interrupted at word 4"

    print("PASS")




@cocotb.test()
async def test_boot_after_passthrough(dut):
    print("\n=== test 6: boot after pass thru ===")
    start_clock(dut)

    # chip_top asserts top_pass_thru_en (programmer connected)
    print(" 1: chip_top asserts top_pass_thru_en = 1 (programmer connected)...")
    dut.reset_ni.value = 1
    dut.pass_thru_en_i.value = 1   # top_pass_thru_en = 1
    dut.spi_miso_i.value = 0
    await ClockCycles(dut.clk_i, 20)

    print(f"    boot_done_o = {int(dut.boot_done_o.value)}  (expected 0)")
    assert dut.boot_done_o.value == 0, "boot_done must be 0 while programmer connected"

    # programmer disconnects, chip_top releases top_pass_thru_en and resets
    print("  2: chip_top releases top_pass_thru_en = 0, applies reset...")
    dut.pass_thru_en_i.value = 0   # top_pass_thru_en = 0
    await apply_reset(dut, cycles=5)

    # normal boot from frehsly programmed flash
    print("  3: booting normally...")
    cocotb.start_soon(flash_model(dut, 32))
    done = await wait_for_boot_done(dut)

    print(f"\n  boot_done_o = {int(dut.boot_done_o.value)}  (expected 1)")
    print(f"  cores_en_o  = {int(dut.cores_en_o.value)}  (expected 1)")
    assert done, "boot did not complete after programmer disconnected"
    assert dut.cores_en_o.value == 1, "cores_en must be 1 after successful reboot"

    print("PASS")



def boot_ctrl_runner():
    proj_path = Path(__file__).resolve().parent

    sources = [
        proj_path / "../src/housekeeping/spi_engine.sv",
        proj_path / "../src/housekeeping/boot_fsm.sv",
        proj_path / "../src/housekeeping/housekeeping_top.sv",
        proj_path / "../src/housekeeping/cypress_model/s25fl128l.v", # The Cypress Model [cite: 790]
        proj_path / "../src/housekeeping/boot_wrapper.sv"   # New Wrapper
    ]

    build_args = []
    if sim == "icarus":
        build_args = ["-g2012"]   # s25fl128l.v uses specify blocks; -g2012 helps
    if sim == "verilator":
        raise RuntimeError("Use icarus for flash model integration tests. "
                           "Verilator does not support specify blocks in s25fl128l.v.")

        
    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel="boot_wrapper",
        always=True,
        build_args=build_args,
        waves=True
    )
    runner.test(
        hdl_toplevel="boot_wrapper",
        test_module="housekeeping_tb",
        waves=True
    )

if __name__ == "__main__":
    boot_ctrl_runner()