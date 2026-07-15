import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotb_tools.runner import get_runner

SIM = os.getenv("SIM", "icarus")
HDL_TOPLEVEL = "directory_controller_full"

# Normalized 4-bit binary metadata command codes, matching directory_controller_full.
CACHE_CMD_NONE = 0
CACHE_CMD_BUS_RD = 1
CACHE_CMD_BUS_RDX = 2
CACHE_CMD_BUS_UPGR = 3
CACHE_CMD_EVICT_CLEAN = 5
CACHE_CMD_EVICT_DIRTY = 6

# Snoop acknowledgement commands. Only "not NONE" matters to the controller; the
# flushed data rides on the snoop data channel regardless of the exact code.
SNOOP_ACK_NONE = 0
SNOOP_ACK_BUS_RD = 9
SNOOP_ACK_BUS_RDX = 10
SNOOP_ACK_BUS_UPGR = 11

DIR_CMD_NONE = 0
DIR_CMD_BUS_RD_ACK = 1
DIR_CMD_BUS_RDX_ACK = 2
DIR_CMD_BUS_UPGR_ACK = 3
DIR_CMD_EVICT_DIRTY_ACK = 6          # echoes EvictDirty (writeback persisted)
DIR_CMD_SNOOP_BUS_RD = 9
DIR_CMD_SNOOP_BUS_RDX = 10
DIR_CMD_SNOOP_BUS_UPGR = 11

# The controller tracks one line per metadata index, index = request_addr[10:0].
DIRECTORY_LINE_MIN = 0
DIRECTORY_LINE_MAX = 2047

TIMEOUT_CYCLES = 900
SETTLE_CYCLES = 40


# Metadata is a 3-bit word {dirty, sharers[1:0]} (matches mem2048x3):
#   sharers[0] = cache 0 holds a copy, sharers[1] = cache 1 holds a copy
#   dirty      = the single sharer owns a modified copy (memory is stale)
# Derived states: INVALID = sharers == 0; SHARED = !dirty && sharers != 0;
# MODIFIED = dirty (exactly one sharer bit set, which names the owner).
def meta_code(sharers, dirty):
    return ((dirty & 1) << 2) | (sharers & 0b11)


def meta_sharers(code):
    return code & 0b11


def meta_dirty(code):
    return (code >> 2) & 1


class DirectoryMemModel:
    """Behavioral model of the two external memories the controller drives.

    * Metadata memory (mem2048x3): one 3-bit ``{dirty, sharers}`` code per line.
      It is a synchronous SRAM whose read data appears the cycle after the
      access, so this model presents a registered read output (``md_q``). Reset
      of the metadata array is external, modelled here as all-zero (INVALID).
    * Main memory (mem_ctrl_2048x32): one 32-bit data word per line address,
      accessed through a ``valid``/``ready`` handshake. Reads are combinational
      for the addressed word; writes commit on an accepted beat.
    """

    def __init__(self, mem_ready_pattern=None):
        self.meta = [0] * 2048          # 3-bit codes; external reset -> 0 (INVALID)
        self.mem = {}                   # addr -> 32-bit word
        self.md_q = 0                   # registered metadata read output
        self.mem_ready_pattern = mem_ready_pattern or [1]
        self.cycle = 0
        self.log = []

    def clear_log(self):
        self.log.clear()

    def set_mem(self, addr, data):
        self.mem[addr & 0xFFFFFFFF] = data & 0xFFFFFFFF

    def read_mem(self, addr):
        return self.mem.get(addr & 0xFFFFFFFF, 0) & 0xFFFFFFFF

    async def tick(self, dut):
        mem_ready = self.mem_ready_pattern[self.cycle % len(self.mem_ready_pattern)]

        await Timer(1, unit="ns")

        # Registered metadata read data and the main-memory ready line.
        dut.md_rdata_i.value = self.md_q & 0b111
        dut.mm_ready_i.value = mem_ready

        if int(dut.rst_ni.value) == 0:
            dut.mm_rdata_i.value = 0
            await RisingEdge(dut.clk_i)
            self.md_q = 0
            self.cycle += 1
            return

        # Metadata memory controls.
        md_en_n = int(dut.md_enable_n_o.value)
        md_we = int(dut.md_we_o.value)
        md_addr = int(dut.md_addr_o.value) & 0x7FF
        md_wdata = int(dut.md_wdata_o.value) & 0b111

        # Main memory controls.
        mm_valid = int(dut.mm_valid_o.value)
        mm_addr = int(dut.mm_addr_o.value) & 0xFFFFFFFF
        mm_wstrb = int(dut.mm_wstrb_o.value) & 0xF
        mm_wdata = int(dut.mm_wdata_o.value) & 0xFFFFFFFF

        # Combinational main-memory read data for the addressed word.
        dut.mm_rdata_i.value = self.read_mem(mm_addr)

        await RisingEdge(dut.clk_i)

        # Commit the metadata access (SRAM latches on the clock edge).
        if md_en_n == 0:
            if md_we:
                self.meta[md_addr] = md_wdata
                self.log.append({"kind": "meta_write", "addr": md_addr, "code": md_wdata})
            else:
                self.md_q = self.meta[md_addr]
                self.log.append({"kind": "meta_read", "addr": md_addr, "code": self.md_q})

        # Commit the main-memory access on an accepted beat.
        if mm_valid and mem_ready:
            if mm_wstrb:
                self.set_mem(mm_addr, mm_wdata)
                self.log.append({"kind": "mem_write", "addr": mm_addr, "data": mm_wdata})
            else:
                self.log.append({"kind": "mem_read", "addr": mm_addr, "data": self.read_mem(mm_addr)})

        self.cycle += 1


