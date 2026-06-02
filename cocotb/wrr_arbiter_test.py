import os
import random
import logging
from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge, Timer
from cocotb_tools.runner import get_runner
from cocotb.clock import Clock
import random


sim = os.getenv("SIM", "icarus")
pdk_root = os.getenv("PDK_ROOT", Path("~/.ciel").expanduser())
pdk = os.getenv("PDK", "gf180mcuD")
scl = os.getenv("SCL", "gf180mcu_fd_sc_mcu7t5v0")
gl = os.getenv("GL", False)
slot = os.getenv("SLOT", "1x1")

hdl_toplevel = "wrr_arbiter.sv"



# ─── Reference Model ──────────────────────────────────────────────────────────

class WeightedRoundRobinModel:
    # Mirrors RTL: each step() models one clock cycle.
    # Grant curr_ptr if requested, decrement credit; advance pointer when credit hits 0 or miss.
    def __init__(self, num_requesters, weights):
        self.num_requesters = num_requesters
        self.weights = weights
        self.curr_ptr = 0
        self.credit_cnt = weights[0]

    def reset(self):
        self.curr_ptr = 0
        self.credit_cnt = self.weights[0]

    def step(self, requests):
        # Returns combinational grant for this cycle, then updates state.
        grant = [0] * self.num_requesters

        if requests[self.curr_ptr] == 1:
            grant[self.curr_ptr] = 1
            if self.credit_cnt > 1:
                self.credit_cnt -= 1
            else:
                self.curr_ptr = (self.curr_ptr + 1) % self.num_requesters
                self.credit_cnt = self.weights[self.curr_ptr]
        else:
            self.curr_ptr = (self.curr_ptr + 1) % self.num_requesters
            self.credit_cnt = self.weights[self.curr_ptr]

        return grant


NUM_REQ = 2
WEIGHTS = [1, 1]

def onehot_to_list(val, width=NUM_REQ):
    return [(val >> i) & 1 for i in range(width)]

def list_to_int(lst):
    value = 0
    for i, bit in enumerate(lst):
        value |= (bit << i)
    return value

def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())

async def reset_dut(dut):
    # Assert active-low reset for 5 cycles then release.
    dut.rst_ni.value = 0   # assert reset (active low)
    dut.req_i.value = 0
    for _ in range(5):
        await RisingEdge(dut.clk_i)
    dut.rst_ni.value = 1   # deassert reset
    await Timer(1, unit="ns")

async def drive_and_sample(dut, req_int):
    # Drive req_i, wait 1 ns for combinational grant_o to settle.
    dut.req_i.value = req_int
    await Timer(1, unit="ns")

async def clock_step(dut):
    # Commit one rising edge, then settle.
    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ns")   # settle after clock


# ─── Tests ────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_reset_state(dut):
    # grant_o must be zero while rst_ni is asserted, regardless of requests.
    start_clock(dut)

    dut.rst_ni.value = 0   # assert reset (active low)
    dut.req_i.value = 0b11
    for cycle in range(5):
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")
        grant = int(dut.grant_o.value)
        assert grant == 0, (
            f"Cycle {cycle}: grant_o={bin(grant)} should be 0 during reset"
        )
    dut.rst_ni.value = 1   # deassert reset


@cocotb.test()
async def test_no_request(dut):
    # No requests should produce no grants.
    start_clock(dut)
    await reset_dut(dut)

    for cycle in range(10):
        await drive_and_sample(dut, 0b00)
        grant = int(dut.grant_o.value)
        assert grant == 0, (
            f"Cycle {cycle}: grant_o={bin(grant)}, expected 0 with no requests"
        )
        await clock_step(dut)


@cocotb.test()
async def test_single_requester_0(dut):
    # Only req[0] active; verify grant pattern matches reference model.
    start_clock(dut)
    await reset_dut(dut)

    model = WeightedRoundRobinModel(NUM_REQ, WEIGHTS)

    for cycle in range(10):
        await drive_and_sample(dut, 0b01)
        dut_grant    = onehot_to_list(int(dut.grant_o.value))
        expect_grant = model.step([1, 0])
        assert dut_grant == expect_grant, (
            f"Cycle {cycle}: got {dut_grant}, expected {expect_grant}"
        )
        await clock_step(dut)


