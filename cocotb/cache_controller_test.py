"""
cache_controller_test.py
Cocotb testbench for the RTL cache_controller module.

Golden model: CacheController (cache_v3.py / emulation package)

Test strategy
─────────────
Both the DUT and the golden model share a single SimpleMemory "directory"
that holds the authoritative backing store.  Every coherence request that
the DUT issues on its cache→directory port is intercepted by a coroutine
running in the background; the same request is replayed into the golden
model's directory handler so both see identical traffic.

Tests
  1. test_single_read_miss          – cold read, checks BUS_RD → SHARED
  2. test_single_write_miss         – cold write, checks BUS_RDX → MODIFIED
  3. test_read_after_write_hit      – write then read same addr, no dir traffic
  4. test_write_after_read_upgrade  – read then write, checks BUS_UPGR
  5. test_tag_mismatch_evict        – force eviction of a dirty line
  6. test_snoop_bus_rd_modified     – snoop BUS_RD on MODIFIED line → flush + SHARED
  7. test_snoop_bus_rdx_shared      – snoop BUS_RDX on SHARED line → INVALID
  8. test_snoop_bus_upgr_shared     – snoop BUS_UPGR on SHARED line → INVALID
  9. test_random_traffic            – 200 random read/write ops vs golden
"""

import os
import random
import logging
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer, ClockCycles
from cocotb_tools.runner import get_runner

# ── Golden model ────────────────────────────────────────────────────────────
from emulation.cache_v3 import CacheController, CacheLine
from emulation.axi_request_types import axi_request, axi_and_coherence_request
from emulation.msi_v2 import MSIState, CoherenceCmd
from emulation.config import OFFSET_WIDTH, INDEX_WIDTH, TAG_WIDTH, NUM_CACHE_LINES

# ── Simulator selection ──────────────────────────────────────────────────────
sim = os.getenv("SIM", "icarus")

log = logging.getLogger("cache_tb")

# ============================================================================
# Backing memory (acts as the "directory" for both DUT and golden model)
# ============================================================================

MEM_WORDS = 1 << (INDEX_WIDTH + TAG_WIDTH)  # enough for all addressable lines

class SimpleMemory:
    """Word-addressed 32-bit backing store."""
    def __init__(self):
        self._mem: dict[int, int] = {}

    def word_addr(self, byte_addr: int) -> int:
        return byte_addr >> OFFSET_WIDTH  # OFFSET_WIDTH=0, so same as byte_addr

    def read(self, byte_addr: int) -> int:
        return self._mem.get(self.word_addr(byte_addr), 0)

    def write(self, byte_addr: int, data: int, wstrb: int = 0xF) -> None:
        wa = self.word_addr(byte_addr)
        old = self._mem.get(wa, 0)
        result = 0
        for b in range(4):
            if (wstrb >> b) & 1:
                result |= (data >> (b * 8) & 0xFF) << (b * 8)
            else:
                result |= (old >> (b * 8) & 0xFF) << (b * 8)
        self._mem[wa] = result


# ============================================================================
# Golden-model directory handler
# The golden CacheController calls this instead of a real directory.
# We just do the read/write on SimpleMemory and return an axi_request.
# ============================================================================

def make_golden_dir_handler(mem: SimpleMemory):
    async def handler(req: axi_and_coherence_request) -> axi_request:
        if not req.mem_valid:
            return axi_request(mem_valid=False, mem_ready=False, mem_instr=False,
                               mem_addr=0, mem_wdata=0, mem_wstrb=0, mem_rdata=0)

        cmd = req.coherence_cmd
        addr = req.mem_addr
        rdata = 0

        if cmd in (CoherenceCmd.BUS_RD, CoherenceCmd.BUS_RDX):
            rdata = mem.read(addr)
        elif cmd == CoherenceCmd.BUS_UPGR:
            rdata = mem.read(addr)
        elif cmd == CoherenceCmd.EVICT_DIRTY:
            mem.write(addr, req.mem_wdata_or_msi_payload)
        elif cmd == CoherenceCmd.EVICT_CLEAN:
            pass  # clean eviction – nothing to write back

        return axi_request(
            mem_valid=True,
            mem_ready=True,
            mem_instr=False,
            mem_addr=addr,
            mem_wdata=0,
            mem_wstrb=0,
            mem_rdata=rdata,
        )
    return handler