async def wait_cycles(dut, mem, cycles):
    for _ in range(cycles):
        await mem.tick(dut)


def set_input_defaults(dut):
    dut.c0_bus_valid_i.value = 0
    dut.c0_bus_addr_i.value = 0
    dut.c0_bus_wdata_i.value = 0
    dut.c0_bus_cache_cmd_i.value = CACHE_CMD_NONE
    dut.c0_snoop_valid_i.value = 0
    dut.c0_snoop_data_i.value = 0
    dut.c0_snoop_cache_cmd_i.value = SNOOP_ACK_NONE
    dut.c0_dir_ready_i.value = 1

    dut.c1_bus_valid_i.value = 0
    dut.c1_bus_addr_i.value = 0
    dut.c1_bus_wdata_i.value = 0
    dut.c1_bus_cache_cmd_i.value = CACHE_CMD_NONE
    dut.c1_snoop_valid_i.value = 0
    dut.c1_snoop_data_i.value = 0
    dut.c1_snoop_cache_cmd_i.value = SNOOP_ACK_NONE
    dut.c1_dir_ready_i.value = 1

    dut.md_rdata_i.value = 0
    dut.mm_rdata_i.value = 0
    dut.mm_ready_i.value = 1


async def reset_dut(dut, mem):
    set_input_defaults(dut)
    dut.rst_ni.value = 0
    await wait_cycles(dut, mem, 5)
    dut.rst_ni.value = 1
    await wait_cycles(dut, mem, 3)
    mem.clear_log()


async def start_test(dut, mem_ready_pattern=None):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    mem = DirectoryMemModel(mem_ready_pattern=mem_ready_pattern)
    await reset_dut(dut, mem)
    return mem


def cache_signals(dut, cache):
    if cache == 0:
        return {
            "bus_valid": dut.c0_bus_valid_i,
            "bus_addr": dut.c0_bus_addr_i,
            "bus_wdata": dut.c0_bus_wdata_i,
            "bus_cmd": dut.c0_bus_cache_cmd_i,
            "bus_ready": dut.c0_bus_ready_o,
            "snoop_valid": dut.c0_snoop_valid_i,
            "snoop_data": dut.c0_snoop_data_i,
            "snoop_cmd": dut.c0_snoop_cache_cmd_i,
            "snoop_ready": dut.c0_snoop_ready_o,
            "dir_valid": dut.c0_dir_valid_o,
            "dir_data": dut.c0_dir_data_o,
            "dir_addr": dut.c0_dir_addr_o,
            "dir_cmd": dut.c0_dir_cmd_o,
            "dir_ready": dut.c0_dir_ready_i,
        }

    return {
        "bus_valid": dut.c1_bus_valid_i,
        "bus_addr": dut.c1_bus_addr_i,
        "bus_wdata": dut.c1_bus_wdata_i,
        "bus_cmd": dut.c1_bus_cache_cmd_i,
        "bus_ready": dut.c1_bus_ready_o,
        "snoop_valid": dut.c1_snoop_valid_i,
        "snoop_data": dut.c1_snoop_data_i,
        "snoop_cmd": dut.c1_snoop_cache_cmd_i,
        "snoop_ready": dut.c1_snoop_ready_o,
        "dir_valid": dut.c1_dir_valid_o,
        "dir_data": dut.c1_dir_data_o,
        "dir_addr": dut.c1_dir_addr_o,
        "dir_cmd": dut.c1_dir_cmd_o,
        "dir_ready": dut.c1_dir_ready_i,
    }


async def send_bus_request(dut, mem, cache, command, addr, data=0):
    sig = cache_signals(dut, cache)

    sig["bus_valid"].value = 1
    sig["bus_addr"].value = addr
    sig["bus_wdata"].value = data
    sig["bus_cmd"].value = command

    for _ in range(TIMEOUT_CYCLES):
        await Timer(1, unit="ns")
        if int(sig["bus_ready"].value):
            await mem.tick(dut)
            sig["bus_valid"].value = 0
            sig["bus_addr"].value = 0
            sig["bus_wdata"].value = 0
            sig["bus_cmd"].value = CACHE_CMD_NONE
            return
        await mem.tick(dut)

    assert False, f"cache {cache} bus request was not accepted"


async def send_snoop_ack(dut, mem, cache, command, data=0):
    sig = cache_signals(dut, cache)

    sig["snoop_valid"].value = 1
    sig["snoop_data"].value = data
    sig["snoop_cmd"].value = command

    for _ in range(TIMEOUT_CYCLES):
        await Timer(1, unit="ns")
        if int(sig["snoop_ready"].value):
            await mem.tick(dut)
            sig["snoop_valid"].value = 0
            sig["snoop_data"].value = 0
            sig["snoop_cmd"].value = SNOOP_ACK_NONE
            return
        await mem.tick(dut)

    assert False, f"cache {cache} snoop ack was not accepted"


