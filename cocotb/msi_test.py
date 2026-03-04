import os
import random
import logging
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, Edge, RisingEdge, FallingEdge, ClockCycles
from cocotb_tools.runner import get_runner
from itertools import product

from emulation.msi_v2 import (
    MSIState, ProcessorEvent, SnoopEvent,
    on_processor_event, on_snoop_event
)


sim = os.getenv("SIM", "icarus")
pdk_root = os.getenv("PDK_ROOT", Path("~/.ciel").expanduser())
pdk = os.getenv("PDK", "gf180mcuD")
scl = os.getenv("SCL", "gf180mcu_fd_sc_mcu7t5v0")
gl = os.getenv("GL", False)
slot = os.getenv("SLOT", "1x1")

hdl_toplevel = "msi.v"

# ============================================================================
# Name Maps
# ============================================================================

STATE_NAMES = {0: "INVALID", 1: "SHARED", 2: "MODIFIED"}
PROC_NAMES  = {0: "PR_RD",   1: "PR_WR"}
SNOOP_NAMES = {0: "BUS_RD",  1: "BUS_RDX", 2: "BUS_UPGR"}

PYTHON_TO_V_CMD = {
    1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 17: 5, 18: 6, 19: 7
}

V_CMD_NAMES = {
    0: "CMD_BUS_RD",    1: "CMD_BUS_RDX",      2: "CMD_BUS_UPGR",
    3: "CMD_EVICT_CLEAN", 4: "CMD_EVICT_DIRTY",
    5: "CMD_SNOOP_BUS_RD", 6: "CMD_SNOOP_BUS_RDX", 7: "CMD_SNOOP_BUS_UPGR"
}

# ============================================================================
# Helpers
# ============================================================================

async def init(dut):
    """Minimal init — just need clock running, no reset needed for comb logic."""
    cocotb.start_soon(Clock(dut.clk_i, 10, unit='ns').start())
    dut.reset_i.value       = 0
    dut.current_state.value = 0
    dut.proc_valid.value    = 0
    dut.proc_event.value    = 0
    dut.snoop_valid.value   = 0
    dut.snoop_event.value   = 0
    await Timer(1, unit='ns')


async def drive_comb(dut, current_state, proc_valid, proc_event, snoop_valid, snoop_event):
    """Directly drive all inputs and wait for combinational settle."""
    dut.current_state.value = int(current_state)
    dut.proc_valid.value    = proc_valid
    dut.proc_event.value    = int(proc_event)
    dut.snoop_valid.value   = snoop_valid
    dut.snoop_event.value   = int(snoop_event)
    await Timer(1, unit='ns')  # combinational settle time


def read_outputs(dut):
    return {
        "next_state": int(dut.next_state.value),
        "cmd_valid":  int(dut.cmd_valid.value),
        "issue_cmd":  int(dut.issue_cmd.value),
        "flush":      int(dut.flush.value),
    }

# ============================================================================
# Tests
# ============================================================================

@cocotb.test()
async def test_fuzz_processor_events(dut):
    """
    Fuzz all 3 states x 2 processor events = 6 combinations.
    Directly drives current_state — no clock-driven state navigation needed.
    """
    await init(dut)
    dut._log.info("=== Fuzz: Processor Events (6 combinations) ===")
    failures = []

    for state, event in product(MSIState, ProcessorEvent):
        await drive_comb(dut, state, 1, event, 0, 0)

        got      = read_outputs(dut)
        expected = on_processor_event(state, event)

        exp_cmd_valid = 1 if expected.issue_cmd is not None else 0
        exp_cmd       = PYTHON_TO_V_CMD[int(expected.issue_cmd)] if expected.issue_cmd is not None else None

        reasons = []
        if got["next_state"] != int(expected.next_state):
            reasons.append(f"next_state={STATE_NAMES[got['next_state']]} exp={STATE_NAMES[int(expected.next_state)]}")
        if got["cmd_valid"] != exp_cmd_valid:
            reasons.append(f"cmd_valid={got['cmd_valid']} exp={exp_cmd_valid}")
        if exp_cmd is not None and got["issue_cmd"] != exp_cmd:
            reasons.append(f"issue_cmd={V_CMD_NAMES.get(got['issue_cmd'])} exp={V_CMD_NAMES.get(exp_cmd)}")
        if got["flush"] != 0:
            reasons.append(f"flush={got['flush']} exp=0")

        passed = len(reasons) == 0
        status = "PASS" if passed else "FAIL"
        dut._log.info(
            f"  [PROC/{status}] {STATE_NAMES[int(state)]} + {PROC_NAMES[int(event)]}"
            f" | next={STATE_NAMES[got['next_state']]}"
            f" cmd_valid={got['cmd_valid']}"
            f" issue_cmd={V_CMD_NAMES.get(got['issue_cmd'])}"
            f" flush={got['flush']}"
            + (f" | {', '.join(reasons)}" if reasons else "")
        )
        if not passed:
            failures.append(f"PROC {STATE_NAMES[int(state)]} + {PROC_NAMES[int(event)]}: {', '.join(reasons)}")

    dut._log.info(f"  Result: {6 - len(failures)}/6 passed")
    assert not failures, "\n".join(failures)