# ============================================================================
# DUT AXI helpers
# ============================================================================

TIMEOUT_CYCLES = 200  # maximum cycles to wait for a handshake


async def start_clock(dut, freq_mhz: int = 50):
    clock = Clock(dut.clk_i, 1 / freq_mhz * 1000, unit="ns")
    cocotb.start_soon(clock.start())


async def reset_dut(dut, duration_ns: int = 100):
    """Assert active-low reset, hold all inputs low."""
    dut.rst_ni.value         = 0
    dut.mem_valid.value      = 0
    dut.mem_instr.value      = 0
    dut.mem_addr.value       = 0
    dut.mem_wdata.value      = 0
    dut.mem_wstrb.value      = 0
    dut.cache_ready_i.value  = 0
    dut.bus_valid_i.value    = 0
    dut.bus_data_i.value     = 0
    dut.bus_dircmd_i.value   = 0
    dut.snoop_valid_i.value  = 0
    dut.snoop_addr_i.value   = 0
    dut.snoop_dircmd_i.value = 0
    await Timer(duration_ns, unit="ns")
    await FallingEdge(dut.clk_i)
    dut.rst_ni.value = 1
    await FallingEdge(dut.clk_i)


# ============================================================================
# DUT directory responder (background coroutine)
#
# Watches the cache→directory port. When the DUT issues a valid coherence
# request (cache_valid_o=1), services it against SimpleMemory and drives
# the bus_* response back to the DUT.
# ============================================================================

async def dut_dir_responder(dut, mem: SimpleMemory):
    """
    Background task – runs for the lifetime of each test.
    Accepts every cache→dir request and responds in the same style a real
    directory would: accept on cache_ready_i, then reply on bus_valid_i.
    """
    CMD_BUS_RD      = 1
    CMD_BUS_RDX     = 2
    CMD_BUS_UPGR    = 3
    CMD_EVICT_CLEAN = 4
    CMD_EVICT_DIRTY = 5

    while True:
        await RisingEdge(dut.clk_i)

        if dut.cache_valid_o.value != 1:
            continue

        cmd  = int(dut.cache_cmd_o.value) & 0x1FF
        addr = int(dut.cache_addr_o.value)
        data = int(dut.cache_data_o.value)

        # ── Accept the request (cache_ready_i = 1 for one cycle) ──
        await FallingEdge(dut.clk_i)
        dut.cache_ready_i.value = 1
        await FallingEdge(dut.clk_i)
        dut.cache_ready_i.value = 0

        # ── Perform the memory operation ───────────────────────────
        rdata = 0
        if cmd == CMD_BUS_RD:
            rdata = mem.read(addr)
        elif cmd == CMD_BUS_RDX:
            rdata = mem.read(addr)
        elif cmd == CMD_BUS_UPGR:
            rdata = mem.read(addr)
        elif cmd == CMD_EVICT_DIRTY:
            mem.write(addr, data)
        # EVICT_CLEAN: nothing to write

        # ── Send response (bus_valid_i = 1 for one cycle) ─────────
        await FallingEdge(dut.clk_i)
        dut.bus_valid_i.value = 1
        dut.bus_data_i.value  = rdata
        await FallingEdge(dut.clk_i)
        dut.bus_valid_i.value = 0
        dut.bus_data_i.value  = 0
        dut.bus_ready_o       # just observe, no drive needed


async def cpu_write(dut, addr: int, data: int, wstrb: int):
    """Drive a CPU write to the DUT and wait for mem_ready."""
    dut.mem_addr.value  = addr
    dut.mem_wdata.value = data
    dut.mem_wstrb.value = wstrb
    dut.mem_valid.value = 1
    dut.mem_instr.value = 0

    for _ in range(TIMEOUT_CYCLES):
        await FallingEdge(dut.clk_i)
        if dut.mem_ready.value == 1:
            break
    else:
        raise TimeoutError(f"cpu_write timeout at addr={addr:#010x}")

    dut.mem_valid.value = 0
    dut.mem_wstrb.value = 0
    await RisingEdge(dut.clk_i)