async def wait_for_dir_packet(dut, mem, cache, hold_ready_low=0):
    sig = cache_signals(dut, cache)

    if hold_ready_low:
        sig["dir_ready"].value = 0

    for _ in range(TIMEOUT_CYCLES):
        await Timer(1, unit="ns")
        if int(sig["dir_valid"].value):
            cmd = int(sig["dir_cmd"].value)
            data = int(sig["dir_data"].value) & 0xFFFFFFFF
            addr = int(sig["dir_addr"].value) & 0xFFFFFFFF

            for _ in range(hold_ready_low):
                await mem.tick(dut)
                assert int(sig["dir_valid"].value) == 1
                assert int(sig["dir_cmd"].value) == cmd
                assert int(sig["dir_data"].value) & 0xFFFFFFFF == data
                assert int(sig["dir_addr"].value) & 0xFFFFFFFF == addr

            sig["dir_ready"].value = 1
            await mem.tick(dut)
            return cmd, data, addr

        await mem.tick(dut)

    assert False, f"cache {cache} did not receive a directory packet"


async def expect_no_dir_packet(dut, mem, cache, cycles=40):
    sig = cache_signals(dut, cache)
    for _ in range(cycles):
        await Timer(1, unit="ns")
        assert int(sig["dir_valid"].value) == 0
        await mem.tick(dut)


async def bus_request_and_expect(
    dut,
    mem,
    cache,
    command,
    addr,
    data,
    expected_command,
    expected_data,
    settle_after=True,
):
    await send_bus_request(dut, mem, cache, command, addr, data)
    got_cmd, got_data, got_addr = await wait_for_dir_packet(dut, mem, cache)

    assert got_cmd == expected_command, (
        f"got cmd {got_cmd:06b}, expected {expected_command:06b}"
    )
    assert got_data == expected_data & 0xFFFFFFFF, (
        f"got data 0x{got_data:08x}, expected 0x{expected_data & 0xFFFFFFFF:08x}"
    )
    assert got_addr == addr & 0xFFFFFFFF

    if settle_after:
        await wait_cycles(dut, mem, SETTLE_CYCLES)


def assert_meta(mem, addr, sharers=None, dirty=None):
    code = mem.meta[addr & 0x7FF]
    if sharers is not None:
        assert meta_sharers(code) == sharers, (
            f"line {addr:#x} sharers {meta_sharers(code):02b}, expected {sharers:02b}"
        )
    if dirty is not None:
        assert meta_dirty(code) == dirty, (
            f"line {addr:#x} dirty {meta_dirty(code)}, expected {dirty}"
        )


def assert_meta_read_seen(mem, addr):
    idx = addr & 0x7FF
    assert any(i["kind"] == "meta_read" and i["addr"] == idx for i in mem.log), (
        f"expected a metadata read for line index {idx}"
    )


def assert_meta_write_seen(mem, addr, sharers=None, dirty=None):
    idx = addr & 0x7FF
    for item in mem.log:
        if item["kind"] != "meta_write" or item["addr"] != idx:
            continue
        if sharers is not None and meta_sharers(item["code"]) != sharers:
            continue
        if dirty is not None and meta_dirty(item["code"]) != dirty:
            continue
        return

    assert False, f"expected metadata write for line index {idx}"


def assert_mem_read_seen(mem, addr):
    a = addr & 0xFFFFFFFF
    assert any(i["kind"] == "mem_read" and i["addr"] == a for i in mem.log), (
        f"expected a main-memory read at {a:#x}"
    )


def assert_mem_write_seen(mem, addr, data):
    a = addr & 0xFFFFFFFF
    assert any(
        i["kind"] == "mem_write" and i["addr"] == a and i["data"] == (data & 0xFFFFFFFF)
        for i in mem.log
    ), f"expected a main-memory write of {data & 0xFFFFFFFF:#x} at {a:#x}"


def assert_no_mem_write(mem, addr=None):
    for item in mem.log:
        if item["kind"] != "mem_write":
            continue
        if addr is None or item["addr"] == (addr & 0xFFFFFFFF):
            assert False, f"unexpected main-memory write in log: {item}"


async def make_modified(dut, mem, cache, addr, data=0):
    mem.set_mem(addr, data)
    await bus_request_and_expect(
        dut,
        mem,
        cache=cache,
        command=CACHE_CMD_BUS_RDX,
        addr=addr,
        data=0,
        expected_command=DIR_CMD_BUS_RDX_ACK,
        expected_data=data,
    )
    assert_meta(mem, addr, sharers=(1 << cache), dirty=1)


async def make_shared_both(dut, mem, addr, data=0):
    mem.set_mem(addr, data)
    await bus_request_and_expect(
        dut, mem, 0, CACHE_CMD_BUS_RD, addr, 0, DIR_CMD_BUS_RD_ACK, data,
    )
    await bus_request_and_expect(
        dut, mem, 1, CACHE_CMD_BUS_RD, addr, 0, DIR_CMD_BUS_RD_ACK, data,
    )
    assert_meta(mem, addr, sharers=0b11, dirty=0)


async def dirty_evict(dut, mem, cache, addr, data):
    mem.clear_log()
    await send_bus_request(dut, mem, cache, CACHE_CMD_EVICT_DIRTY, addr, data)
    # Part 2: the directory now acknowledges a dirty writeback once its data +
    # metadata are persisted (echoes the EvictDirty code back to the requester).
    cmd, _, _ = await wait_for_dir_packet(dut, mem, cache)
    assert cmd == DIR_CMD_EVICT_DIRTY_ACK, (
        f"expected EvictDirty ack {DIR_CMD_EVICT_DIRTY_ACK}, got {cmd}"
    )
    await wait_cycles(dut, mem, SETTLE_CYCLES)
    assert_mem_write_seen(mem, addr, data)
    assert_meta_write_seen(mem, addr, sharers=0, dirty=0)
    assert_meta(mem, addr, sharers=0, dirty=0)


