"""
cache_controller_test.py
Cocotb testbench for the RTL cache_controller module.
Golden model: MSI state machine logic (inline below).

Assumed command encodings – adjust constants to match your RTL:

  cache_cmd_o  (9-bit, cache → directory)
    CMD_GETS  = 0x01  – read request (wants Shared)
    CMD_GETM  = 0x02  – write / upgrade request (wants Modified)
    CMD_PUTM  = 0x04  – write-back dirty line

  bus_dircmd_i (3-bit, directory → cache inbound response)
    DIR_NOP   = 0  – no operation / idle
    DIR_DATA  = 1  – data payload (fills cache line for GetS / GetM)
    DIR_INV   = 2  – forced invalidate  (downgrade M→I or S→I)
    DIR_ACK   = 3  – upgrade ack (S→M, no data transfer)

  snoop_dircmd_i (3-bit, directory-initiated snoop)
    SNOOP_NOP  = 0
    SNOOP_INV  = 1  – invalidate (peer wrote, drop our S copy)
    SNOOP_GETS = 2  – intervention: supply data to peer reader
"""

import os
import random
import logging
from pathlib import Path

import cocotb
from cocotb.clock   import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer, ClockCycles, with_timeout
from cocotb_tools.runner import get_runner

# ─── Sim / logging setup ────────────────────────────────────────────────────
sim = os.getenv("SIM", "icarus")
log = logging.getLogger("cache_tb")
logging.basicConfig(level=logging.INFO)

TIMEOUT_CYCLES = 100   # cycles to wait for any single handshake

# ─── Protocol constants (keep in sync with RTL parameters) ──────────────────
CMD_GETS  = 0x01
CMD_GETM  = 0x02
CMD_PUTM  = 0x04

DIR_NOP   = 0
DIR_DATA  = 1
DIR_INV   = 2
DIR_ACK   = 3

SNOOP_NOP  = 0
SNOOP_INV  = 1
SNOOP_GETS = 2


# ════════════════════════════════════════════════════════════════════════════
#  Low-level helpers
# ════════════════════════════════════════════════════════════════════════════

async def start_clock(dut, freq_mhz: int = 50):
    clock = Clock(dut.clk_i, 1_000 / freq_mhz, unit="ns")
    cocotb.start_soon(clock.start())


async def reset_dut(dut, duration_ns: int = 100):
    """Assert active-low reset and hold all inputs idle."""
    dut.rst_ni.value        = 0
    dut.mem_valid_i.value   = 0
    dut.mem_instr_i.value   = 0
    dut.mem_addr_i.value    = 0
    dut.mem_wdata_i.value   = 0
    dut.mem_wstrb_i.value   = 0
    dut.cache_ready_i.value = 0
    dut.bus_valid_i.value   = 0
    dut.bus_data_i.value    = 0
    dut.bus_dircmd_i.value  = 0
    dut.snoop_valid_i.value = 0
    dut.snoop_addr_i.value  = 0
    dut.snoop_dircmd_i.value = 0
    await Timer(duration_ns, unit="ns")
    await FallingEdge(dut.clk_i)
    dut.rst_ni.value = 1
    await FallingEdge(dut.clk_i)

    reset_time = 128 * 4 * 2

    for i in range(reset_time):
        await FallingEdge(dut.clk_i)
    
    log.info("Reset released")


async def clkedge(dut):
    await RisingEdge(dut.clk_i)


# ════════════════════════════════════════════════════════════════════════════
#  Bus-functional models
# ════════════════════════════════════════════════════════════════════════════