async def cpu_read(dut, addr: int) -> int:
    """Drive a CPU read to the DUT and return rdata."""
    dut.mem_addr.value  = addr
    dut.mem_wdata.value = 0
    dut.mem_wstrb.value = 0
    dut.mem_valid.value = 1
    dut.mem_instr.value = 0

    rdata = 0
    for _ in range(TIMEOUT_CYCLES):
        await FallingEdge(dut.clk_i)
        if dut.mem_ready.value == 1:
            rdata = int(dut.mem_rdata.value)
            break
    else:
        raise TimeoutError(f"cpu_read timeout at addr={addr:#010x}")

    dut.mem_valid.value = 0
    await RisingEdge(dut.clk_i)
    return rdata


async def send_snoop(dut, addr: int, snoop_cmd: int):
    """
    Inject a snoop from the directory into the DUT.
    snoop_cmd: 0=BUS_RD, 1=BUS_RDX, 2=BUS_UPGR
    Waits for snoop_ready_o.
    """
    dut.snoop_valid_i.value  = 1
    dut.snoop_addr_i.value   = addr
    dut.snoop_dircmd_i.value = snoop_cmd

    for _ in range(TIMEOUT_CYCLES):
        await FallingEdge(dut.clk_i)
        if dut.snoop_ready_o.value == 1:
            break
    else:
        raise TimeoutError(f"snoop timeout at addr={addr:#010x} cmd={snoop_cmd}")

    dut.snoop_valid_i.value = 0
    await RisingEdge(dut.clk_i)


# ============================================================================
# Shared test fixture – call at the top of every test
# ============================================================================

async def setup(dut):
    """
    Returns (mem, golden) after starting the clock, resetting the DUT,
    and launching the background directory-responder coroutine.
    """
    mem    = SimpleMemory()
    golden = CacheController(core_id=0,
                             directory_axi_handler=make_golden_dir_handler(mem))
    await start_clock(dut)
    await reset_dut(dut)
    cocotb.start_soon(dut_dir_responder(dut, mem))
    return mem, golden


# ============================================================================
# Helper: drive the golden model with the same CPU op
# ============================================================================

async def golden_write(golden: CacheController, addr: int, data: int, wstrb: int):
    req = axi_request(mem_valid=True, mem_ready=False, mem_instr=False,
                      mem_addr=addr, mem_wdata=data, mem_wstrb=wstrb, mem_rdata=0)
    await golden._handle_cpu_write(req)


async def golden_read(golden: CacheController, addr: int) -> int:
    req = axi_request(mem_valid=True, mem_ready=False, mem_instr=False,
                      mem_addr=addr, mem_wdata=0, mem_wstrb=0, mem_rdata=0)
    resp = await golden._handle_cpu_read(req)
    return resp.mem_rdata


def golden_snoop(golden: CacheController, addr: int, snoop_cmd: int):
    """
    snoop_cmd: 0=BUS_RD, 1=BUS_RDX, 2=BUS_UPGR
    Maps to CoherenceCmd.SNOOP_BUS_RD/RDX/UPGR for the golden model.
    """
    cmd_map = {
        0: CoherenceCmd.SNOOP_BUS_RD,
        1: CoherenceCmd.SNOOP_BUS_RDX,
        2: CoherenceCmd.SNOOP_BUS_UPGR,
    }
    req = axi_and_coherence_request(
        mem_valid=True, mem_ready=False, mem_instr=False,
        mem_addr=addr, mem_wdata_or_msi_payload=0, mem_wstrb=0xF,
        mem_rdata=0, coherence_cmd=cmd_map[snoop_cmd], core_id=1,
    )
    golden._handle_snoop(req)


# ============================================================================
# Tests
# ============================================================================

