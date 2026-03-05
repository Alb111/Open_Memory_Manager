# test_wrr_arbiter.py
import os
from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge, Timer
from cocotb.clock import Clock
# from cocotb.result import TestFailure
from cocotb_tools.runner import get_runner
import random

sim = os.getenv("SIM", "icarus")
pdk_root = os.getenv("PDK_ROOT", Path("~/.ciel").expanduser())
pdk = os.getenv("PDK", "gf180mcuD")
scl = os.getenv("SCL", "gf180mcu_fd_sc_mcu7t5v0")
gl = os.getenv("GL", False)
slot = os.getenv("SLOT", "1x1")

# Python Reference Model 
class WeightedRoundRobinModel:

    def __init__(self, num_requesters, weights):
        if len(weights) != num_requesters:
            raise ValueError("Weights must match number of requesters")

        self.num_requesters = num_requesters
        self.weights = weights
        self.current_index = 0
        self.remaining_credits = weights[0]
        self.max_possible_iterations = sum(weights)

    def arbitrate(self, requests):

        if sum(requests) == 0:
            return [0] * self.num_requesters

        attempts = 0
        while attempts < self.max_possible_iterations:

            if requests[self.current_index] == 1:
                grant = [0] * self.num_requesters
                grant[self.current_index] = 1

                self.remaining_credits -= 1

                if self.remaining_credits == 0:
                    self.current_index = (self.current_index + 1) % self.num_requesters
                    self.remaining_credits = self.weights[self.current_index]

                return grant

            else:
                self.current_index = (self.current_index + 1) % self.num_requesters
                self.remaining_credits = self.weights[self.current_index]
                attempts += 1

        raise Exception("Arbitration timeout")


# Utility Functions
def onehot_to_list(val, width=2):
    return [(val >> i) & 1 for i in range(width)]



def list_to_int(lst):
    value = 0
    for i, bit in enumerate(lst):
        value |= (bit << i)
    return value



# Reset Sequence
async def reset_dut(dut):
    dut.rst_ni.value = 0
    dut.req_i.value = 0
    for _ in range(5):
        await RisingEdge(dut.clk_i)
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)


# Main Test
@cocotb.test()
async def test_weighted_round_robin(dut):

    NUM_REQ = 2
    WEIGHTS = [3, 1]   # Change freely for testing

    # Start clock
    clock = Clock(dut.clk_i, 10, unit="ns")
    cocotb.start_soon(clock.start())

    # Reset
    await reset_dut(dut)

    # Instantiate reference model
    model = WeightedRoundRobinModel(NUM_REQ, WEIGHTS)

    dut._log.info("Starting WRR arbitration test")

    # Directed Test: Both Always Requesting
    # Expect 3 grants to req0, 1 grant to req1 repeating

    dut._log.info("Running directed weighted test")

    dut.req_i.value = 0b11

    for cycle in range(20):
        await RisingEdge(dut.clk_i)

        dut_grant = onehot_to_list(int(dut.grant_o.value), NUM_REQ)
        expected_grant = model.arbitrate([1, 1])

        # if dut_grant != expected_grant:
        #     raise TestFailure(
        #         f"Mismatch at cycle {cycle}: "
        #         f"DUT={dut_grant} Expected={expected_grant}"
        #     )
         
        assert(dut_grant == expected_grant), f"Mismatch at cycle {cycle}: \n DUT={dut_grant} Expected={expected_grant}"

        

    dut._log.info("Directed weighted test PASSED")

    # Randomized Request Test

    dut._log.info("Running randomized request test")

    dut._log.info(" hellllllllllllllllo")
    for cycle in range(100):

        # Random request pattern
        req_vec = [random.randint(0, 1) for _ in range(NUM_REQ)]
        dut.req_o.value = list_to_int(req_vec)

        await RisingEdge(dut.clk_i)


        # dut._log.info(f" hellllllllllllllllo {dut.grant_o.value}")
        dut_grant = onehot_to_list(int(dut.grant_o.value), NUM_REQ)
        expected_grant = model.arbitrate(req_vec)

        # if dut_grant != expected_grant:
        #     raise TestFailure(
        #         f"Random Test Mismatch at cycle {cycle}: "
        #         f"REQ={req_vec} DUT={dut_grant} Expected={expected_grant}"
        #     )

        assert(dut_grant == expected_grant), f"Mismatch at cycle {cycle}: \n DUT={dut_grant} Expected={expected_grant}"

    dut._log.info("Randomized test PASSED")
    dut._log.info("All WRR tests PASSED successfully")

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