async def proc_read(dut, addr: int) -> int:
    """
    Drive a processor read on the mem_* interface.
    Returns the data word latched when mem_ready_o is asserted.
    Does NOT wait for the coherence transaction to complete – the caller
    should run drive_dir_response() concurrently if a miss is expected.
    """
    dut.mem_valid_i.value = 1
    dut.mem_instr_i.value = 0
    dut.mem_addr_i.value  = addr
    dut.mem_wdata_i.value = 0
    dut.mem_wstrb_i.value = 0

    print("starting test")

    for _ in range(TIMEOUT_CYCLES):
        await RisingEdge(dut.clk_i)
        if dut.mem_ready_o.value:
            data = int(dut.mem_rdata_o.value)
            dut.mem_valid_i.value = 0
            log.info("proc_read  addr=0x%08x → data=0x%08x", addr, data)
            return data

    dut.mem_valid_i.value = 0
    raise cocotb.result.TestFailure(
        f"proc_read timed out waiting for mem_ready_o (addr=0x{addr:08x})"
    )


async def proc_write(dut, addr: int, data: int, wstrb: int = 0xF):
    """Drive a processor write. Waits for mem_ready_o."""
    dut.mem_valid_i.value = 1
    dut.mem_instr_i.value = 0
    dut.mem_addr_i.value  = addr
    dut.mem_wdata_i.value = data
    dut.mem_wstrb_i.value = wstrb

    for _ in range(TIMEOUT_CYCLES):
        await RisingEdge(dut.clk_i)
        if dut.mem_ready_o.value:
            dut.mem_valid_i.value = 0
            log.info("proc_write addr=0x%08x  data=0x%08x  wstrb=0x%x",
                     addr, data, wstrb)
            return

    dut.mem_valid_i.value = 0
    raise cocotb.result.TestFailure(
        f"proc_write timed out (addr=0x{addr:08x})"
    )


async def wait_cache_request(dut) -> tuple[int, int]:
    """
    Wait for the cache to raise cache_valid_o and latch (addr, cmd).
    Holds cache_ready_i=0 until the request is seen, then pulses it.
    Returns (addr, cmd).
    """
    dut.cache_ready_i.value = 0
    for _ in range(TIMEOUT_CYCLES):
        await RisingEdge(dut.clk_i)
        if dut.cache_valid_o.value:
            addr = int(dut.cache_addr_o.value)
            cmd  = int(dut.cache_cmd_o.value)
            log.info("cache→dir  cmd=0x%03x  addr=0x%08x", cmd, addr)
            # Accept the request
            dut.cache_ready_i.value = 1
            await RisingEdge(dut.clk_i)
            dut.cache_ready_i.value = 0
            return addr, cmd

    raise cocotb.result.TestFailure("Timeout waiting for cache_valid_o")


async def drive_dir_response(dut, dircmd: int, data: int = 0):
    """
    Send one directory→cache response on the bus_* interface.
    Waits for bus_ready_o before deasserting.
    """
    dut.bus_valid_i.value  = 1
    dut.bus_dircmd_i.value = dircmd
    dut.bus_data_i.value   = data

    for _ in range(TIMEOUT_CYCLES):
        await RisingEdge(dut.clk_i)
        if dut.bus_ready_o.value:
            dut.bus_valid_i.value  = 0
            dut.bus_dircmd_i.value = DIR_NOP
            dut.bus_data_i.value   = 0
            log.info("dir→cache  dircmd=%d  data=0x%08x", dircmd, data)
            return

    dut.bus_valid_i.value = 0
    raise cocotb.result.TestFailure("Timeout waiting for bus_ready_o")


async def drive_snoop(dut, addr: int, dircmd: int):
    """Send a directory-initiated snoop and wait for snoop_ready_o."""
    dut.snoop_valid_i.value  = 1
    dut.snoop_addr_i.value   = addr
    dut.snoop_dircmd_i.value = dircmd

    for _ in range(TIMEOUT_CYCLES):
        await RisingEdge(dut.clk_i)
        if dut.snoop_ready_o.value:
            dut.snoop_valid_i.value  = 0
            dut.snoop_dircmd_i.value = SNOOP_NOP
            log.info("snoop ack  dircmd=%d  addr=0x%08x", dircmd, addr)
            return

    dut.snoop_valid_i.value = 0
    raise cocotb.result.TestFailure(
        f"Timeout waiting for snoop_ready_o (addr=0x{addr:08x})"
    )


