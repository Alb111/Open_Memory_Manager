import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer
from cocotb_tools.runner import get_runner

from sram_models import find_sram_model


SIM = os.getenv("SIM", "icarus")
HDL_TOPLEVEL = "mem_ctrl_8192x32"

NUM_WORDS = 8192
NUM_BANKS = 8
BANK_DEPTH = NUM_WORDS // NUM_BANKS   # 1024


def set_idle(dut):
    dut.mem_valid_i.value = 0
    dut.mem_instr_i.value = 0
    dut.mem_addr_i.value = 0
    dut.mem_wdata_i.value = 0
    dut.mem_wstrb_i.value = 0
    dut.clear_start_i.value = 0
    dut.debug_mode_i.value = 0
    dut.scan_in_i.value = 0


async def start_clock(dut, freq_mhz=50):
    clock = Clock(dut.clk_i, 1 / freq_mhz * 1000, unit="ns")
    cocotb.start_soon(clock.start())
    await Timer(1, unit="ns")
    set_idle(dut)


async def reset(dut, duration_ns=60):
    dut.rst_ni.value = 0
    set_idle(dut)
    await Timer(duration_ns, unit="ns")
    await FallingEdge(dut.clk_i)
    dut.rst_ni.value = 1
    await FallingEdge(dut.clk_i)


async def write_word(dut, addr, data, wstrb=0xF):
    await FallingEdge(dut.clk_i)
    dut.mem_addr_i.value = addr & (NUM_WORDS - 1)
    dut.mem_wdata_i.value = data & 0xFFFFFFFF
    dut.mem_wstrb_i.value = wstrb
    dut.mem_valid_i.value = 1
    await RisingEdge(dut.clk_i)   # SRAM commits the write on this edge
    await Timer(1, unit="ns")
    set_idle(dut)


async def read_word(dut, addr):
    # Present the address, let the SRAM register it on one rising edge, then
    # sample the registered Q (combinationally driven to mem_rdata_o).
    await FallingEdge(dut.clk_i)
    dut.mem_addr_i.value = addr & (NUM_WORDS - 1)
    dut.mem_wstrb_i.value = 0
    dut.mem_valid_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ns")
    value = int(dut.mem_rdata_o.value) & 0xFFFFFFFF
    set_idle(dut)
    return value


async def self_clear(dut, timeout_cycles=1100):
    """Run the broadcast clear (one counter -> all 8 banks) and time it."""
    await FallingEdge(dut.clk_i)
    dut.clear_start_i.value = 1
    cycles = 0
    while True:
        await RisingEdge(dut.clk_i)
        cycles += 1
        await Timer(1, unit="ns")
        if int(dut.clear_done_o.value) == 1:
            break
        assert cycles < timeout_cycles, (
            f"clear_done_o never asserted after {cycles} cycles"
        )
    set_idle(dut)
    await FallingEdge(dut.clk_i)
    return cycles


def addr_in_bank(bank, offset):
    """Compose a word address for a given bank (addr[12:10]) + in-bank offset."""
    return (bank << 10) | (offset & (BANK_DEPTH - 1))


@cocotb.test()
async def test_clear_parallel_all_banks_zero(dut):
    """One broadcast counter clears all eight banks at once, so the sweep costs
    one bank-depth (~1024 cycles) and leaves every word zero."""
    await start_clock(dut)
    await reset(dut)

    # Dirty one word in every bank first.
    for bank in range(NUM_BANKS):
        await write_word(dut, addr_in_bank(bank, bank * 111 + 1), 0xDEAD0000 | bank)

    cycles = await self_clear(dut)
    assert BANK_DEPTH <= cycles <= BANK_DEPTH + 5, (
        f"clear took {cycles} cycles; expected ~{BANK_DEPTH} (parallel banks)"
    )

    # Every bank must be zero at the (previously dirtied) and boundary offsets.
    for bank in range(NUM_BANKS):
        for offset in (0, bank * 111 + 1, BANK_DEPTH - 1):
            got = await read_word(dut, addr_in_bank(bank, offset))
            assert got == 0, (
                f"bank {bank} offset {offset} not zero after clear: {got:#010x}"
            )


@cocotb.test()
async def test_bank_decode_isolation(dut):
    """addr[12:10] must steer each access to its own bank; a write to one bank
    must not appear in another at the same in-bank offset."""
    await start_clock(dut)
    await reset(dut)
    await self_clear(dut)

    offset = 0x155
    for bank in range(NUM_BANKS):
        await write_word(dut, addr_in_bank(bank, offset), 0xB0000000 | (bank << 4) | bank)

    for bank in range(NUM_BANKS):
        got = await read_word(dut, addr_in_bank(bank, offset))
        exp = 0xB0000000 | (bank << 4) | bank
        assert got == exp, (
            f"bank {bank} decode/isolation error at offset {offset:#x}: "
            f"got {got:#010x}, expected {exp:#010x}"
        )


@cocotb.test()
async def test_random_round_trip_full_space(dut):
    """Random writes/reads across the full 8192-word space with a golden dict."""
    await start_clock(dut)
    await reset(dut)
    await self_clear(dut)

    rng = random.Random(0x8192_32)
    expected = {}

    for _ in range(1000):
        addr = rng.randrange(NUM_WORDS)
        data = rng.randrange(1 << 32)
        expected[addr] = data
        await write_word(dut, addr, data)
        got = await read_word(dut, addr)
        assert got == data, (
            f"round-trip mismatch at addr {addr:#x}: got {got:#010x}, "
            f"expected {data:#010x}"
        )

    for addr in rng.sample(sorted(expected), min(128, len(expected))):
        got = await read_word(dut, addr)
        assert got == expected[addr], (
            f"retention mismatch at addr {addr:#x}: got {got:#010x}, "
            f"expected {expected[addr]:#010x}"
        )


def mem_ctrl_8192x32_runner():
    proj_path = Path(__file__).resolve().parent
    sources = [
        find_sram_model(1024, lib="ocd"),
        proj_path / "../src/mem_ctrl/mem1024x32.sv",
        proj_path / "../src/mem_ctrl/mem8192x32.sv",
    ]

    if SIM == "icarus":
        build_args = ["-g2012"]
    elif SIM == "verilator":
        build_args = ["--timing", "--trace", "--trace-fst", "--trace-structs"]
    else:
        build_args = []

    runner = get_runner(SIM)
    runner.build(
        sources=sources,
        hdl_toplevel=HDL_TOPLEVEL,
        always=True,
        build_args=build_args,
        waves=True,
    )

    runner.test(
        hdl_toplevel=HDL_TOPLEVEL,
        test_module="mem8192x32_tb",
        waves=True,
    )


if __name__ == "__main__":
    mem_ctrl_8192x32_runner()