async def clean_evict(dut, mem, cache, addr):
    mem.clear_log()
    await send_bus_request(dut, mem, cache, CACHE_CMD_EVICT_CLEAN, addr, 0)
    await expect_no_dir_packet(dut, mem, cache, cycles=20)
    await wait_cycles(dut, mem, SETTLE_CYCLES)


@cocotb.test()
async def test_reset_leaves_all_lines_invalid(dut):
    mem = await start_test(dut)

    # Metadata storage is cleared externally; the model reflects that as all
    # lines INVALID (sharers == 0, dirty == 0) right after reset.
    for index in (0, 1, 2, 63, 64, 1023, 1024, 2046, 2047):
        assert_meta(mem, index, sharers=0, dirty=0)


@cocotb.test()
async def test_request_served_without_init_delay(dut):
    # There is no reset-time invalidation phase anymore, so the very first
    # request after reset must be accepted and answered.
    mem = await start_test(dut)

    addr = 0x12
    data = 0x1234ABCD
    mem.set_mem(addr, data)
    await bus_request_and_expect(
        dut, mem, 0, CACHE_CMD_BUS_RD, addr, 0, DIR_CMD_BUS_RD_ACK, data,
    )
    assert_meta(mem, addr, sharers=0b01, dirty=0)


@cocotb.test()
async def test_cold_bus_rd_from_each_cache_reads_main_memory(dut):
    mem = await start_test(dut)

    cases = [
        (0, 0x10, 0xAAAA0010),
        (1, 0x11, 0xBBBB0011),
    ]

    for cache, addr, data in cases:
        mem.set_mem(addr, data)
        mem.clear_log()
        await bus_request_and_expect(
            dut,
            mem,
            cache=cache,
            command=CACHE_CMD_BUS_RD,
            addr=addr,
            data=0,
            expected_command=DIR_CMD_BUS_RD_ACK,
            expected_data=data,
        )
        assert_meta(mem, addr, sharers=(1 << cache), dirty=0)
        assert_meta_read_seen(mem, addr)
        assert_mem_read_seen(mem, addr)
        # A clean read never writes memory back.
        assert_no_mem_write(mem, addr)


@cocotb.test()
async def test_bus_rdx_direct_from_each_cache_sets_modified_owner(dut):
    mem = await start_test(dut)

    for cache, addr, data in [
        (0, 0x20, 0x11110020),
        (1, 0x21, 0x22220021),
    ]:
        mem.set_mem(addr, data)
        mem.clear_log()
        await bus_request_and_expect(
            dut,
            mem,
            cache=cache,
            command=CACHE_CMD_BUS_RDX,
            addr=addr,
            data=0,
            expected_command=DIR_CMD_BUS_RDX_ACK,
            expected_data=data,
        )
        assert_meta(mem, addr, sharers=(1 << cache), dirty=1)
        assert_mem_read_seen(mem, addr)
        assert_no_mem_write(mem, addr)


@cocotb.test()
async def test_dirty_evict_writes_memory_and_invalidates(dut):
    mem = await start_test(dut)

    addr = 0x30
    data = 0xDEAD0030
    await make_modified(dut, mem, cache=0, addr=addr, data=0x1000)
    await dirty_evict(dut, mem, cache=0, addr=addr, data=data)

    assert mem.read_mem(addr) == data


@cocotb.test()
async def test_modified_owner_snoop_bus_rd_flushes_to_requester_and_memory(dut):
    mem = await start_test(dut)

    cases = [
        (0, 1, 0x40, 0xBAD00040),
        (1, 0, 0x41, 0xBAD00041),
    ]

    for owner, requester, addr, flush_data in cases:
        await make_modified(dut, mem, cache=owner, addr=addr, data=0x33330000)
        mem.clear_log()

        await send_bus_request(dut, mem, requester, CACHE_CMD_BUS_RD, addr, 0)
        cmd, payload, snoop_addr = await wait_for_dir_packet(dut, mem, owner)
        assert cmd == DIR_CMD_SNOOP_BUS_RD
        assert payload == 0
        assert snoop_addr == addr

        # The owner flushes its dirty line inline on the snoop-ack channel.
        await send_snoop_ack(dut, mem, owner, SNOOP_ACK_BUS_RD, flush_data)
        cmd, payload, ack_addr = await wait_for_dir_packet(dut, mem, requester)
        assert cmd == DIR_CMD_BUS_RD_ACK
        assert payload == flush_data
        assert ack_addr == addr

        await wait_cycles(dut, mem, SETTLE_CYCLES)
        assert_meta(mem, addr, sharers=0b11, dirty=0)
        assert_mem_write_seen(mem, addr, flush_data)
        assert mem.read_mem(addr) == flush_data