# ════════════════════════════════════════════════════════════════════════════
#  Test cases
# ════════════════════════════════════════════════════════════════════════════

@cocotb.test()
async def test_read_miss_cold(dut):
    """
    Read to an uncached address:
      Processor issues read → cache sends GetS to directory →
      directory replies with DATA → processor receives data.
    Expected MSI state transition: I → S
    """
    await start_clock(dut)
    await reset_dut(dut)

    ADDR      = 0x0000_0000
    FILL_DATA = 0xDEAD_BEEF

    # # Kick off processor read; the cache will miss and stall mem_ready_o
    read_task = cocotb.start_soon(proc_read(dut, ADDR))

    # Expect a GetS on the outbound coherence port
    # req_addr, req_cmd = await wait_cache_request(dut)
    # assert req_addr == ADDR,    f"Expected addr 0x{ADDR:08x}, got 0x{req_addr:08x}"
    # assert req_cmd  == CMD_GETS, f"Expected GetS (0x{CMD_GETS:x}), got 0x{req_cmd:x}"

    # # Directory supplies the cache line
    # await drive_dir_response(dut, DIR_DATA, FILL_DATA)

    # # Processor read should now complete with fill data
    # rdata = await read_task
    # assert rdata == FILL_DATA, f"Expected 0x{FILL_DATA:08x}, got 0x{rdata:08x}"
    # log.info("PASS test_read_miss_cold")


# @cocotb.test()
# async def test_read_hit_after_fill(dut):
#     """
#     Two reads to the same address.  The second read must be served from
#     the cache (no second GetS should appear on cache_valid_o).
#     Expected state: I → S (miss) → S (hit, no coherence traffic).
#     """
#     await start_clock(dut)
#     await reset_dut(dut)

#     ADDR      = 0x0000_2000
#     FILL_DATA = 0xCAFE_BABE

#     # ── First read (miss) ──────────────────────────────────────────
#     read1 = cocotb.start_soon(proc_read(dut, ADDR))
#     _, cmd = await wait_cache_request(dut)
#     assert cmd == CMD_GETS
#     await drive_dir_response(dut, DIR_DATA, FILL_DATA)
#     rdata1 = await read1
#     assert rdata1 == FILL_DATA

#     await ClockCycles(dut.clk_i, 4)

#     # ── Second read (should hit – no outbound request) ─────────────
#     dut.cache_ready_i.value = 1          # keep ready asserted so we notice any spurious req
#     read2 = cocotb.start_soon(proc_read(dut, ADDR))

#     spurious_req = False
#     for _ in range(20):
#         await RisingEdge(dut.clk_i)
#         if dut.cache_valid_o.value:
#             spurious_req = True
#             break

#     rdata2 = await read2
#     dut.cache_ready_i.value = 0

#     assert not spurious_req, "Unexpected coherence request on cache hit"
#     assert rdata2 == FILL_DATA, f"Cache hit returned wrong data: 0x{rdata2:08x}"
#     log.info("PASS test_read_hit_after_fill")


# @cocotb.test()
# async def test_write_miss(dut):
#     """
#     Write to an uncached (Invalid) address:
#       Processor write → cache issues GetM → directory responds with DATA/ACK →
#       write completes.
#     Expected MSI state: I → M
#     """
#     await start_clock(dut)
#     await reset_dut(dut)

#     ADDR  = 0x0000_3000
#     WDATA = 0x1234_5678
#     WSTRB = 0xF

#     write_task = cocotb.start_soon(proc_write(dut, ADDR, WDATA, WSTRB))