@cocotb.test()
async def test_fuzz_snoop_events(dut):
    """
    Fuzz all 3 states x 3 snoop events = 9 combinations.
    Directly drives current_state — no clock-driven state navigation needed.
    """
    await init(dut)
    dut._log.info("=== Fuzz: Snoop Events (9 combinations) ===")
    failures = []

    for state, event in product(MSIState, SnoopEvent):
        await drive_comb(dut, state, 0, 0, 1, event)

        got      = read_outputs(dut)
        expected = on_snoop_event(state, event)

        reasons = []
        if got["next_state"] != int(expected.next_state):
            reasons.append(f"next_state={STATE_NAMES[got['next_state']]} exp={STATE_NAMES[int(expected.next_state)]}")
        if got["flush"] != int(expected.flush):
            reasons.append(f"flush={got['flush']} exp={int(expected.flush)}")
        if got["cmd_valid"] != 0:
            reasons.append(f"cmd_valid={got['cmd_valid']} exp=0")

        passed = len(reasons) == 0
        status = "PASS" if passed else "FAIL"
        dut._log.info(
            f"  [SNOOP/{status}] {STATE_NAMES[int(state)]} + {SNOOP_NAMES[int(event)]}"
            f" | next={STATE_NAMES[got['next_state']]}"
            f" flush={got['flush']}"
            f" cmd_valid={got['cmd_valid']}"
            + (f" | {', '.join(reasons)}" if reasons else "")
        )
        if not passed:
            failures.append(f"SNOOP {STATE_NAMES[int(state)]} + {SNOOP_NAMES[int(event)]}: {', '.join(reasons)}")

    dut._log.info(f"  Result: {9 - len(failures)}/9 passed")
    assert not failures, "\n".join(failures)


@cocotb.test()
async def test_fuzz_idle(dut):
    """Both valids low across all 3 states — next_state must hold, no side effects."""
    await init(dut)
    dut._log.info("=== Fuzz: Idle (3 combinations) ===")
    failures = []

    for state in MSIState:
        await drive_comb(dut, state, 0, 0, 0, 0)
        got = read_outputs(dut)

        reasons = []
        if got["next_state"] != int(state):
            reasons.append(f"next_state={STATE_NAMES[got['next_state']]} exp={STATE_NAMES[int(state)]}")
        if got["cmd_valid"] != 0:
            reasons.append(f"cmd_valid={got['cmd_valid']} exp=0")
        if got["flush"] != 0:
            reasons.append(f"flush={got['flush']} exp=0")

        passed = len(reasons) == 0
        status = "PASS" if passed else "FAIL"
        dut._log.info(
            f"  [IDLE/{status}] current={STATE_NAMES[int(state)]}"
            f" | next={STATE_NAMES[got['next_state']]}"
            f" cmd_valid={got['cmd_valid']} flush={got['flush']}"
            + (f" | {', '.join(reasons)}" if reasons else "")
        )
        if not passed:
            failures.append(f"IDLE {STATE_NAMES[int(state)]}: {', '.join(reasons)}")

    dut._log.info(f"  Result: {3 - len(failures)}/3 passed")
    assert not failures, "\n".join(failures)


@cocotb.test()
async def test_fuzz_both_valid(dut):
    """
    Both valids high — protocol violation.
    Snoop should win (per priority), verify flush and cmd_valid never both high.
    Covers all 3 states x 2 proc events x 3 snoop events = 18 combinations.
    """
    await init(dut)
    dut._log.info("=== Fuzz: Both Valid High (18 combinations) ===")
    failures = []

    for state, pe, se in product(MSIState, ProcessorEvent, SnoopEvent):
        await drive_comb(dut, state, 1, pe, 1, se)
        got = read_outputs(dut)

        # Snoop wins — check against snoop expected output
        expected = on_snoop_event(state, se)

        reasons = []
        if got["next_state"] != int(expected.next_state):
            reasons.append(f"next_state={STATE_NAMES[got['next_state']]} exp={STATE_NAMES[int(expected.next_state)]}")
        if got["flush"] != int(expected.flush):
            reasons.append(f"flush={got['flush']} exp={int(expected.flush)}")
        if got["cmd_valid"] != 0:
            reasons.append(f"cmd_valid={got['cmd_valid']} exp=0 (snoop must win)")

        passed = len(reasons) == 0
        status = "PASS" if passed else "FAIL"
        dut._log.info(
            f"  [BOTH/{status}] {STATE_NAMES[int(state)]} + PROC={PROC_NAMES[int(pe)]} SNOOP={SNOOP_NAMES[int(se)]}"
            f" | next={STATE_NAMES[got['next_state']]} flush={got['flush']} cmd_valid={got['cmd_valid']}"
            + (f" | {', '.join(reasons)}" if reasons else "")
        )
        if not passed:
            failures.append(f"BOTH {STATE_NAMES[int(state)]} pe={PROC_NAMES[int(pe)]} se={SNOOP_NAMES[int(se)]}: {', '.join(reasons)}")

    total = 18
    dut._log.info(f"  Result: {total - len(failures)}/{total} passed")
    assert not failures, "\n".join(failures)   

def mem_ctrl_runner():
    proj_path = Path(__file__).resolve().parent


    sources = [
        proj_path / "../src/msi_protocol/msi.v",
    ]

    build_args = []
    if sim == "icarus":
        pass
    if sim == "verilator":
        build_args = ["--timing", "--trace", "--trace-fst", "--trace-structs"]
    
    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel="msi_protocol",
        always=True,
        build_args=build_args,
        waves=True,
    )

    runner.test(
        hdl_toplevel="msi_protocol",
        test_module="msi_test",
        waves=True,
    )

if __name__ == "__main__":
    mem_ctrl_runner()