@cocotb.test()
async def test_modified_owner_snoop_bus_rdx_transfers_ownership(dut):
    mem = await start_test(dut)

    cases = [
        (0, 1, 0x44, 0xCAFE0044),
        (1, 0, 0x45, 0xCAFE0045),
    ]

    for owner, requester, addr, ack_data in cases:
        await make_modified(dut, mem, cache=owner, addr=addr, data=0x44440000)
        mem.clear_log()

        await send_bus_request(dut, mem, requester, CACHE_CMD_BUS_RDX, addr, 0)
        cmd, payload, snoop_addr = await wait_for_dir_packet(dut, mem, owner)
        assert cmd == DIR_CMD_SNOOP_BUS_RDX
        assert payload == 0
        assert snoop_addr == addr

        await send_snoop_ack(dut, mem, owner, SNOOP_ACK_BUS_RDX, ack_data)
        cmd, payload, ack_addr = await wait_for_dir_packet(dut, mem, requester)
        assert cmd == DIR_CMD_BUS_RDX_ACK
        assert payload == ack_data
        assert ack_addr == addr

        await wait_cycles(dut, mem, SETTLE_CYCLES)
        assert_meta(mem, addr, sharers=(1 << requester), dirty=1)
        assert_mem_write_seen(mem, addr, ack_data)
        assert mem.read_mem(addr) == ack_data


@cocotb.test()
async def test_shared_bus_rdx_and_bus_upgr_invalidate_other_sharer(dut):
    mem = await start_test(dut)

    shared_data = 0x50500050

    for command, expected_ack, addr, expected_data in [
        (CACHE_CMD_BUS_RDX, DIR_CMD_BUS_RDX_ACK, 0x50, shared_data),
        (CACHE_CMD_BUS_UPGR, DIR_CMD_BUS_UPGR_ACK, 0x51, 0),
    ]:
        await make_shared_both(dut, mem, addr, data=shared_data)
        mem.clear_log()

        await send_bus_request(dut, mem, 0, command, addr, 0)
        cmd, payload, snoop_addr = await wait_for_dir_packet(dut, mem, 1)
        assert cmd == DIR_CMD_SNOOP_BUS_UPGR
        assert payload == 0
        assert snoop_addr == addr

        await send_snoop_ack(dut, mem, 1, SNOOP_ACK_BUS_UPGR, 0)
        cmd, payload, ack_addr = await wait_for_dir_packet(dut, mem, 0)
        assert cmd == expected_ack
        assert payload == expected_data
        assert ack_addr == addr

        await wait_cycles(dut, mem, SETTLE_CYCLES)
        assert_meta(mem, addr, sharers=0b01, dirty=1)
        # Neither a shared upgrade nor an upgrade-hit writes memory back.
        assert_no_mem_write(mem, addr)


@cocotb.test()
async def test_single_sharer_bus_upgr_does_not_snoop_other_cache(dut):
    mem = await start_test(dut)

    addr = 0x58
    data = 0x58580058
    mem.set_mem(addr, data)
    await bus_request_and_expect(
        dut, mem, 0, CACHE_CMD_BUS_RD, addr, 0, DIR_CMD_BUS_RD_ACK, data,
    )
    await bus_request_and_expect(
        dut, mem, 0, CACHE_CMD_BUS_UPGR, addr, 0, DIR_CMD_BUS_UPGR_ACK, 0,
    )
    await expect_no_dir_packet(dut, mem, 1)
    assert_meta(mem, addr, sharers=0b01, dirty=1)


@cocotb.test()
async def test_clean_evict_last_sharer_and_one_of_two_sharers(dut):
    mem = await start_test(dut)

    last_addr = 0x60
    mem.set_mem(last_addr, 0x60600060)
    await bus_request_and_expect(
        dut, mem, 0, CACHE_CMD_BUS_RD, last_addr, 0, DIR_CMD_BUS_RD_ACK, 0x60600060,
    )
    await clean_evict(dut, mem, 0, last_addr)
    assert_meta(mem, last_addr, sharers=0, dirty=0)

    shared_addr = 0x61
    await make_shared_both(dut, mem, shared_addr, data=0x61610061)
    await clean_evict(dut, mem, 0, shared_addr)
    assert_meta(mem, shared_addr, sharers=0b10, dirty=0)

    await bus_request_and_expect(
        dut,
        mem,
        1,
        CACHE_CMD_BUS_UPGR,
        shared_addr,
        0,
        DIR_CMD_BUS_UPGR_ACK,
        0,
    )
    await expect_no_dir_packet(dut, mem, 0)
    assert_meta(mem, shared_addr, sharers=0b10, dirty=1)