#     req_addr, req_cmd = await wait_cache_request(dut)
#     assert req_addr == ADDR,    f"Wrong address: 0x{req_addr:08x}"
#     assert req_cmd  == CMD_GETM, f"Expected GetM (0x{CMD_GETM:x}), got 0x{req_cmd:x}"

#     # Directory grants exclusive ownership (data response for a cold miss)
#     await drive_dir_response(dut, DIR_DATA, 0x0)

#     await write_task
#     log.info("PASS test_write_miss")


# @cocotb.test()
# async def test_write_upgrade_shared(dut):
#     """
#     Read (I→S) then write (S→M upgrade):
#       Second coherence request must be GetM, no data in response needed.
#     """
#     await start_clock(dut)
#     await reset_dut(dut)

#     ADDR      = 0x0000_4000
#     FILL_DATA = 0xAAAA_BBBB
#     WDATA     = 0xCCCC_DDDD

#     # ── Fill into Shared ───────────────────────────────────────────
#     read_task = cocotb.start_soon(proc_read(dut, ADDR))
#     await wait_cache_request(dut)
#     await drive_dir_response(dut, DIR_DATA, FILL_DATA)
#     await read_task

#     await ClockCycles(dut.clk_i, 4)

#     # ── Upgrade to Modified ────────────────────────────────────────
#     write_task = cocotb.start_soon(proc_write(dut, ADDR, WDATA))

#     req_addr, req_cmd = await wait_cache_request(dut)
#     assert req_addr == ADDR,    f"Wrong address: 0x{req_addr:08x}"
#     assert req_cmd  == CMD_GETM, f"Expected GetM upgrade, got 0x{req_cmd:x}"

#     # Directory sends upgrade ACK (no fresh data needed)
#     await drive_dir_response(dut, DIR_ACK, 0)

#     await write_task
#     log.info("PASS test_write_upgrade_shared")


# @cocotb.test()
# async def test_snoop_invalidate_shared(dut):
#     """
#     Line in Shared state receives a SNOOP_INV:
#       Cache must assert snoop_ready_o and transition to Invalid.
#     Verify: a subsequent read causes a fresh GetS (not a hit).
#     """
#     await start_clock(dut)
#     await reset_dut(dut)

#     ADDR      = 0x0000_5000
#     FILL_DATA = 0x1111_2222
#     NEW_DATA  = 0x3333_4444

#     # ── Populate the line (I→S) ────────────────────────────────────
#     read_task = cocotb.start_soon(proc_read(dut, ADDR))
#     await wait_cache_request(dut)
#     await drive_dir_response(dut, DIR_DATA, FILL_DATA)
#     await read_task

#     await ClockCycles(dut.clk_i, 4)

#     # ── Snoop invalidate ───────────────────────────────────────────
#     await drive_snoop(dut, ADDR, SNOOP_INV)
#     await ClockCycles(dut.clk_i, 4)

#     # ── Re-read should miss again ──────────────────────────────────
#     read_task2 = cocotb.start_soon(proc_read(dut, ADDR))

#     req_addr, req_cmd = await wait_cache_request(dut)
#     assert req_addr == ADDR,    f"Wrong address on re-read: 0x{req_addr:08x}"
#     assert req_cmd  == CMD_GETS, f"Expected GetS after invalidation, got 0x{req_cmd:x}"

#     await drive_dir_response(dut, DIR_DATA, NEW_DATA)
#     rdata = await read_task2
#     assert rdata == NEW_DATA, f"Expected fresh data 0x{NEW_DATA:08x}, got 0x{rdata:08x}"
#     log.info("PASS test_snoop_invalidate_shared")


# @cocotb.test()
# async def test_snoop_unrelated_address(dut):
#     """
#     A snoop to an address not held by this cache must still be
#     acknowledged without error (cache responds snoop_ready_o=1 quickly).
#     """
#     await start_clock(dut)
#     await reset_dut(dut)

#     await drive_snoop(dut, 0xDEAD_0000, SNOOP_INV)
#     log.info("PASS test_snoop_unrelated_address")


