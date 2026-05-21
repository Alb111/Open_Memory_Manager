import os
import logging
from pathlib import Path
from typing import List

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer, with_timeout
from cocotb_tools.runner import get_runner

# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────

sim = os.getenv("SIM", "icarus")
log = logging.getLogger("cache_tb")
logging.basicConfig(level=logging.INFO)

from emulation.cache_v3 import CacheController
from emulation.axi_request_types import axi_request
from emulation.msi_v2 import CoherenceCmd

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

CMD_BUS_RD   = 0b000000001
CMD_BUS_RDX  = 0b000000010
CMD_BUS_UPGR = 0b000000100

BUSRD_ACK   = 0b001
BUSRDX_ACK  = 0b010
BUSUPGR_ACK = 0b100

TIMEOUT_CYCLES = 10

# ─────────────────────────────────────────────────────────────────────────────
# Golden model hook
# ─────────────────────────────────────────────────────────────────────────────

captured_dir_requests: List = []

async def dummy_directory_handler(req):
    captured_dir_requests.append(req)

    return axi_request(
        mem_valid=True,
        mem_ready=True,
        mem_instr=False,
        mem_addr=req.mem_addr,
        mem_wdata=0,
        mem_wstrb=0,
        mem_rdata=2,
    )


def coherence_cmd_to_acks(cmd: CoherenceCmd) -> int:
    if cmd == CoherenceCmd.BUS_RD:
        return BUSRD_ACK
    elif cmd == CoherenceCmd.BUS_RDX:
        return BUSRDX_ACK
    elif cmd == CoherenceCmd.BUS_UPGR:
        return BUSUPGR_ACK
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Clock
# ─────────────────────────────────────────────────────────────────────────────

async def start_clock(dut, freq_mhz=1):
    clock = Clock(dut.clk_i, 1000 / freq_mhz, unit="ns")
    cocotb.start_soon(clock.start())


# ─────────────────────────────────────────────────────────────────────────────
# Reset
# ─────────────────────────────────────────────────────────────────────────────

async def reset_dut(dut):
    dut.rst_ni.value = 1

    dut.mem_valid_i.value = 0
    dut.mem_instr_i.value = 0
    dut.mem_addr_i.value = 0
    dut.mem_wdata_i.value = 0
    dut.mem_wstrb_i.value = 0

    dut.bus_valid_i.value = 0
    dut.bus_data_i.value = 0
    dut.bus_dircmd_i.value = 0

    dut.cache_ready_i.value = 0
    dut.snoop_valid_i.value = 0

    # reset pulse
    await RisingEdge(dut.clk_i)
    dut.rst_ni.value = 0
    await RisingEdge(dut.clk_i)
    dut.rst_ni.value = 1

    # its take very long to reset all the srams
    cycles_to_reset: int = 2 * 512 
    # cycles_to_reset: int =  # any thing more then 511 caues a infinite block 
    for _ in range(cycles_to_reset):
        await RisingEdge(dut.clk_i)

    log.info("Reset complete")


# ─────────────────────────────────────────────────────────────────────────────
# Safe handshake helpers (IMPORTANT FIX)
# ─────────────────────────────────────────────────────────────────────────────

async def wait_for_signal(dut, sig):
    """Wait until a signal becomes 1 (clock-sampled safe)."""
    for _ in range(TIMEOUT_CYCLES):
        await RisingEdge(dut.clk_i)
        if sig.value == 1:
            return
    raise TimeoutError(f"{sig._name} never asserted")


# ─────────────────────────────────────────────────────────────────────────────
# Test transaction
# ─────────────────────────────────────────────────────────────────────────────

