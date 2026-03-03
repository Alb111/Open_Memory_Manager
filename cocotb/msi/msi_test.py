import sys
import os
sys.path.insert(0, '/workspaces/Open_Memory_Manager/emulation/complete')

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, ClockCycles, Timer
from itertools import product

from msi_v2 import (
    MSIState, ProcessorEvent, SnoopEvent, CoherenceCmd,
    on_processor_event, on_snoop_event, TransitionResult
)

# ============================================================================
# Name Maps for Readable Logging
# ============================================================================

STATE_NAMES = {
    0: "INVALID",
    1: "SHARED",
    2: "MODIFIED"
}

PROC_NAMES = {
    0: "PR_RD",
    1: "PR_WR"
}

SNOOP_NAMES = {
    0: "BUS_RD",
    1: "BUS_RDX",
    2: "BUS_UPGR"
}

# Maps Python CoherenceCmd values (1-5, 17-19) to Verilog enum values (0-7)
PYTHON_TO_V_CMD = {
    1:  0,  # BUS_RD
    2:  1,  # BUS_RDX
    3:  2,  # BUS_UPGR
    4:  3,  # EVICT_CLEAN
    5:  4,  # EVICT_DIRTY
    17: 5,  # SNOOP_BUS_RD
    18: 6,  # SNOOP_BUS_RDX
    19: 7,  # SNOOP_BUS_UPGR
}

V_CMD_NAMES = {
    0: "CMD_BUS_RD",
    1: "CMD_BUS_RDX",
    2: "CMD_BUS_UPGR",
    3: "CMD_EVICT_CLEAN",
    4: "CMD_EVICT_DIRTY",
    5: "CMD_SNOOP_BUS_RD",
    6: "CMD_SNOOP_BUS_RDX",
    7: "CMD_SNOOP_BUS_UPGR"
}

# ============================================================================
# State navigation sequences
# Each entry drives the FSM from INVALID to the target state.
# Tuples: (proc_valid, proc_event, snoop_valid, snoop_event)
# ============================================================================

REACH_STATE = {
    MSIState.INVALID:  [],
    MSIState.SHARED:   [(1, 0, 0, 0)],
    MSIState.MODIFIED: [(1, 0, 0, 0), (1, 1, 0, 0)],
}

# ============================================================================
# Helpers
# ============================================================================

async def initialise(dut):
    """Start clock, apply reset for 5 cycles, then release."""
    cocotb.start_soon(Clock(dut.clk_i, 10, unit='ns').start())
    dut.reset_i.value       = 1
    dut.current_state.value = 0
    dut.proc_valid.value    = 0
    dut.proc_event.value    = 0
    dut.snoop_valid.value   = 0
    dut.snoop_event.value   = 0
    await ClockCycles(dut.clk_i, 5)
    dut.reset_i.value = 0
    await FallingEdge(dut.clk_i)


async def drive_to_state(dut, target: MSIState):
    """
    Reset FSM and replay known event sequences to reach the target state.
    Leaves valids low and combinational outputs settled on exit.
    Navigation events are clocked but outputs are NOT checked here.
    """
    dut.reset_i.value     = 1
    dut.proc_valid.value  = 0
    dut.snoop_valid.value = 0
    await ClockCycles(dut.clk_i, 2)
    dut.reset_i.value = 0
    await FallingEdge(dut.clk_i)

    for (pv, pe, sv, se) in REACH_STATE[target]:
        dut.proc_valid.value  = pv
        dut.proc_event.value  = pe
        dut.snoop_valid.value = sv
        dut.snoop_event.value = se
        await RisingEdge(dut.clk_i)
        await FallingEdge(dut.clk_i)

    dut.proc_valid.value  = 0
    dut.snoop_valid.value = 0
    await Timer(1, unit='ns')


def read_outputs(dut):
    """Read all DUT outputs into a plain dict."""
    return {
        "next_state": int(dut.next_state.value),
        "cmd_valid":  int(dut.cmd_valid.value),
        "issue_cmd":  int(dut.issue_cmd.value),
        "flush":      int(dut.flush.value),
    }


