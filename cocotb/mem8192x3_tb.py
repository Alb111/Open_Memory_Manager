import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer
from cocotb_tools.runner import get_runner

from sram_models import find_sram_model


SIM = os.getenv("SIM", "icarus")
HDL_TOPLEVEL = "mem8192x3"

NUM_LINES = 8192
LINES_PER_ROW = 8
NUM_ROWS = NUM_LINES // LINES_PER_ROW   # 1024


def set_idle(dut):
    dut.enable_n_i.value = 1
    dut.we_i.value = 0
    dut.addr_i.value = 0
    dut.wdata_i.value = 0
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


async def write_line(dut, addr, data):
    await FallingEdge(dut.clk_i)
    dut.enable_n_i.value = 0
    dut.we_i.value = 1
    dut.addr_i.value = addr & (NUM_LINES - 1)
    dut.wdata_i.value = data & 0b111
    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ns")
    set_idle(dut)


async def read_line(dut, addr):
    # Address is held through the capture cycle so the bit-lane select matches
    # the byte presented on the registered SRAM Q outputs.
    await FallingEdge(dut.clk_i)
    dut.enable_n_i.value = 0
    dut.we_i.value = 0
    dut.addr_i.value = addr & (NUM_LINES - 1)
    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ns")
    value = int(dut.rdata_o.value) & 0b111
    set_idle(dut)
    return value


async def self_clear(dut, timeout_cycles=1100):
    """Run the internal broadcast clear sweep and wait for clear_done_o."""
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


@cocotb.test()
async def test_clear_sweep_zeros_all_and_timing(dut):
    """The self-clear sweep zeroes every line; it takes ~1024 cycles (one row
    per cycle, all 8192 lines), not the full line count."""
    await start_clock(dut)
    await reset(dut)

    # Dirty a spread of lines first so a stale array can't pass by accident.
    for addr in (0, 1, 7, 8, 4095, 4096, NUM_LINES - 1):
        await write_line(dut, addr, 0b111)

    cycles = await self_clear(dut)
    # One row cleared per cycle -> ~NUM_ROWS cycles (allow a few for FSM edges).
    assert NUM_ROWS <= cycles <= NUM_ROWS + 5, (
        f"clear took {cycles} cycles; expected ~{NUM_ROWS} (row-paced)"
    )

    for addr in (0, 1, 7, 8, 1023, 1024, 4096, NUM_LINES - 8, NUM_LINES - 1):
        got = await read_line(dut, addr)
        assert got == 0, f"line {addr} not zero after clear: {got:#05b}"


@cocotb.test()
async def test_byte_lane_isolation(dut):
    """A single-line write must not disturb the other 7 lines in its byte."""
    await start_clock(dut)
    await reset(dut)
    await self_clear(dut)

    rng = random.Random(0x8192)
    # Exercise the first row, a middle row, and the last row.
    for base in (0, 4096, NUM_LINES - LINES_PER_ROW):
        patterns = [rng.randrange(8) for _ in range(LINES_PER_ROW)]

        for lane, data in enumerate(patterns):
            await write_line(dut, base + lane, data)

        for lane, data in enumerate(patterns):
            got = await read_line(dut, base + lane)
            assert got == data, (
                f"lane {lane} of row {base // LINES_PER_ROW} corrupted: "
                f"got {got:#05b}, expected {data:#05b} (neighbor write leaked)"
            )


@cocotb.test()
async def test_bit_plane_mapping(dut):
    """Each of the 3 bits routes to its own plane and back through the mux."""
    await start_clock(dut)
    await reset(dut)
    await self_clear(dut)

    addr = 5678
    for pattern in (0b000, 0b001, 0b010, 0b100, 0b011, 0b101, 0b110, 0b111):
        await write_line(dut, addr, pattern)
        got = await read_line(dut, addr)
        assert got == pattern, (
            f"bit-plane mismatch at line {addr}: got {got:#05b}, "
            f"expected {pattern:#05b}"
        )


@cocotb.test()
async def test_random_round_trip(dut):
    """Interleaved random writes/reads across the full 8192-line space."""
    await start_clock(dut)
    await reset(dut)
    await self_clear(dut)

    rng = random.Random(0xC0FFEE)
    expected = dict.fromkeys(range(NUM_LINES), 0)

    for _ in range(800):
        addr = rng.randrange(NUM_LINES)
        data = rng.randrange(8)
        expected[addr] = data
        await write_line(dut, addr, data)
        got = await read_line(dut, addr)
        assert got == data, (
            f"round-trip mismatch at line {addr}: got {got:#05b}, "
            f"expected {data:#05b}"
        )

    for addr in rng.sample(range(NUM_LINES), 128):
        got = await read_line(dut, addr)
        assert got == expected[addr], (
            f"retention mismatch at line {addr}: got {got:#05b}, "
            f"expected {expected[addr]:#05b}"
        )


def mem8192x3_runner():
    proj_path = Path(__file__).resolve().parent
    sources = [
        find_sram_model(1024, lib="ocd"),
        proj_path / "../src/mem2048x3/mem8192x3.sv",
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
        test_module="mem8192x3_tb",
        waves=True,
    )


if __name__ == "__main__":
    mem8192x3_runner()