# @cocotb.test()
# async def test_dir_backpressure(dut):
#     """
#     cache_ready_i is de-asserted for several cycles; the cache must hold
#     cache_valid_o and keep the request stable until accepted.
#     """
#     await start_clock(dut)
#     await reset_dut(dut)

#     ADDR      = 0x0000_6000
#     FILL_DATA = 0xFEED_FACE

#     dut.cache_ready_i.value = 0   # block the outbound channel

#     read_task = cocotb.start_soon(proc_read(dut, ADDR))

#     # Wait until cache raises valid
#     for _ in range(TIMEOUT_CYCLES):
#         await RisingEdge(dut.clk_i)
#         if dut.cache_valid_o.value:
#             break
#     else:
#         raise cocotb.result.TestFailure("cache_valid_o never asserted")

#     # Keep it blocked for 10 more cycles; verify the request stays stable
#     first_addr = int(dut.cache_addr_o.value)
#     first_cmd  = int(dut.cache_cmd_o.value)
#     for _ in range(10):
#         await RisingEdge(dut.clk_i)
#         assert dut.cache_valid_o.value,                    "cache_valid_o dropped prematurely"
#         assert int(dut.cache_addr_o.value) == first_addr,  "cache_addr_o changed under backpressure"
#         assert int(dut.cache_cmd_o.value)  == first_cmd,   "cache_cmd_o changed under backpressure"

#     # Release and complete the transaction
#     dut.cache_ready_i.value = 1
#     await RisingEdge(dut.clk_i)
#     dut.cache_ready_i.value = 0

#     await drive_dir_response(dut, DIR_DATA, FILL_DATA)
#     rdata = await read_task
#     assert rdata == FILL_DATA
#     log.info("PASS test_dir_backpressure")


# @cocotb.test()
# async def test_instruction_fetch(dut):
#     """
#     mem_instr_i=1 should be forwarded correctly.  The cache must still
#     issue a GetS and complete the fetch.
#     """
#     await start_clock(dut)
#     await reset_dut(dut)

#     ADDR      = 0x0000_0100   # typical instruction address
#     INSTR_VAL = 0x0013_0293   # addi t0, t1, 1  (just a valid-looking word)

#     read_task = cocotb.start_soon(proc_read(dut, ADDR, instr=True))
#     await wait_cache_request(dut)
#     await drive_dir_response(dut, DIR_DATA, INSTR_VAL)
#     rdata = await read_task
#     assert rdata == INSTR_VAL
#     log.info("PASS test_instruction_fetch")


# @cocotb.test()
# async def test_partial_write_wstrb(dut):
#     """
#     Write with a byte-enable mask (wstrb != 0xF).
#     Cache must still acquire the line (GetM) and complete without errors.
#     """
#     await start_clock(dut)
#     await reset_dut(dut)

#     ADDR  = 0x0000_7000
#     WDATA = 0xABCD_EF01
#     WSTRB = 0b0110   # byte 1 and byte 2 only

#     write_task = cocotb.start_soon(proc_write(dut, ADDR, WDATA, WSTRB))

#     req_addr, req_cmd = await wait_cache_request(dut)
#     assert req_addr == ADDR
#     assert req_cmd  == CMD_GETM

#     # For a partial write the cache may need the existing line first
#     await drive_dir_response(dut, DIR_DATA, 0xFFFF_FFFF)
#     await write_task
#     log.info("PASS test_partial_write_wstrb")


# @cocotb.test()
# async def test_sequential_reads_different_addresses(dut):
#     """
#     N back-to-back reads to different (cold) addresses.
#     Each must generate exactly one GetS and receive data.
#     """
#     await start_clock(dut)
#     await reset_dut(dut)

#     N = 8
#     base_addr = 0x0001_0000

#     for i in range(N):
#         addr      = base_addr + i * 4
#         fill_data = random.randint(0, 0xFFFF_FFFF)

