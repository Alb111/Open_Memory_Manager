import cocotb
from cocotb.triggers import RisingEdge, Timer
from cocotb.clock import Clock
import random


# ─── Reference Model ──────────────────────────────────────────────────────────

class WeightedRoundRobinModel:
    """
    Mirrors the RTL exactly:
      - Each call to step() models ONE clock cycle.
      - If req[curr_ptr] is asserted  → grant it, decrement credit.
            credit hits 0             → advance pointer, reload credit.
      - If req[curr_ptr] is NOT asserted → advance pointer, reload credit.
            grant is 0 this cycle.
    The combinational grant_o is returned for the cycle BEFORE the clock edge.
    """
    def __init__(self, num_requesters, weights):
        self.num_requesters = num_requesters
        self.weights = weights
        self.curr_ptr = 0
        self.credit_cnt = weights[0]

    def reset(self):
        self.curr_ptr = 0
        self.credit_cnt = self.weights[0]

    def step(self, requests):
        """
        Compute combinational grant for this cycle, then update state
        (simulating what the RTL clocks in on the rising edge).
        Returns the grant list for this cycle.
        """
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


# ─── Constants ────────────────────────────────────────────────────────────────

NUM_REQ = 2
WEIGHTS = [1, 1]   # matches RTL default WEIGHTS = {3'd1, 3'd1}


# ─── Utilities ────────────────────────────────────────────────────────────────

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
    """Assert active-low reset for 5 cycles then release."""
    dut.rst_ni.value = 0   # assert reset (active low)
    dut.req_i.value = 0
    for _ in range(5):
        await RisingEdge(dut.clk_i)
    dut.rst_ni.value = 1   # deassert reset
    await Timer(1, unit="ns")   # let combinational outputs settle after reset

async def drive_and_sample(dut, req_int):
    """
    Zero-cycle grant protocol:
      1. Drive req_i.
      2. Wait 1 ns for combinational grant_o to settle.
      -- Caller reads grant_o here, BEFORE any clock edge --
    """
    dut.req_i.value = req_int
    await Timer(1, unit="ns")

async def clock_step(dut):
    """Commit one rising edge (clocks in next_ptr / next_credit_cnt)."""
    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ns")   # settle after clock


# ─── Tests ────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_reset_state(dut):
    """grant_o must be zero while rst_ni is asserted (low), regardless of requests."""
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
    """No requests should produce no grants."""
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
    """
    Only req[0] active.
    With weights [1,1] the pointer alternates every cycle, so req[0] is only
    served on even cycles (ptr=0) and grant=0 on odd cycles (ptr=1, miss →
    rotate). Verify against the reference model.
    """
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
    """
    Only req[1] active.
    Pointer starts at 0; req[0] absent → rotate to 1, grant req[1], rotate
    back to 0, etc. Verify against the reference model.
    """
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
    """Both requesting — verify grant pattern matches reference model weights [1,1]."""
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
    """Grant must always be one-hot (or zero) — never two bits set simultaneously."""
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
    """req_o must always mirror req_i combinationally."""
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
    """
    Randomized test: each cycle drive a random request, sample the
    combinational grant BEFORE the clock edge, advance the reference model
    in lockstep, then clock.
    """
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


# ─── Additional Functionality Tests ───────────────────────────────────────────

@cocotb.test()
async def test_mid_run_reset(dut):
    """
    Assert reset in the middle of normal operation, then release it.
    After reset de-assertion:
      - pointer must be back at 0
      - credit must be reloaded to weight_table[0]
      - grant output must immediately match a freshly-reset reference model
    """
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
    """
    Start with both requesters active, then drop one mid-sequence.
    Verify the arbiter stops granting the dropped requester and the
    reference model stays in sync.
    """
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
    """
    req[1] is silent for several cycles (pointer bounces past it), then
    asserts.  Verify it gets served correctly on the next opportunity and
    the reference model agrees throughout.
    """
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
    """
    With both requesters active for 100 cycles and equal weights [1,1],
    each requester must receive exactly half the total grants (±1 for any
    odd-length run).  This catches implementations that silently starve
    one requester.
    """
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
    """
    grant_o must not glitch between the moment req_i is driven and the
    next clock edge.  Sample at 1 ns and again at 8 ns (just before the
    rising edge) and verify they are identical.
    """
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
    """
    Drive only req[0] and req[1] in strict alternation for many cycles.
    The pointer must wrap from index 1 back to index 0 without getting
    stuck, and the reference model must agree every cycle.
    """
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
    """
    Exhaustive check over all non-zero 2-bit request patterns for 10 cycles
    each: a grant bit must never be set for a requester that is not active.
    """
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
    """
    Advance the pointer to req[1] by running one cycle with only req[0]
    active (miss on ptr=0 → ptr advances to 1 is NOT what happens;
    instead grant on ptr=0 with weight=1 → ptr advances to 1).
    Then assert reset and confirm pointer is back at 0 by checking that
    req[0] is granted on the very first cycle after reset.
    """
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