@cocotb.test()
async def test_single_requester_1(dut):
    # Only req[1] active; verify grant pattern matches reference model.
    start_clock(dut)
    await reset_dut(dut)

    model = WeightedRoundRobinModel(NUM_REQ, WEIGHTS)

    for cycle in range(10):
        await drive_and_sample(dut, 0b10)
        dut_grant    = onehot_to_list(int(dut.grant_o.value))
        expect_grant = model.step([0, 1])
        assert dut_grant == expect_grant, (
            f"Cycle {cycle}: got {dut_grant}, expected {expect_grant}"
        )
        await clock_step(dut)


@cocotb.test()
async def test_weighted_both_requesting(dut):
    # Both requesting — verify grant pattern matches reference model weights [1,1].
    start_clock(dut)
    await reset_dut(dut)

    model = WeightedRoundRobinModel(NUM_REQ, WEIGHTS)

    for cycle in range(20):
        await drive_and_sample(dut, 0b11)
        dut_grant    = onehot_to_list(int(dut.grant_o.value))
        expect_grant = model.step([1, 1])
        assert dut_grant == expect_grant, (
            f"Cycle {cycle}: DUT={dut_grant} Expected={expect_grant}"
        )
        await clock_step(dut)


@cocotb.test()
async def test_grant_is_onehot(dut):
    # Grant must always be one-hot or zero — never two bits set simultaneously.
    start_clock(dut)
    await reset_dut(dut)

    for cycle in range(50):
        req = random.randint(1, 3)
        await drive_and_sample(dut, req)
        g = int(dut.grant_o.value)
        assert g & (g - 1) == 0, (
            f"Cycle {cycle}: grant_o={bin(g)} is not one-hot"
        )
        await clock_step(dut)


@cocotb.test()
async def test_req_passthrough(dut):
    # req_o must always mirror req_i combinationally.
    start_clock(dut)
    await reset_dut(dut)

    for cycle in range(20):
        val = random.randint(0, 3)
        await drive_and_sample(dut, val)
        assert int(dut.req_o.value) == val, (
            f"Cycle {cycle}: req_o={int(dut.req_o.value)}, expected {val}"
        )
        await clock_step(dut)


@cocotb.test()
async def test_randomized(dut):
    # Random requests each cycle; verify grant matches reference model in lockstep.
    start_clock(dut)
    await reset_dut(dut)

    model = WeightedRoundRobinModel(NUM_REQ, WEIGHTS)

    for cycle in range(200):
        req_vec = [random.randint(0, 1) for _ in range(NUM_REQ)]
        req_int = list_to_int(req_vec)

        await drive_and_sample(dut, req_int)
        dut_grant    = onehot_to_list(int(dut.grant_o.value))
        expect_grant = model.step(req_vec)

        assert dut_grant == expect_grant, (
            f"Cycle {cycle}: REQ={req_vec} DUT={dut_grant} Expected={expect_grant}"
        )

        await clock_step(dut)

@cocotb.test()
async def test_mid_run_reset(dut):
    # Assert reset mid-operation; verify pointer and credit reload correctly after release.
    start_clock(dut)
    await reset_dut(dut)

    model = WeightedRoundRobinModel(NUM_REQ, WEIGHTS)

    # Run for a few cycles to move the pointer away from its reset position
    for _ in range(5):
        await drive_and_sample(dut, 0b11)
        model.step([1, 1])
        await clock_step(dut)

    # Assert reset mid-run (active low)
    dut.rst_ni.value = 0
    dut.req_i.value = 0b11
    for cycle in range(3):
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")
        grant = int(dut.grant_o.value)
        assert grant == 0, (
            f"Mid-reset cycle {cycle}: grant_o={bin(grant)} should be 0"
        )

    # Release reset — pointer must be at 0, credits reloaded
    dut.rst_ni.value = 1
    await Timer(1, unit="ns")

    # Re-sync reference model to reset state
    model.reset()

    # Verify post-reset behaviour matches a fresh model for 10 cycles
    for cycle in range(10):
        await drive_and_sample(dut, 0b11)
        dut_grant    = onehot_to_list(int(dut.grant_o.value))
        expect_grant = model.step([1, 1])
        assert dut_grant == expect_grant, (
            f"Post-reset cycle {cycle}: DUT={dut_grant} Expected={expect_grant}"
        )
        await clock_step(dut)