def check_proc(got, expected):
    """
    Check processor event outputs against golden reference.
    Returns (passed: bool, reason: str).
    """
    exp_cmd_valid = 1 if expected.issue_cmd is not None else 0

    if got["next_state"] != int(expected.next_state):
        return False, (
            f"next_state={STATE_NAMES[got['next_state']]} "
            f"expected {STATE_NAMES[int(expected.next_state)]}"
        )
    if got["cmd_valid"] != exp_cmd_valid:
        return False, f"cmd_valid={got['cmd_valid']} expected {exp_cmd_valid}"

    if expected.issue_cmd is not None:
        exp_sv = PYTHON_TO_V_CMD[int(expected.issue_cmd)]
        if got["issue_cmd"] != exp_sv:
            return False, (
                f"issue_cmd={V_CMD_NAMES.get(got['issue_cmd'], got['issue_cmd'])} "
                f"expected {V_CMD_NAMES.get(exp_sv, exp_sv)}"
            )
    if got["flush"] != 0:
        return False, f"flush={got['flush']} expected 0 — flush must never be set on proc events"

    return True, "OK"


def check_snoop(got, expected):
    """
    Check snoop event outputs against golden reference.
    Returns (passed: bool, reason: str).
    """
    if got["next_state"] != int(expected.next_state):
        return False, (
            f"next_state={STATE_NAMES[got['next_state']]} "
            f"expected {STATE_NAMES[int(expected.next_state)]}"
        )
    if got["flush"] != int(expected.flush):
        return False, f"flush={got['flush']} expected {int(expected.flush)}"
    if got["cmd_valid"] != 0:
        return False, f"cmd_valid={got['cmd_valid']} expected 0 — cmd_valid must never be set on snoop events"

    return True, "OK"


def log_proc(dut, state, event, got, expected, status, reason):
    """Log a processor transition with full GOT/EXP and PASS/FAIL on every call."""
    exp_cmd_valid = 1 if expected.issue_cmd is not None else 0
    exp_sv_cmd    = PYTHON_TO_V_CMD[int(expected.issue_cmd)] if expected.issue_cmd is not None else None
    dut._log.info(
        f"  [PROC] [{status}] "
        f"{STATE_NAMES[int(state)]} + {PROC_NAMES[int(event)]}"
        f" | GOT  next={STATE_NAMES[got['next_state']]}"
        f" cmd_valid={got['cmd_valid']}"
        f" issue_cmd={V_CMD_NAMES.get(got['issue_cmd'], got['issue_cmd'])}"
        f" flush={got['flush']}"
        f" | EXP  next={STATE_NAMES[int(expected.next_state)]}"
        f" cmd_valid={exp_cmd_valid}"
        f" issue_cmd={V_CMD_NAMES.get(exp_sv_cmd, 'None')}"
        f" flush=0"
        + (f" | REASON: {reason}" if status == "FAIL" else "")
    )


def log_snoop(dut, state, event, got, expected, status, reason):
    """Log a snoop transition with full GOT/EXP and PASS/FAIL on every call."""
    dut._log.info(
        f"  [SNOOP] [{status}] "
        f"{STATE_NAMES[int(state)]} + {SNOOP_NAMES[int(event)]}"
        f" | GOT  next={STATE_NAMES[got['next_state']]}"
        f" flush={got['flush']}"
        f" cmd_valid={got['cmd_valid']}"
        f" | EXP  next={STATE_NAMES[int(expected.next_state)]}"
        f" flush={int(expected.flush)}"
        f" cmd_valid=0"
        + (f" | REASON: {reason}" if status == "FAIL" else "")
    )


# ============================================================================
# Tests
# ============================================================================