async def one_read(dut):

    captured_dir_requests.clear()

    await FallingEdge(dut.clk_i)
    # ── CPU request ─────────────────────────────────────────────
    dut.mem_valid_i.value = 1
    dut.mem_instr_i.value = 0
    dut.mem_addr_i.value = 1
    dut.mem_wdata_i.value = 0
    dut.mem_wstrb_i.value = 0
    dut.cache_ready_i.value = 1  

    await RisingEdge(dut.clk_i) 

    # golden model
    cache = CacheController(
        core_id=0,
        directory_axi_handler=dummy_directory_handler,
    )

    golden_resp = await cache.axi_handler_for_core(
        axi_request(
            mem_valid=True,
            mem_ready=False,
            mem_instr=False,
            mem_addr=1,
            mem_wdata=0,
            mem_wstrb=0,
            mem_rdata=0,
        )
    )

    # # ── Wait for DUT request to directory ───────────────────────
    for i in range(TIMEOUT_CYCLES):
        # await RisingEdge(dut.clk_i)
        await with_timeout(RisingEdge(dut.clk_i), 5000, 'ns')
        if int(dut.cache_valid_o.value) == 1:
            return
        print(f"i is {i}")

    print("heloooooooooooooooooooooooooo")
    raise TimeoutError(f"cahce_valid_o never asserted")

    # await wait_for_signal(dut, dut.cache_valid_o)

    # assert captured_dir_requests, "No directory request captured"

    # dir_req = captured_dir_requests[0]

    # # sample SAME cycle safely
    # dut_cmd = int(dut.cache_cmd_o.value)

    # assert int(dir_req.coherence_cmd) == dut_cmd, (
    #     f"Expected {dir_req.coherence_cmd}, got {dut_cmd}"
    # )

    # # ── Respond from directory ───────────────────────────────────
    # dut.bus_valid_i.value = 1
    # dut.bus_data_i.value = 2
    # dut.bus_dircmd_i.value = coherence_cmd_to_acks(dir_req.coherence_cmd)

    # # wait for DUT to accept response
    # await wait_for_signal(dut, dut.bus_ready_o)

    # dut.bus_valid_i.value = 0

    # # ── Wait for completion ─────────────────────────────────────
    # await wait_for_signal(dut, dut.mem_ready_o)

    # assert int(dut.mem_rdata_o.value) == golden_resp.mem_rdata


# ─────────────────────────────────────────────────────────────────────────────
# Test entry
# ─────────────────────────────────────────────────────────────────────────────

@cocotb.test()
async def test_simple(dut):
    await start_clock(dut)
    await reset_dut(dut)
    await one_read(dut)

# ════════════════════════════════════════════════════════════════════════════
#  Runner
# ════════════════════════════════════════════════════════════════════════════

def cache_controller_test():
    proj_path = Path(__file__).resolve().parent
    pdk_root  = Path("../gf180mcu")

    sources = [
        proj_path / "../src/msi_protocol/apply_wstrb.sv",
        proj_path / "../src/msi_protocol/on_processor_event_state_machine.sv",
        proj_path / "../src/msi_protocol/on_snoop_event_state_machine.sv",
        proj_path / "../src/msi_protocol/cache_controller.sv",
        proj_path / "../src/msi_protocol/outbound_arbiter.sv",
        proj_path / "../src/mem_ctrl/cache_dir_memory/mem128x4.sv",
        proj_path / "../src/mem_ctrl/cache_dir_memory/mem128x32.sv",
        proj_path / "../src/mem_ctrl/cache_dir_memory/cache_mem.sv",
        proj_path / "../src/mem_ctrl/cache_dir_memory/two_port_cache_mem.sv",
        pdk_root / "gf180mcuD/libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram512x8m8wm1.v",
        pdk_root / "gf180mcuD/libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram64x8m8wm1.v",
    ]

    build_args = []

    if sim == "verilator":
        build_args = [
            "--timing",
            "--trace",
            "--trace-fst",
            "--trace-structs",
        ]

    runner = get_runner(sim)

    runner.build(
        sources=sources,
        hdl_toplevel="cache_controller",
        always=True,
        build_args=build_args,
        waves=True,
    )

    runner.test(
        hdl_toplevel="cache_controller",
        test_module="cache_controller_test",
        waves=True,
    )


if __name__ == "__main__":
    cache_controller_test()