@cocotb.test()
async def test_req_deassert_mid_sequence(dut):
    # Drop req[1] mid-sequence; verify it stops being granted and model stays in sync.
    start_clock(dut)
    await reset_dut(dut)

    model = WeightedRoundRobinModel(NUM_REQ, WEIGHTS)

    # Phase 1: both requesting for 6 cycles
    for cycle in range(6):
        req_vec = [1, 1]
        await drive_and_sample(dut, list_to_int(req_vec))
        dut_grant    = onehot_to_list(int(dut.grant_o.value))
        expect_grant = model.step(req_vec)
        assert dut_grant == expect_grant, (
            f"Phase1 cycle {cycle}: DUT={dut_grant} Expected={expect_grant}"
        )
        await clock_step(dut)

    # Phase 2: req[1] drops out — only req[0] active
    for cycle in range(8):
        req_vec = [1, 0]
        await drive_and_sample(dut, list_to_int(req_vec))
        dut_grant    = onehot_to_list(int(dut.grant_o.value))
        expect_grant = model.step(req_vec)
        assert dut_grant == expect_grant, (
            f"Phase2 cycle {cycle}: DUT={dut_grant} Expected={expect_grant}"
        )
        # req[1] must never be granted when it is not requesting
        assert dut_grant[1] == 0, (
            f"Phase2 cycle {cycle}: req[1] was granted despite not requesting"
        )
        await clock_step(dut)


@cocotb.test()
async def test_req_assert_after_pointer_passes(dut):
    # req[1] silent for several cycles, then asserts; verify it's served correctly.
    start_clock(dut)
    await reset_dut(dut)

    model = WeightedRoundRobinModel(NUM_REQ, WEIGHTS)

    # Only req[0] active for 4 cycles (pointer will bounce 0→1→0→1...)
    for cycle in range(4):
        req_vec = [1, 0]
        await drive_and_sample(dut, list_to_int(req_vec))
        dut_grant    = onehot_to_list(int(dut.grant_o.value))
        expect_grant = model.step(req_vec)
        assert dut_grant == expect_grant, (
            f"Silent cycle {cycle}: DUT={dut_grant} Expected={expect_grant}"
        )
        await clock_step(dut)

    # Now both request — req[1] should be served on its turn
    for cycle in range(10):
        req_vec = [1, 1]
        await drive_and_sample(dut, list_to_int(req_vec))
        dut_grant    = onehot_to_list(int(dut.grant_o.value))
        expect_grant = model.step(req_vec)
        assert dut_grant == expect_grant, (
            f"Both-active cycle {cycle}: DUT={dut_grant} Expected={expect_grant}"
        )
        await clock_step(dut)


@cocotb.test()
async def test_fairness_grant_counts(dut):
    # With equal weights [1,1], each requester must receive ~50% of grants over 100 cycles.
    start_clock(dut)
    await reset_dut(dut)

    NUM_CYCLES = 100
    grant_counts = [0, 0]

    for _ in range(NUM_CYCLES):
        await drive_and_sample(dut, 0b11)
        g = onehot_to_list(int(dut.grant_o.value))
        for i in range(NUM_REQ):
            grant_counts[i] += g[i]
        await clock_step(dut)

    total = sum(grant_counts)
    for i in range(NUM_REQ):
        ratio = grant_counts[i] / total if total else 0
        assert abs(ratio - 0.5) <= 0.05, (
            f"req[{i}] got {grant_counts[i]}/{total} grants "
            f"({ratio:.1%}), expected ~50% for weight=1"
        )