@cocotb.test()
async def test_reset(dut):
    """After reset, next_state must be INVALID and all outputs idle."""
    await initialise(dut)
    got = read_outputs(dut)

    passed = (
        got["next_state"] == int(MSIState.INVALID) and
        got["cmd_valid"]  == 0 and
        got["flush"]      == 0
    )
    status = "PASS" if passed else "FAIL"
    dut._log.info(
        f"  [RESET] [{status}]"
        f" | GOT  next={STATE_NAMES[got['next_state']]}"
        f" cmd_valid={got['cmd_valid']} flush={got['flush']}"
        f" | EXP  next=INVALID cmd_valid=0 flush=0"
    )

    assert got["next_state"] == int(MSIState.INVALID), \
        f"next_state={STATE_NAMES[got['next_state']]} expected INVALID"
    assert got["cmd_valid"]  == 0, f"cmd_valid={got['cmd_valid']} expected 0"
    assert got["flush"]      == 0, f"flush={got['flush']} expected 0"


@cocotb.test()
async def test_all_processor_transitions(dut):
    """
    Exhaustively test all 6 processor event transitions (MSIState x ProcessorEvent).
    Outputs sampled BEFORE rising edge — combinational outputs reflect the active transition.
    Every combination logged with PASS/FAIL regardless of outcome.
    """
    await initialise(dut)
    dut._log.info("  === Processor Event Transitions (6 combinations) ===")

    failures = []

    for state, event in product(MSIState, ProcessorEvent):
        await drive_to_state(dut, state)

        # Drive event
        dut.proc_valid.value  = 1
        dut.snoop_valid.value = 0
        dut.proc_event.value  = int(event)
        dut.snoop_event.value = 0

        # ---- SAMPLE BEFORE CLOCK EDGE ----
        # At this point CS = target state, event is driven, NS is combinational.
        # After RisingEdge, CS would advance to NS and outputs would change.
        await Timer(1, unit='ns')
        got      = read_outputs(dut)
        expected = on_processor_event(state, event)

        passed, reason = check_proc(got, expected)
        status = "PASS" if passed else "FAIL"
        log_proc(dut, state, event, got, expected, status, reason)

        if not passed:
            failures.append(
                f"PROC {STATE_NAMES[int(state)]} + {PROC_NAMES[int(event)]}: {reason}"
            )

        # Advance state — must happen AFTER output capture
        await RisingEdge(dut.clk_i)
        await FallingEdge(dut.clk_i)
        dut.proc_valid.value  = 0
        dut.snoop_valid.value = 0
        await Timer(1, unit='ns')

    total = len(list(product(MSIState, ProcessorEvent)))
    dut._log.info(f"  Processor transitions: {total - len(failures)}/{total} passed")
    for f in failures:
        dut._log.warning(f"  FAILED: {f}")
    assert not failures, f"{len(failures)} processor transition(s) failed"


@cocotb.test()
async def test_all_snoop_transitions(dut):
    """
    Exhaustively test all 9 snoop event transitions (MSIState x SnoopEvent).
    Outputs sampled BEFORE rising edge — combinational outputs reflect the active transition.
    Every combination logged with PASS/FAIL regardless of outcome.
    """
    await initialise(dut)
    dut._log.info("  === Snoop Event Transitions (9 combinations) ===")

    failures = []

    for state, event in product(MSIState, SnoopEvent):
        await drive_to_state(dut, state)

        # Drive snoop event
        dut.snoop_valid.value = 1
        dut.proc_valid.value  = 0
        dut.snoop_event.value = int(event)
        dut.proc_event.value  = 0

        # ---- SAMPLE BEFORE CLOCK EDGE ----
        await Timer(1, unit='ns')
        got      = read_outputs(dut)
        expected = on_snoop_event(state, event)

        passed, reason = check_snoop(got, expected)
        status = "PASS" if passed else "FAIL"
        log_snoop(dut, state, event, got, expected, status, reason)

        if not passed:
            failures.append(
                f"SNOOP {STATE_NAMES[int(state)]} + {SNOOP_NAMES[int(event)]}: {reason}"
            )

        # Advance state
        await RisingEdge(dut.clk_i)
        await FallingEdge(dut.clk_i)
        dut.snoop_valid.value = 0
        dut.proc_valid.value  = 0
        await Timer(1, unit='ns')

    total = len(list(product(MSIState, SnoopEvent)))
    dut._log.info(f"  Snoop transitions: {total - len(failures)}/{total} passed")
    for f in failures:
        dut._log.warning(f"  FAILED: {f}")
    assert not failures, f"{len(failures)} snoop transition(s) failed"