@cocotb.test()
async def test_repeated_same_line_state_transition_stress(dut):
    mem = await start_test(dut)

    addr = 0x70
    await make_shared_both(dut, mem, addr, data=0x70700070)

    # Shared -> Modified (cache 0) via upgrade, snooping the other sharer.
    await send_bus_request(dut, mem, 0, CACHE_CMD_BUS_UPGR, addr, 0)
    cmd, _, _ = await wait_for_dir_packet(dut, mem, 1)
    assert cmd == DIR_CMD_SNOOP_BUS_UPGR
    await send_snoop_ack(dut, mem, 1, SNOOP_ACK_BUS_UPGR, 0)
    cmd, _, _ = await wait_for_dir_packet(dut, mem, 0)
    assert cmd == DIR_CMD_BUS_UPGR_ACK
    await wait_cycles(dut, mem, SETTLE_CYCLES)
    assert_meta(mem, addr, sharers=0b01, dirty=1)

    # Modified (cache 0) -> Shared both via cache 1 read that flushes the owner.
    await send_bus_request(dut, mem, 1, CACHE_CMD_BUS_RD, addr, 0)
    cmd, _, _ = await wait_for_dir_packet(dut, mem, 0)
    assert cmd == DIR_CMD_SNOOP_BUS_RD
    await send_snoop_ack(dut, mem, 0, SNOOP_ACK_BUS_RD, 0xAAAA0070)
    cmd, payload, _ = await wait_for_dir_packet(dut, mem, 1)
    assert cmd == DIR_CMD_BUS_RD_ACK
    assert payload == 0xAAAA0070
    await wait_cycles(dut, mem, SETTLE_CYCLES)
    assert_meta(mem, addr, sharers=0b11, dirty=0)

    # Shared both -> Modified (cache 1) via exclusive read, snooping cache 0.
    await send_bus_request(dut, mem, 1, CACHE_CMD_BUS_RDX, addr, 0)
    cmd, _, _ = await wait_for_dir_packet(dut, mem, 0)
    assert cmd == DIR_CMD_SNOOP_BUS_UPGR
    await send_snoop_ack(dut, mem, 0, SNOOP_ACK_BUS_UPGR, 0)
    cmd, payload, _ = await wait_for_dir_packet(dut, mem, 1)
    assert cmd == DIR_CMD_BUS_RDX_ACK
    # Requester keeps the shared copy it already had; data comes from memory.
    assert payload == 0xAAAA0070
    await wait_cycles(dut, mem, SETTLE_CYCLES)
    assert_meta(mem, addr, sharers=0b10, dirty=1)

    # Dirty writeback then a fresh cold read from cache 0.
    await dirty_evict(dut, mem, 1, addr, 0xBBBB0070)
    await bus_request_and_expect(
        dut,
        mem,
        0,
        CACHE_CMD_BUS_RD,
        addr,
        0,
        DIR_CMD_BUS_RD_ACK,
        0xBBBB0070,
    )


@cocotb.test()
async def test_output_ready_backpressure_holds_ack_packet_stable(dut):
    mem = await start_test(dut)

    addr = 0x78
    data = 0x78780078
    mem.set_mem(addr, data)
    await send_bus_request(dut, mem, 0, CACHE_CMD_BUS_RD, addr, 0)
    cmd, payload, got_addr = await wait_for_dir_packet(
        dut, mem, 0, hold_ready_low=6,
    )
    assert cmd == DIR_CMD_BUS_RD_ACK
    assert payload == data
    assert got_addr == addr


@cocotb.test()
async def test_main_memory_ready_backpressure_still_completes_request(dut):
    mem = await start_test(dut, mem_ready_pattern=[1, 0, 0, 1, 1, 0, 1])

    addr = 0x7A
    data = 0x7A7A007A
    mem.set_mem(addr, data)
    await bus_request_and_expect(
        dut, mem, 0, CACHE_CMD_BUS_RD, addr, 0, DIR_CMD_BUS_RD_ACK, data,
    )
    assert_meta(mem, addr, sharers=0b01, dirty=0)


@cocotb.test()
async def test_main_memory_write_backpressure_still_completes_writeback(dut):
    # A dirty eviction drives a main-memory write beat (StWriteData). With the
    # memory holding ready low for several cycles, the controller must stall on
    # mm_ready_i until the write is accepted, then still invalidate the line.
    mem = await start_test(dut, mem_ready_pattern=[1, 0, 0, 0, 1, 1])

    addr = 0x7C
    data = 0x7C7C007C
    await dirty_evict(dut, mem, cache=0, addr=addr, data=data)
    assert mem.read_mem(addr) == data
    assert_meta(mem, addr, sharers=0, dirty=0)


@cocotb.test()
async def test_snoop_send_backpressure_holds_snoop_packet_stable(dut):
    # Force a SNOOP_BUS_RD, then hold the snoop target's dir_ready low. The
    # controller must keep the snoop packet valid and stable in StSendSnoop
    # until the target accepts it, and the flow must still complete afterwards.
    mem = await start_test(dut)

    owner, requester, addr = 0, 1, 0x7E
    await make_modified(dut, mem, cache=owner, addr=addr, data=0x33330000)
    mem.clear_log()

    await send_bus_request(dut, mem, requester, CACHE_CMD_BUS_RD, addr, 0)
    cmd, payload, snoop_addr = await wait_for_dir_packet(
        dut, mem, owner, hold_ready_low=6,
    )
    assert cmd == DIR_CMD_SNOOP_BUS_RD
    assert payload == 0
    assert snoop_addr == addr

    flush_data = 0xF10D007E
    await send_snoop_ack(dut, mem, owner, SNOOP_ACK_BUS_RD, flush_data)
    cmd, payload, ack_addr = await wait_for_dir_packet(dut, mem, requester)
    assert cmd == DIR_CMD_BUS_RD_ACK
    assert payload == flush_data
    assert ack_addr == addr

    await wait_cycles(dut, mem, SETTLE_CYCLES)
    assert_meta(mem, addr, sharers=0b11, dirty=0)
    assert_mem_write_seen(mem, addr, flush_data)