#         read_task = cocotb.start_soon(proc_read(dut, addr))
#         req_addr, req_cmd = await wait_cache_request(dut)
#         assert req_addr == addr
#         assert req_cmd  == CMD_GETS

#         await drive_dir_response(dut, DIR_DATA, fill_data)
#         rdata = await read_task
#         assert rdata == fill_data, (
#             f"iter {i}: expected 0x{fill_data:08x}, got 0x{rdata:08x}"
#         )

#     log.info("PASS test_sequential_reads_different_addresses (%d iters)", N)


# @cocotb.test()
# async def test_write_then_read_same_line(dut):
#     """
#     Write to a line (I→M) and immediately read back from it.
#     The second access should hit the Modified line (no new coherence msg).
#     """
#     await start_clock(dut)
#     await reset_dut(dut)

#     ADDR  = 0x0002_0000
#     WDATA = 0x5A5A_A5A5

#     # ── Write (miss → Modified) ───────────────────────────────────
#     write_task = cocotb.start_soon(proc_write(dut, ADDR, WDATA))
#     req_addr, req_cmd = await wait_cache_request(dut)
#     assert req_addr == ADDR
#     assert req_cmd  == CMD_GETM
#     await drive_dir_response(dut, DIR_DATA, 0)
#     await write_task

#     await ClockCycles(dut.clk_i, 4)

#     # ── Read back (should hit – no outbound GetS) ─────────────────
#     dut.cache_ready_i.value = 1
#     read_task = cocotb.start_soon(proc_read(dut, ADDR))

#     spurious = False
#     for _ in range(20):
#         await RisingEdge(dut.clk_i)
#         if dut.cache_valid_o.value:
#             spurious = True
#             break

#     rdata = await read_task
#     dut.cache_ready_i.value = 0

#     assert not spurious, "Unexpected coherence request on Modified-line read"
#     assert rdata == WDATA, f"Expected 0x{WDATA:08x}, got 0x{rdata:08x}"
#     log.info("PASS test_write_then_read_same_line")


# @cocotb.test()
# async def test_reset_clears_state(dut):
#     """
#     After a mid-transaction reset the DUT must return to idle:
#     all outputs deasserted and ready to accept a fresh request.
#     """
#     await start_clock(dut)
#     await reset_dut(dut)

#     # Start a read but do NOT service it (leave cache_ready_i=0)
#     dut.mem_valid_i.value = 1
#     dut.mem_addr_i.value  = 0x9999_0000
#     dut.mem_wstrb_i.value = 0

#     await ClockCycles(dut.clk_i, 5)

#     # Assert reset in the middle
#     dut.rst_ni.value = 0
#     await ClockCycles(dut.clk_i, 4)
#     dut.rst_ni.value = 1
#     dut.mem_valid_i.value = 0
#     await ClockCycles(dut.clk_i, 4)

#     # After reset, outputs should be deasserted
#     assert not dut.mem_ready_o.value,   "mem_ready_o should be 0 after reset"
#     assert not dut.cache_valid_o.value, "cache_valid_o should be 0 after reset"
#     assert not dut.bus_ready_o.value,   "bus_ready_o should be 0 after reset"

#     # And a fresh transaction should work normally
#     ADDR      = 0x0003_0000
#     FILL_DATA = 0xBEEF_CAFE

#     read_task = cocotb.start_soon(proc_read(dut, ADDR))
#     req_addr, req_cmd = await wait_cache_request(dut)
#     assert req_addr == ADDR
#     assert req_cmd  == CMD_GETS
#     await drive_dir_response(dut, DIR_DATA, FILL_DATA)
#     rdata = await read_task
#     assert rdata == FILL_DATA
#     log.info("PASS test_reset_clears_state")


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
        build_args = ["--timing", "--trace", "--trace-fst", "--trace-structs"]

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