@cocotb.test()
async def test_idle_no_valid(dut):
    """
    Both valids low — next_state must hold CS, cmd_valid=0, flush=0.
    Tests all 3 states. Every state logged with PASS/FAIL.
    """
    await initialise(dut)
    dut._log.info("  === Idle (No Valid) — 3 combinations ===")

    failures = []

    for state in MSIState:
        await drive_to_state(dut, state)

        dut.proc_valid.value  = 0
        dut.snoop_valid.value = 0
        await Timer(1, unit='ns')

        got    = read_outputs(dut)
        passed = (
            got["next_state"] == int(state) and
            got["cmd_valid"]  == 0 and
            got["flush"]      == 0
        )
        status = "PASS" if passed else "FAIL"
        reason = ""
        if not passed:
            if got["next_state"] != int(state):
                reason = f"next_state={STATE_NAMES[got['next_state']]} expected {STATE_NAMES[int(state)]}"
            elif got["cmd_valid"] != 0:
                reason = f"cmd_valid={got['cmd_valid']} expected 0"
            else:
                reason = f"flush={got['flush']} expected 0"
            failures.append(f"IDLE {STATE_NAMES[int(state)]}: {reason}")

        dut._log.info(
            f"  [IDLE] [{status}] current={STATE_NAMES[int(state)]}"
            f" | GOT  next={STATE_NAMES[got['next_state']]}"
            f" cmd_valid={got['cmd_valid']} flush={got['flush']}"
            f" | EXP  next={STATE_NAMES[int(state)]} cmd_valid=0 flush=0"
            + (f" | REASON: {reason}" if status == "FAIL" else "")
        )

        await RisingEdge(dut.clk_i)
        await FallingEdge(dut.clk_i)

    total = len(list(MSIState))
    dut._log.info(f"  Idle transitions: {total - len(failures)}/{total} passed")
    for f in failures:
        dut._log.warning(f"  FAILED: {f}")
    assert not failures, f"{len(failures)} idle transition(s) failed"


@cocotb.test()
async def test_both_valid_illegal(dut):
    """
    proc_valid and snoop_valid simultaneously high is a protocol violation.
    Verify flush and cmd_valid are never both high at the same time.
    Tests all 3 states. Every state logged with PASS/FAIL.
    """
    await initialise(dut)
    dut._log.info("  === Illegal: Both Valid High — 3 combinations ===")

    failures = []

    for state in MSIState:
        await drive_to_state(dut, state)

        dut.proc_valid.value  = 1
        dut.snoop_valid.value = 1
        dut.proc_event.value  = int(ProcessorEvent.PR_WR)
        dut.snoop_event.value = int(SnoopEvent.BUS_RDX)
        await Timer(1, unit='ns')

        got    = read_outputs(dut)
        passed = not (got["flush"] == 1 and got["cmd_valid"] == 1)
        status = "PASS" if passed else "FAIL"
        reason = "flush=1 and cmd_valid=1 simultaneously" if not passed else ""

        if not passed:
            failures.append(f"ILLEGAL {STATE_NAMES[int(state)]}: {reason}")

        dut._log.info(
            f"  [ILLEGAL] [{status}] current={STATE_NAMES[int(state)]}"
            f" | GOT  next={STATE_NAMES[got['next_state']]}"
            f" cmd_valid={got['cmd_valid']} flush={got['flush']}"
            + (f" | REASON: {reason}" if status == "FAIL" else "")
        )

        await RisingEdge(dut.clk_i)
        await FallingEdge(dut.clk_i)
        dut.proc_valid.value  = 0
        dut.snoop_valid.value = 0

    total = len(list(MSIState))
    dut._log.info(f"  Illegal input tests: {total - len(failures)}/{total} passed")
    for f in failures:
        dut._log.warning(f"  FAILED: {f}")
    assert not failures, f"{len(failures)} illegal input test(s) failed"