@cocotb.test()
async def test_single_read_miss(dut):
    """Cold read: cache is INVALID → should issue BUS_RD → land in SHARED."""
    log.info("=== test_single_read_miss ===")
    mem, golden = await setup(dut)

    addr = 0x00000010
    mem.write(addr, 0xDEADBEEF)  # pre-load backing memory

    dut_rdata    = await cpu_read(dut, addr)
    golden_rdata = await golden_read(golden, addr)

    assert dut_rdata == golden_rdata, (
        f"Read mismatch at {addr:#010x}: DUT={dut_rdata:#010x} GOLDEN={golden_rdata:#010x}"
    )
    log.info(f"PASS: rdata={dut_rdata:#010x}")


@cocotb.test()
async def test_single_write_miss(dut):
    """Cold write: cache is INVALID → should issue BUS_RDX → land in MODIFIED."""
    log.info("=== test_single_write_miss ===")
    mem, golden = await setup(dut)

    addr = 0x00000020
    data = 0xCAFEBABE

    await cpu_write(dut, addr, data, 0xF)
    await golden_write(golden, addr, data, 0xF)

    # Read back and compare
    dut_rdata    = await cpu_read(dut, addr)
    golden_rdata = await golden_read(golden, addr)

    assert dut_rdata == golden_rdata, (
        f"Write-then-read mismatch at {addr:#010x}: DUT={dut_rdata:#010x} GOLDEN={golden_rdata:#010x}"
    )
    log.info(f"PASS: rdata={dut_rdata:#010x}")


@cocotb.test()
async def test_read_after_write_hit(dut):
    """
    Write then read the same address.
    Second access should be a cache hit (no directory traffic).
    """
    log.info("=== test_read_after_write_hit ===")
    mem, golden = await setup(dut)

    addr = 0x00000030
    data = 0x12345678

    await cpu_write(dut, addr, data, 0xF)
    await golden_write(golden, addr, data, 0xF)

    dut_rdata    = await cpu_read(dut, addr)
    golden_rdata = await golden_read(golden, addr)

    assert dut_rdata == golden_rdata, (
        f"Hit-read mismatch at {addr:#010x}: DUT={dut_rdata:#010x} GOLDEN={golden_rdata:#010x}"
    )
    assert dut_rdata == data, (
        f"Expected {data:#010x}, got {dut_rdata:#010x}"
    )
    log.info(f"PASS: rdata={dut_rdata:#010x}")


@cocotb.test()
async def test_write_after_read_upgrade(dut):
    """
    Read first (→ SHARED), then write (→ BUS_UPGR → MODIFIED).
    Verify the written value is readable.
    """
    log.info("=== test_write_after_read_upgrade ===")
    mem, golden = await setup(dut)

    addr      = 0x00000040
    init_data = 0xAABBCCDD
    new_data  = 0x11223344

    mem.write(addr, init_data)

    # Read to bring into SHARED
    await cpu_read(dut, addr)
    await golden_read(golden, addr)

    # Write to upgrade to MODIFIED
    await cpu_write(dut, addr, new_data, 0xF)
    await golden_write(golden, addr, new_data, 0xF)

    dut_rdata    = await cpu_read(dut, addr)
    golden_rdata = await golden_read(golden, addr)

    assert dut_rdata == golden_rdata, (
        f"Upgrade mismatch at {addr:#010x}: DUT={dut_rdata:#010x} GOLDEN={golden_rdata:#010x}"
    )
    assert dut_rdata == new_data, (
        f"Expected {new_data:#010x}, got {dut_rdata:#010x}"
    )
    log.info(f"PASS: rdata={dut_rdata:#010x}")