@cocotb.test()
async def test_grant_stable_between_clocks(dut):
    # grant_o must not glitch; sample at 1 ns and 8 ns and verify they match.
    start_clock(dut)
    await reset_dut(dut)

    for cycle in range(30):
        req = random.randint(0, 3)
        dut.req_i.value = req

        # Early sample (just after drive)
        await Timer(1, unit="ns")
        grant_early = int(dut.grant_o.value)

        # Late sample (just before clock edge, 1 ns before rising edge of
        # a 10 ns period clock means we sample at t+8 ns after the drive)
        await Timer(7, unit="ns")
        grant_late = int(dut.grant_o.value)

        assert grant_early == grant_late, (
            f"Cycle {cycle}: grant_o glitched — "
            f"early={bin(grant_early)} late={bin(grant_late)}"
        )

        # Consume the remaining time to the clock edge
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")


@cocotb.test()
async def test_pointer_wraps_correctly(dut):
    # Alternate single requester each cycle; verify pointer wraps and model agrees.
    start_clock(dut)
    await reset_dut(dut)

    model = WeightedRoundRobinModel(NUM_REQ, WEIGHTS)

    for cycle in range(20):
        # Alternate which single requester is active each cycle
        req_vec = [1, 0] if cycle % 2 == 0 else [0, 1]
        await drive_and_sample(dut, list_to_int(req_vec))
        dut_grant    = onehot_to_list(int(dut.grant_o.value))
        expect_grant = model.step(req_vec)
        assert dut_grant == expect_grant, (
            f"Cycle {cycle}: REQ={req_vec} DUT={dut_grant} Expected={expect_grant}"
        )
        await clock_step(dut)


@cocotb.test()
async def test_grant_only_to_active_requesters(dut):
    # For all non-zero request patterns, a grant bit must never be set for an inactive requester.
    start_clock(dut)
    await reset_dut(dut)

    for req_int in range(1, 1 << NUM_REQ):   # 0b01 and 0b10 and 0b11
        req_vec = [(req_int >> i) & 1 for i in range(NUM_REQ)]
        for cycle in range(10):
            await drive_and_sample(dut, req_int)
            g = onehot_to_list(int(dut.grant_o.value))
            for i in range(NUM_REQ):
                if req_vec[i] == 0:
                    assert g[i] == 0, (
                        f"req_pattern={bin(req_int)} cycle {cycle}: "
                        f"grant[{i}] set but req[{i}] not active"
                    )
            await clock_step(dut)

        # Reset between patterns so pointer state doesn't carry over
        await reset_dut(dut)


@cocotb.test()
async def test_reset_clears_pointer_and_resumes(dut):
    # Advance pointer to 1, assert reset, verify pointer returns to 0 on first post-reset grant.
    start_clock(dut)
    await reset_dut(dut)

    # One cycle with both requesting: ptr=0 grants req[0], advances to ptr=1
    await drive_and_sample(dut, 0b11)
    await clock_step(dut)

    # Now ptr should be 1. Assert reset (active low).
    dut.rst_ni.value = 0
    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ns")
    assert int(dut.grant_o.value) == 0, "grant_o must be 0 during reset"

    dut.rst_ni.value = 1   # deassert reset
    await Timer(1, unit="ns")

    # First cycle post-reset with both requesting: ptr=0 → must grant req[0]
    await drive_and_sample(dut, 0b11)
    g = onehot_to_list(int(dut.grant_o.value))
    assert g == [1, 0], (
        f"First post-reset grant: got {g}, expected [1, 0] (ptr should be 0)"
    )

def wrr_arbiter_runner():
    proj_path = Path(__file__).resolve().parent

    sources = [
        proj_path / "../src/arb/wrr_arbiter.sv",
    ]

    build_args = []
    if sim == "icarus":
        pass
    if sim == "verilator":
        build_args = ["--timing", "--trace", "--trace-fst", "--trace-structs"]
    
    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel="wrr_arbiter",
        always=True,
        build_args=build_args,
        waves=True,
    )

    runner.test(
        hdl_toplevel="wrr_arbiter",
        test_module="wrr_arbiter_test",
        waves=True,
    )

if __name__ == "__main__":
    wrr_arbiter_runner()
