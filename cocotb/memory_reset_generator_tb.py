import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotb_tools.runner import get_runner

SIM = os.getenv("SIM", "icarus")
HDL_TOPLEVEL = "memory_reset_generator"

NUM_MAIN_WORDS = 2048          # main memory words, addresses 0..2047
NUM_META_ROWS = 256            # mem2048x3 rows (8 lines each), addresses row*8
LINES_PER_ROW = 8
MAX_SWEEP_CYCLES = 8000        # generous bound (covers backpressure runs)


def set_idle(dut):
    dut.start_i.value = 0
    dut.mm_ready_i.value = 1


async def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())


async def reset_dut(dut):
    set_idle(dut)
    dut.rst_ni.value = 0
    for _ in range(5):
        await RisingEdge(dut.clk_i)
    dut.rst_ni.value = 1
    await Timer(1, unit="ns")


async def pulse_start(dut):
    await RisingEdge(dut.clk_i)
    dut.start_i.value = 1
    await RisingEdge(dut.clk_i)
    dut.start_i.value = 0


async def run_sweep(dut, ready_pattern=(1,)):
    """Drive one clear sweep to completion, collecting the addresses touched.

    Returns (mm_addrs, md_rows, busy_seen, ready_seen).
    """
    mm_addrs = set()
    md_rows = set()
    busy_seen = False
    ready_seen = False
    cyc = 0

    # Sample the outputs valid during the current cycle, then advance the clock.
    # Sampling before the edge captures the very first StClear cycle (word 0).
    for _ in range(MAX_SWEEP_CYCLES):
        await Timer(1, unit="ns")
        # Drive main-memory ready for this cycle, then let it settle.
        dut.mm_ready_i.value = ready_pattern[cyc % len(ready_pattern)]
        await Timer(1, unit="ns")

        busy = int(dut.busy_o.value)
        if busy:
            busy_seen = True
            # A main-memory write commits at the next edge only if accepted.
            if (
                int(dut.mm_valid_o.value)
                and int(dut.mm_wstrb_o.value) == 0xF
                and int(dut.mm_ready_i.value)
            ):
                mm_addrs.add(int(dut.mm_addr_o.value))
            # Metadata row clears commit every active cycle (no handshake).
            if (
                int(dut.md_we_o.value)
                and int(dut.md_enable_n_o.value) == 0
                and int(dut.md_clear_o.value)
            ):
                md_rows.add(int(dut.md_addr_o.value))

        if int(dut.ready_o.value):
            ready_seen = True

        # Finish once the sweep has run and the generator returns to idle.
        if busy_seen and ready_seen and not busy:
            break

        await RisingEdge(dut.clk_i)
        cyc += 1
    else:
        assert False, "reset generator sweep never completed"

    return mm_addrs, md_rows, busy_seen, ready_seen


@cocotb.test()
async def test_ready_low_until_first_sweep(dut):
    await start_clock(dut)
    await reset_dut(dut)
    # Nothing has been cleared yet: readiness must stay deasserted until a sweep.
    for _ in range(5):
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")
        assert int(dut.ready_o.value) == 0, "ready asserted before any sweep"
        assert int(dut.busy_o.value) == 0, "busy asserted before start"


@cocotb.test()
async def test_full_sweep_clears_both_memories(dut):
    await start_clock(dut)
    await reset_dut(dut)
    await pulse_start(dut)

    mm_addrs, md_rows, busy_seen, ready_seen = await run_sweep(dut)

    assert busy_seen, "generator never became busy"
    assert ready_seen, "generator never signalled ready"

    expected_mm = set(range(NUM_MAIN_WORDS))
    assert mm_addrs == expected_mm, (
        f"main-memory sweep incomplete: missing "
        f"{sorted(expected_mm - mm_addrs)[:8]}..., extra {sorted(mm_addrs - expected_mm)[:8]}"
    )

    expected_md = {row * LINES_PER_ROW for row in range(NUM_META_ROWS)}
    assert md_rows == expected_md, (
        f"metadata sweep incomplete: missing "
        f"{sorted(expected_md - md_rows)[:8]}..., extra {sorted(md_rows - expected_md)[:8]}"
    )

    # Back to idle with readiness latched high.
    assert int(dut.busy_o.value) == 0
    assert int(dut.ready_o.value) == 1


@cocotb.test()
async def test_held_start_triggers_exactly_one_sweep(dut):
    await start_clock(dut)
    await reset_dut(dut)

    # Assert start and hold it high for the whole test. Edge detection means a
    # continuously-high start must trigger exactly one sweep, not repeat.
    dut.start_i.value = 1
    mm_addrs, _, busy_seen, ready_seen = await run_sweep(dut)
    assert busy_seen and ready_seen
    assert mm_addrs == set(range(NUM_MAIN_WORDS))

    # Start still high; no second sweep may begin.
    for _ in range(20):
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")
        assert int(dut.busy_o.value) == 0, "held start_i started a second sweep"
    assert int(dut.ready_o.value) == 1


@cocotb.test()
async def test_main_memory_backpressure_completes_full_sweep(dut):
    await start_clock(dut)
    await reset_dut(dut)
    await pulse_start(dut)

    # Ready deasserted most cycles: the generator must stall on mm_ready_i and
    # still cover every word exactly once.
    mm_addrs, md_rows, _, ready_seen = await run_sweep(dut, ready_pattern=(1, 0, 0, 1, 0))

    assert ready_seen
    assert mm_addrs == set(range(NUM_MAIN_WORDS)), "backpressured sweep missed words"
    assert md_rows == {row * LINES_PER_ROW for row in range(NUM_META_ROWS)}


@cocotb.test()
async def test_second_sweep_after_reset(dut):
    await start_clock(dut)
    await reset_dut(dut)
    await pulse_start(dut)
    await run_sweep(dut)

    # A fresh reset re-arms readiness, and a new start sweeps again.
    await reset_dut(dut)
    await Timer(1, unit="ns")
    assert int(dut.ready_o.value) == 0, "reset did not clear readiness"
    await pulse_start(dut)
    mm_addrs, md_rows, busy_seen, ready_seen = await run_sweep(dut)
    assert busy_seen and ready_seen
    assert mm_addrs == set(range(NUM_MAIN_WORDS))
    assert md_rows == {row * LINES_PER_ROW for row in range(NUM_META_ROWS)}


def find_source_file():
    env_source = os.getenv("MEMORY_RESET_GENERATOR_RTL")
    if env_source:
        return Path(env_source).resolve()

    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent / "src" / "directory_controller" / "memory_reset_generator.sv",
        here.parent.parent / "src" / "memory_reset_generator.sv",
        here.parent / "memory_reset_generator.sv",
    ]
    for path in candidates:
        if path.exists():
            return path.resolve()

    raise FileNotFoundError(
        "Could not find memory_reset_generator RTL. Set "
        "MEMORY_RESET_GENERATOR_RTL or place memory_reset_generator.sv in src/."
    )


def run_tests():
    source = find_source_file()

    if SIM == "icarus":
        build_args = ["-g2012"]
    elif SIM == "verilator":
        build_args = ["--timing", "--trace", "--trace-fst"]
    else:
        build_args = []

    runner = get_runner(SIM)
    runner.build(
        sources=[source],
        hdl_toplevel=HDL_TOPLEVEL,
        always=True,
        build_args=build_args,
        waves=True,
    )
    runner.test(
        hdl_toplevel=HDL_TOPLEVEL,
        test_module=Path(__file__).stem,
        waves=True,
    )


if __name__ == "__main__":
    run_tests()