@cocotb.test()
async def test_simultaneous_requests_are_both_served_through_wrr_arbiter(dut):
    mem = await start_test(dut)

    mem.set_mem(0x74, 0x74740074)
    mem.set_mem(0x75, 0x75750075)

    dut.c0_bus_valid_i.value = 1
    dut.c0_bus_addr_i.value = 0x74
    dut.c0_bus_wdata_i.value = 0
    dut.c0_bus_cache_cmd_i.value = CACHE_CMD_BUS_RD

    dut.c1_bus_valid_i.value = 1
    dut.c1_bus_addr_i.value = 0x75
    dut.c1_bus_wdata_i.value = 0
    dut.c1_bus_cache_cmd_i.value = CACHE_CMD_BUS_RD

    accepted = []

    for _ in range(TIMEOUT_CYCLES):
        await Timer(1, unit="ns")
        c0_ready = int(dut.c0_bus_ready_o.value)
        c1_ready = int(dut.c1_bus_ready_o.value)
        assert not (c0_ready and c1_ready), "both cache requests were granted together"

        if c0_ready:
            await mem.tick(dut)
            dut.c0_bus_valid_i.value = 0
            dut.c0_bus_cache_cmd_i.value = CACHE_CMD_NONE
            accepted.append(0)
            break
        if c1_ready:
            await mem.tick(dut)
            dut.c1_bus_valid_i.value = 0
            dut.c1_bus_cache_cmd_i.value = CACHE_CMD_NONE
            accepted.append(1)
            break

        await mem.tick(dut)
    else:
        assert False, "first simultaneous request was not accepted"

    first_cache = accepted[0]
    first_data = 0x74740074 if first_cache == 0 else 0x75750075
    cmd, payload, addr = await wait_for_dir_packet(dut, mem, first_cache)
    assert cmd == DIR_CMD_BUS_RD_ACK
    assert payload == first_data
    assert addr == (0x74 if first_cache == 0 else 0x75)
    await wait_cycles(dut, mem, SETTLE_CYCLES)

    remaining_cache = 1 - first_cache
    for _ in range(TIMEOUT_CYCLES):
        await Timer(1, unit="ns")
        sig = cache_signals(dut, remaining_cache)
        if int(sig["bus_ready"].value):
            await mem.tick(dut)
            sig["bus_valid"].value = 0
            sig["bus_cmd"].value = CACHE_CMD_NONE
            accepted.append(remaining_cache)
            break
        await mem.tick(dut)
    else:
        assert False, "second simultaneous request was not accepted"

    second_data = 0x75750075 if remaining_cache == 1 else 0x74740074
    cmd, payload, addr = await wait_for_dir_packet(dut, mem, remaining_cache)
    assert cmd == DIR_CMD_BUS_RD_ACK
    assert payload == second_data
    assert addr == (0x75 if remaining_cache == 1 else 0x74)

    assert sorted(accepted) == [0, 1]


@cocotb.test()
async def test_directory_boundary_lines_zero_to_2047(dut):
    mem = await start_test(dut)

    addresses = [0, 1, 2, 3, 4, 7, 8, 15, 16, 31, 1023, 1024, 1025, 2046, 2047]

    for index, addr in enumerate(addresses):
        cache = index % 2
        data = 0xABC00000 | addr
        mem.set_mem(addr, data)
        mem.clear_log()
        await bus_request_and_expect(
            dut,
            mem,
            cache=cache,
            command=CACHE_CMD_BUS_RD,
            addr=addr,
            data=0,
            expected_command=DIR_CMD_BUS_RD_ACK,
            expected_data=data,
        )
        assert_meta(mem, addr, sharers=(1 << cache), dirty=0)
        assert_mem_read_seen(mem, addr)


@cocotb.test()
async def test_seeded_random_dirty_writeback_readback_smoke(dut):
    mem = await start_test(dut)
    rng = random.Random(187)
    used = set()

    for _ in range(16):
        while True:
            addr = rng.randint(DIRECTORY_LINE_MIN, DIRECTORY_LINE_MAX)
            if addr not in used:
                used.add(addr)
                break

        owner = rng.randint(0, 1)
        reader = 1 - owner
        initial_data = rng.getrandbits(32)
        dirty_data = rng.getrandbits(32)

        await make_modified(dut, mem, owner, addr, initial_data)
        await dirty_evict(dut, mem, owner, addr, dirty_data)
        await bus_request_and_expect(
            dut,
            mem,
            reader,
            CACHE_CMD_BUS_RD,
            addr,
            0,
            DIR_CMD_BUS_RD_ACK,
            dirty_data,
        )


# Default ADDR_SPACE_WORDS for directory_controller_full: the valid space is
# [0, 8192) (the 8192x32 main memory / 8192-line directory). Requests outside it
# are answered with zero data and must not reach either memory.
ADDR_SPACE_WORDS = 8192


@cocotb.test()
async def test_out_of_range_read_requests_return_zero_without_touching_memory(dut):
    mem = await start_test(dut)

    oor_addrs = [ADDR_SPACE_WORDS, ADDR_SPACE_WORDS + 1, 0x4000, 0xDEADBEEF]
    read_cases = [
        (CACHE_CMD_BUS_RD, DIR_CMD_BUS_RD_ACK),
        (CACHE_CMD_BUS_RDX, DIR_CMD_BUS_RDX_ACK),
        (CACHE_CMD_BUS_UPGR, DIR_CMD_BUS_UPGR_ACK),
    ]

    for cache in (0, 1):
        for addr in oor_addrs:
            for command, expected_ack in read_cases:
                mem.clear_log()
                await send_bus_request(dut, mem, cache, command, addr, 0)
                cmd, data, got_addr = await wait_for_dir_packet(dut, mem, cache)

                assert cmd == expected_ack, (
                    f"oor {command:05b} @ {addr:#x}: got cmd {cmd:06b}, "
                    f"expected {expected_ack:06b}"
                )
                assert data == 0, (
                    f"oor {command:05b} @ {addr:#x}: expected zero data, got {data:#x}"
                )
                assert got_addr == addr & 0xFFFFFFFF

                assert not any(
                    i["kind"] in ("meta_read", "meta_write") for i in mem.log
                ), f"oor {command:05b} @ {addr:#x} touched metadata: {mem.log}"
                assert not any(
                    i["kind"] in ("mem_read", "mem_write") for i in mem.log
                ), f"oor {command:05b} @ {addr:#x} touched main memory: {mem.log}"

                await wait_cycles(dut, mem, SETTLE_CYCLES)