@cocotb.test()
async def test_tag_mismatch_evict(dut):
    """
    Write to address A (→ MODIFIED in its cache slot).
    Write to address B that maps to the SAME slot with a different tag.
    The controller must evict A (EVICT_DIRTY) before fetching B.
    Both reads back must match the golden model.
    """
    log.info("=== test_tag_mismatch_evict ===")
    mem, golden = await setup(dut)

    # Two addresses that land on the same index but different tags.
    # Index is addr[INDEX_W-1:0] = addr[6:0].  Tag is addr[8:7].
    # addr_a tag=0b00, index=0x01  → 0x01
    # addr_b tag=0b01, index=0x01  → 0x81
    addr_a = 0x00000001
    addr_b = 0x00000081  # same index, different tag

    data_a = 0xAAAAAAAA
    data_b = 0xBBBBBBBB

    # Write A → MODIFIED
    await cpu_write(dut, addr_a, data_a, 0xF)
    await golden_write(golden, addr_a, data_a, 0xF)

    # Write B → should evict A first
    await cpu_write(dut, addr_b, data_b, 0xF)
    await golden_write(golden, addr_b, data_b, 0xF)

    # Read B back
    dut_b    = await cpu_read(dut, addr_b)
    golden_b = await golden_read(golden, addr_b)

    assert dut_b == golden_b, (
        f"Tag-mismatch B mismatch: DUT={dut_b:#010x} GOLDEN={golden_b:#010x}"
    )
    # addr_a was evicted to memory; reading it back fetches from memory
    dut_a    = await cpu_read(dut, addr_a)
    golden_a = await golden_read(golden, addr_a)

    assert dut_a == golden_a, (
        f"Tag-mismatch A mismatch: DUT={dut_a:#010x} GOLDEN={golden_a:#010x}"
    )
    log.info(f"PASS: A={dut_a:#010x} B={dut_b:#010x}")


@cocotb.test()
async def test_snoop_bus_rd_modified(dut):
    """
    Write a line (→ MODIFIED).
    Inject SNOOP_BUS_RD → DUT must flush dirty data and downgrade to SHARED.
    Read the line back: should still return the correct data.
    """
    log.info("=== test_snoop_bus_rd_modified ===")
    mem, golden = await setup(dut)

    addr = 0x00000050
    data = 0xFACEFACE

    await cpu_write(dut, addr, data, 0xF)
    await golden_write(golden, addr, data, 0xF)

    # Snoop BUS_RD (cmd=0)
    await send_snoop(dut, addr, 0)
    golden_snoop(golden, addr, 0)

    # Read back – line is now SHARED, data in memory was updated by flush
    dut_rdata    = await cpu_read(dut, addr)
    golden_rdata = await golden_read(golden, addr)

    assert dut_rdata == golden_rdata, (
        f"Snoop-BUS_RD mismatch: DUT={dut_rdata:#010x} GOLDEN={golden_rdata:#010x}"
    )
    log.info(f"PASS: rdata={dut_rdata:#010x}")


@cocotb.test()
async def test_snoop_bus_rdx_shared(dut):
    """
    Read a line (→ SHARED).
    Inject SNOOP_BUS_RDX → DUT must invalidate.
    Next read should be a miss (fetches from memory).
    """
    log.info("=== test_snoop_bus_rdx_shared ===")
    mem, golden = await setup(dut)

    addr = 0x00000060
    data = 0x55AA55AA
    mem.write(addr, data)

    await cpu_read(dut, addr)
    await golden_read(golden, addr)

    # Snoop BUS_RDX (cmd=1)
    await send_snoop(dut, addr, 1)
    golden_snoop(golden, addr, 1)

    # Read back – should re-fetch from memory (miss)
    dut_rdata    = await cpu_read(dut, addr)
    golden_rdata = await golden_read(golden, addr)

    assert dut_rdata == golden_rdata, (
        f"Snoop-BUS_RDX mismatch: DUT={dut_rdata:#010x} GOLDEN={golden_rdata:#010x}"
    )
    assert dut_rdata == data, (
        f"Expected {data:#010x}, got {dut_rdata:#010x}"
    )
    log.info(f"PASS: rdata={dut_rdata:#010x}")


@cocotb.test()
async def test_snoop_bus_upgr_shared(dut):
    """
    Read a line (→ SHARED).
    Inject SNOOP_BUS_UPGR → DUT must invalidate (no flush).
    Next read is a miss.
    """
    log.info("=== test_snoop_bus_upgr_shared ===")
    mem, golden = await setup(dut)

    addr = 0x00000070
    data = 0x13572468
    mem.write(addr, data)

    await cpu_read(dut, addr)
    await golden_read(golden, addr)

    # Snoop BUS_UPGR (cmd=2)
    await send_snoop(dut, addr, 2)
    golden_snoop(golden, addr, 2)

    dut_rdata    = await cpu_read(dut, addr)
    golden_rdata = await golden_read(golden, addr)

    assert dut_rdata == golden_rdata, (
        f"Snoop-BUS_UPGR mismatch: DUT={dut_rdata:#010x} GOLDEN={golden_rdata:#010x}"
    )
    log.info(f"PASS: rdata={dut_rdata:#010x}")


