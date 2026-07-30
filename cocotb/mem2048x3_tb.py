import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer
from cocotb_tools.runner import get_runner

from sram_models import find_sram_model


SIM = os.getenv("SIM", "icarus")
HDL_TOPLEVEL = "mem2048x3"

NUM_LINES = 2048
LINES_PER_ROW = 8


def set_idle(dut):
    dut.enable_n_i.value = 1
    dut.we_i.value = 0
    dut.clear_i.value = 0
    dut.addr_i.value = 0
    dut.wdata_i.value = 0


async def start_clock(dut, freq_mhz=50):
    clock = Clock(dut.clk_i, 1 / freq_mhz * 1000, unit="ns")
    cocotb.start_soon(clock.start())
    await Timer(1, unit="ns")
    set_idle(dut)


async def write_line(dut, addr, data):
    await FallingEdge(dut.clk_i)
    dut.enable_n_i.value = 0
    dut.we_i.value = 1
    dut.clear_i.value = 0
    dut.addr_i.value = addr & (NUM_LINES - 1)
    dut.wdata_i.value = data & 0b111
    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ns")
    set_idle(dut)


async def clear_row(dut, addr):
    # clear_i zeroes all three bits of the eight lines sharing the row.
    await FallingEdge(dut.clk_i)
    dut.enable_n_i.value = 0
    dut.we_i.value = 1
    dut.clear_i.value = 1
    dut.addr_i.value = addr & (NUM_LINES - 1)
    dut.wdata_i.value = 0
    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ns")
    set_idle(dut)


async def read_line(dut, addr):
    # Address is held through the capture cycle so the bit-lane select matches
    # the byte presented on the registered SRAM Q outputs.
    await FallingEdge(dut.clk_i)
    dut.enable_n_i.value = 0
    dut.we_i.value = 0
    dut.clear_i.value = 0
    dut.addr_i.value = addr & (NUM_LINES - 1)
    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ns")
    value = int(dut.rdata_o.value) & 0b111
    set_idle(dut)
    return value


async def clear_all(dut):
    """Define the whole array by clearing every row (one write per 8 lines)."""
    for row in range(NUM_LINES // LINES_PER_ROW):
        await clear_row(dut, row * LINES_PER_ROW)


@cocotb.test()
async def test_clear_then_read_all_zero(dut):
    await start_clock(dut)
    await clear_all(dut)

    for addr in (0, 1, 7, 8, 1023, 2040, 2047):
        got = await read_line(dut, addr)
        assert got == 0, f"line {addr} not zero after clear: {got:#05b}"


@cocotb.test()
async def test_byte_lane_isolation(dut):
    """A single-line write must not disturb the other 7 lines in its byte."""
    await start_clock(dut)
    await clear_all(dut)

    rng = random.Random(0x2048)
    # Exercise the first row, a middle row, and the last row.
    for base in (0, 512, NUM_LINES - LINES_PER_ROW):
        patterns = [rng.randrange(8) for _ in range(LINES_PER_ROW)]

        # Write the 8 lines one at a time (each a masked single-lane write).
        for lane, data in enumerate(patterns):
            await write_line(dut, base + lane, data)

        # Every line in the row must hold exactly what was written to it.
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
    await clear_all(dut)

    addr = 1234
    for pattern in (0b000, 0b001, 0b010, 0b100, 0b011, 0b101, 0b110, 0b111):
        await write_line(dut, addr, pattern)
        got = await read_line(dut, addr)
        assert got == pattern, (
            f"bit-plane mismatch at line {addr}: got {got:#05b}, "
            f"expected {pattern:#05b}"
        )


@cocotb.test()
async def test_clear_row_isolation(dut):
    """clear_i zeroes exactly the addressed row, not its neighbors."""
    await start_clock(dut)
    await clear_all(dut)

    target_row = 40
    guard_rows = (target_row - 1, target_row + 1)

    # Fill target and guard rows with all-ones.
    for row in (target_row, *guard_rows):
        for lane in range(LINES_PER_ROW):
            await write_line(dut, row * LINES_PER_ROW + lane, 0b111)

    # Clear the target row using an arbitrary line within it.
    await clear_row(dut, target_row * LINES_PER_ROW + 3)

    for lane in range(LINES_PER_ROW):
        got = await read_line(dut, target_row * LINES_PER_ROW + lane)
        assert got == 0, f"target row lane {lane} not cleared: {got:#05b}"

    for row in guard_rows:
        for lane in range(LINES_PER_ROW):
            got = await read_line(dut, row * LINES_PER_ROW + lane)
            assert got == 0b111, (
                f"guard row {row} lane {lane} disturbed by clear: {got:#05b}"
            )


@cocotb.test()
async def test_random_round_trip(dut):
    """Interleaved random writes/reads across the full address space."""
    await start_clock(dut)
    await clear_all(dut)

    rng = random.Random(0xC0FFEE)
    expected = dict.fromkeys(range(NUM_LINES), 0)

    for _ in range(600):
        addr = rng.randrange(NUM_LINES)
        data = rng.randrange(8)
        expected[addr] = data
        await write_line(dut, addr, data)
        got = await read_line(dut, addr)
        assert got == data, (
            f"round-trip mismatch at line {addr}: got {got:#05b}, "
            f"expected {data:#05b}"
        )

    # Spot-check retention on a random sample of the reference model.
    for addr in rng.sample(range(NUM_LINES), 128):
        got = await read_line(dut, addr)
        assert got == expected[addr], (
            f"retention mismatch at line {addr}: got {got:#05b}, "
            f"expected {expected[addr]:#05b}"
        )


def mem2048x3_runner():
    proj_path = Path(__file__).resolve().parent
    sources = [
        find_sram_model(256),
        proj_path / "../src/mem2048x3/mem2048x3.sv",
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
        test_module="mem2048x3_tb",
        waves=True,
    )


if __name__ == "__main__":
    mem2048x3_runner()