@cocotb.test()
async def test_out_of_range_evictions_are_dropped_without_memory_access(dut):
    mem = await start_test(dut)

    for command in (CACHE_CMD_EVICT_CLEAN, CACHE_CMD_EVICT_DIRTY):
        mem.clear_log()
        await send_bus_request(dut, mem, 0, command, 0x4000, 0xDEAD)
        await expect_no_dir_packet(dut, mem, 0, cycles=30)
        assert_no_mem_write(mem)
        assert not any(
            i["kind"] in ("meta_read", "meta_write") for i in mem.log
        ), f"out-of-range evict touched metadata: {mem.log}"
        await wait_cycles(dut, mem, SETTLE_CYCLES)


@cocotb.test()
async def test_boundary_last_in_range_line_is_served_normally(dut):
    # ADDR_SPACE_WORDS-1 is the highest in-range line and must still be served.
    mem = await start_test(dut)

    addr = ADDR_SPACE_WORDS - 1
    data = 0x5A5A5A5A
    mem.set_mem(addr, data)
    mem.clear_log()
    await bus_request_and_expect(
        dut, mem, 0, CACHE_CMD_BUS_RD, addr, 0, DIR_CMD_BUS_RD_ACK, data,
    )
    assert_meta(mem, addr, sharers=0b01, dirty=0)
    assert_mem_read_seen(mem, addr)


@cocotb.test()
async def test_scan_chain_continuity(dut):
    """A single marker must traverse the whole directory-controller scan chain:
    18 controller regs (156 bits) then u_wrr_arbiter (curr_ptr[1] + credit_cnt[3])
    = 160 bits, in exactly that many cycles under debug_mode_i."""
    CHAIN_LEN = 156 + 4

    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    # Quiesce functional inputs; scan mode ignores them but avoids X propagation.
    for sig in ("c0_bus_valid_i", "c1_bus_valid_i", "c0_snoop_valid_i",
                "c1_snoop_valid_i", "c0_dir_ready_i", "c1_dir_ready_i", "mm_ready_i"):
        if hasattr(dut, sig):
            getattr(dut, sig).value = 0
    dut.debug_mode_i.value = 0
    dut.scan_in_i.value = 0
    dut.rst_ni.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk_i)
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)

    # Enter scan mode and flush the chain to zero.
    dut.debug_mode_i.value = 1
    dut.scan_in_i.value = 0
    for _ in range(CHAIN_LEN):
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ps")
    assert int(dut.scan_out_o.value) == 0, "chain not flushed to 0"

    # Inject a single 1; it must appear at scan_out exactly at the last cycle.
    dut.scan_in_i.value = 1
    for cycle in range(CHAIN_LEN):
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ps")
        if cycle == 0:
            dut.scan_in_i.value = 0
        expected = int(cycle == CHAIN_LEN - 1)
        assert int(dut.scan_out_o.value) == expected, (
            f"scan marker at cycle {cycle + 1}, expected {CHAIN_LEN}"
        )
    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ps")
    assert int(dut.scan_out_o.value) == 0


def find_source_file():
    env_source = os.getenv("DIRECTORY_CONTROLLER_RTL")
    if env_source:
        return Path(env_source).resolve()

    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent / "src" / "directory_controller" / "directory_controller_full.sv",
        here.parent.parent / "src" / "directory_controller_full.sv",
        here.parent / "directory_controller_full.sv",
        here.parent.parent / "directory_controller_full.sv",
    ]

    for path in candidates:
        if path.exists():
            return path.resolve()

    raise FileNotFoundError(
        "Could not find directory_controller_full RTL. Set "
        "DIRECTORY_CONTROLLER_RTL or place directory_controller_full.sv in src/."
    )


def find_arbiter_file():
    env_source = os.getenv("WRR_ARBITER_RTL")
    if env_source:
        return Path(env_source).resolve()

    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent / "src" / "arb" / "wrr_arbiter.sv",
        here.parent.parent / "src" / "wrr_arbiter.sv",
        here.parent / "wrr_arbiter.sv",
        here.parent.parent / "wrr_arbiter.sv",
    ]

    for path in candidates:
        if path.exists():
            return path.resolve()

    raise FileNotFoundError(
        "Could not find wrr_arbiter RTL. Set WRR_ARBITER_RTL or place "
        "wrr_arbiter.sv in src/arb/."
    )


def run_tests():
    source = find_source_file()
    arbiter = find_arbiter_file()

    if SIM == "icarus":
        build_args = ["-g2012"]
    elif SIM == "verilator":
        build_args = ["--timing", "--trace", "--trace-fst"]
    else:
        build_args = []

    runner = get_runner(SIM)
    runner.build(
        sources=[arbiter, source],
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