@cocotb.test()
async def test_sequential_transitions(dut):
    """
    Drive a realistic cache access sequence and verify each step:
    INVALID --(PR_RD)--> SHARED --(PR_WR)--> MODIFIED --(BUS_RDX)--> INVALID
    Outputs sampled BEFORE each clock edge. Every step logged with PASS/FAIL.
    """
    await initialise(dut)
    dut._log.info("  === Sequential Transitions ===")

    sequence = [
        (True,  ProcessorEvent.PR_RD, MSIState.INVALID,  on_processor_event),
        (True,  ProcessorEvent.PR_WR, MSIState.SHARED,   on_processor_event),
        (False, SnoopEvent.BUS_RDX,   MSIState.MODIFIED, on_snoop_event),
    ]

    failures = []

    for step, (is_proc, event, state, ref_fn) in enumerate(sequence):
        if is_proc:
            dut.proc_valid.value  = 1
            dut.snoop_valid.value = 0
            dut.proc_event.value  = int(event)
            dut.snoop_event.value = 0
        else:
            dut.snoop_valid.value = 1
            dut.proc_valid.value  = 0
            dut.snoop_event.value = int(event)
            dut.proc_event.value  = 0

        # Sample BEFORE clock edge
        await Timer(1, unit='ns')
        got      = read_outputs(dut)
        expected = ref_fn(state, event)

        passed = got["next_state"] == int(expected.next_state)
        status = "PASS" if passed else "FAIL"
        reason = (
            f"next_state={STATE_NAMES[got['next_state']]} "
            f"expected {STATE_NAMES[int(expected.next_state)]}"
            if not passed else ""
        )

        if not passed:
            failures.append(f"SEQ step {step} {STATE_NAMES[int(state)]} + {event.name}: {reason}")

        dut._log.info(
            f"  [SEQ {step}] [{status}]"
            f" {STATE_NAMES[int(state)]} + {event.name}"
            f" | GOT  next={STATE_NAMES[got['next_state']]}"
            f" | EXP  next={STATE_NAMES[int(expected.next_state)]}"
            + (f" | REASON: {reason}" if status == "FAIL" else "")
        )

        await RisingEdge(dut.clk_i)
        await FallingEdge(dut.clk_i)

    total = len(sequence)
    dut._log.info(f"  Sequential transitions: {total - len(failures)}/{total} passed")
    for f in failures:
        dut._log.warning(f"  FAILED: {f}")
    assert not failures, f"{len(failures)} sequential transition(s) failed"


@cocotb.test()
async def test_modified_busupgr_protocol_violation(dut):
    """
    MODIFIED + BUS_UPGR is a protocol violation.
    Verify DUT stays MODIFIED and does not assert flush.
    """
    await initialise(dut)
    await drive_to_state(dut, MSIState.MODIFIED)

    dut.snoop_valid.value = 1
    dut.proc_valid.value  = 0
    dut.snoop_event.value = int(SnoopEvent.BUS_UPGR)
    dut.proc_event.value  = 0

    # Sample BEFORE clock edge
    await Timer(1, unit='ns')
    got      = read_outputs(dut)
    expected = on_snoop_event(MSIState.MODIFIED, SnoopEvent.BUS_UPGR)

    passed = (got["next_state"] == int(MSIState.MODIFIED) and got["flush"] == 0)
    status = "PASS" if passed else "FAIL"
    reason = ""
    if not passed:
        if got["next_state"] != int(MSIState.MODIFIED):
            reason = f"next_state={STATE_NAMES[got['next_state']]} expected MODIFIED"
        else:
            reason = f"flush={got['flush']} expected 0"

    dut._log.info(
        f"  [VIOLATION] [{status}] MODIFIED + BUS_UPGR"
        f" | GOT  next={STATE_NAMES[got['next_state']]} flush={got['flush']}"
        f" | EXP  next=MODIFIED flush=0"
        + (f" | REASON: {reason}" if status == "FAIL" else "")
    )

    await RisingEdge(dut.clk_i)
    await FallingEdge(dut.clk_i)

    assert passed, f"Protocol violation not handled gracefully: {reason}"
    