@cocotb.test()
async def test_wstrb_partial_write(dut):
    """
    Write a full word then do a partial-byte write using wstrb.
    Verify only the strobed bytes are updated.
    """
    log.info("=== test_wstrb_partial_write ===")
    mem, golden = await setup(dut)

    addr      = 0x00000008
    init_data = 0xDEADBEEF
    new_data  = 0xFF112233  # only low byte (wstrb=0x1) should land

    mem.write(addr, init_data)

    # Full write to warm cache
    await cpu_write(dut, addr, init_data, 0xF)
    await golden_write(golden, addr, init_data, 0xF)

    # Partial write: low byte only
    await cpu_write(dut, addr, new_data, 0x1)
    await golden_write(golden, addr, new_data, 0x1)

    dut_rdata    = await cpu_read(dut, addr)
    golden_rdata = await golden_read(golden, addr)

    assert dut_rdata == golden_rdata, (
        f"Partial-write mismatch: DUT={dut_rdata:#010x} GOLDEN={golden_rdata:#010x}"
    )
    expected = (init_data & 0xFFFFFF00) | (new_data & 0x000000FF)
    assert dut_rdata == expected, (
        f"Expected {expected:#010x}, got {dut_rdata:#010x}"
    )
    log.info(f"PASS: rdata={dut_rdata:#010x}")


@cocotb.test()
async def test_random_traffic(dut):
    """
    200 random read / write ops against the golden model.
    Every result is compared immediately after each transaction.
    """
    log.info("=== test_random_traffic ===")
    mem, golden = await setup(dut)

    NUM_TRANSACTIONS = 200
    rng = random.Random(42)  # fixed seed for reproducibility

    # Use a small address range to exercise hits, misses, and evictions
    ADDR_RANGE = 1 << (INDEX_WIDTH + 1)  # spans two tags per index

    for i in range(NUM_TRANSACTIONS):
        addr  = rng.randint(0, ADDR_RANGE - 1) & ~0x3  # word-align
        data  = rng.randint(0, 0xFFFFFFFF)
        wstrb = rng.choice([0x0, 0x1, 0x3, 0xF])  # 0x0 = read

        if wstrb == 0:
            dut_rdata    = await cpu_read(dut, addr)
            golden_rdata = await golden_read(golden, addr)
            assert dut_rdata == golden_rdata, (
                f"[{i}] Read mismatch at {addr:#010x}: "
                f"DUT={dut_rdata:#010x} GOLDEN={golden_rdata:#010x}"
            )
        else:
            await cpu_write(dut, addr, data, wstrb)
            await golden_write(golden, addr, data, wstrb)

            dut_rdata    = await cpu_read(dut, addr)
            golden_rdata = await golden_read(golden, addr)
            assert dut_rdata == golden_rdata, (
                f"[{i}] Write-readback mismatch at {addr:#010x}: "
                f"DUT={dut_rdata:#010x} GOLDEN={golden_rdata:#010x}"
            )

    log.info(f"PASS: {NUM_TRANSACTIONS} transactions verified")


# ============================================================================
# Runner
# ============================================================================

def cache_controller_test():
    proj_path = Path(__file__).resolve().parent
    pdk_root  = Path("../gf180mcu")

    sources = [
        proj_path / "../src/msi_protocol/apply_wstrb.sv",
        proj_path / "../src/msi_protocol/on_processor_event_state_machine.sv",
        proj_path / "../src/msi_protocol/on_snoop_event_state_machine.sv",
        proj_path / "../src/msi_protocol/cache_controller.sv",

        proj_path / "../src/mem_ctrl/cache_dir_memory/mem128x4.sv",
        proj_path / "../src/mem_ctrl/cache_dir_memory/mem128x32.sv",
        proj_path / "../src/mem_ctrl/cache_dir_memory/cache_mem.sv",

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
