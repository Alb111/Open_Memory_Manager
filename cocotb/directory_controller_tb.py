import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotb_tools.runner import get_runner

SIM = os.getenv("SIM", "icarus")
HDL_TOPLEVEL = "directory_controller"

CACHE_CMD_NONE = 0b00000
CACHE_CMD_BUS_RD = 0b00001
CACHE_CMD_BUS_RDX = 0b00010
CACHE_CMD_BUS_UPGR = 0b00100
CACHE_CMD_EVICT_CLEAN = 0b01000
CACHE_CMD_EVICT_DIRTY = 0b10000

SNOOP_ACK_NONE = 0b000
SNOOP_ACK_BUS_RD = 0b001
SNOOP_ACK_BUS_RDX = 0b010
SNOOP_ACK_BUS_UPGR = 0b100

DIR_CMD_NONE = 0b000000
DIR_CMD_BUS_RD_ACK = 0b000001
DIR_CMD_BUS_RDX_ACK = 0b000010
DIR_CMD_BUS_UPGR_ACK = 0b000100
DIR_CMD_SNOOP_BUS_RD = 0b001000
DIR_CMD_SNOOP_BUS_RDX = 0b010000
DIR_CMD_SNOOP_BUS_UPGR = 0b100000

LINE_INVALID = 0b00
LINE_SHARED = 0b01
LINE_MODIFIED = 0b10

DIRECTORY_LINE_MIN = 0
DIRECTORY_LINE_MAX = 127
META_BASE = 0
CACHE0_BACKUP_BASE = 1792
CACHE1_BACKUP_BASE = 1920

INIT_TIMEOUT_CYCLES = 1500
TIMEOUT_CYCLES = 900
SETTLE_CYCLES = 80


class DirectoryMemModel:
    """Behavioral model for the directory_mem abstraction.

    Addresses 0 through 127 are metadata entries. Addresses 1792 through 1919
    are cache 0 backup words. Addresses 1920 through 2047 are cache 1 backup
    words. The model responds through the same split data and metadata fields
    that the RTL directory controller uses.
    """

    def __init__(self, ready_pattern=None):
        self.ready_pattern = ready_pattern or [1]
        self.cycle = 0
        self.log = []
        self.meta = [
            {"state": LINE_INVALID, "sharers": 0, "owner": 0, "valid": 0}
            for _ in range(128)
        ]
        self.backup = {}

    def clear_log(self):
        self.log.clear()

    @staticmethod
    def line_index(addr):
        return addr & 0x7F

    @staticmethod
    def backup_addr(cache, addr):
        base = CACHE1_BACKUP_BASE if cache else CACHE0_BACKUP_BASE
        return base + (addr & 0x7F)

    def set_backup(self, cache, addr, data):
        self.backup[self.backup_addr(cache, addr)] = data & 0xFFFFFFFF

    def read_backup(self, cache, addr):
        return self.backup.get(self.backup_addr(cache, addr), 0) & 0xFFFFFFFF

    def classify_addr(self, addr):
        if META_BASE <= addr <= META_BASE + 127:
            return "metadata"
        if CACHE0_BACKUP_BASE <= addr <= CACHE0_BACKUP_BASE + 127:
            return "backup0"
        if CACHE1_BACKUP_BASE <= addr <= CACHE1_BACKUP_BASE + 127:
            return "backup1"
        return "other"

    def read_outputs_for_addr(self, addr):
        kind = self.classify_addr(addr)
        r_data = 0
        r_state = LINE_INVALID
        r_sharers = 0
        r_owner = 0
        r_valid = 0

        if kind == "metadata":
            entry = self.meta[self.line_index(addr)]
            r_state = entry["state"] & 0x3
            r_sharers = entry["sharers"] & 0x3
            r_owner = entry["owner"] & 0x1
            r_valid = entry["valid"] & 0x1
        elif kind in ("backup0", "backup1"):
            r_data = self.backup.get(addr, 0) & 0xFFFFFFFF

        return r_data, r_state, r_sharers, r_owner, r_valid

    def commit_write(self, addr, wstrb, data, state, sharers, owner, valid):
        kind = self.classify_addr(addr)

        if kind == "metadata":
            self.meta[self.line_index(addr)] = {
                "state": state & 0x3,
                "sharers": sharers & 0x3,
                "owner": owner & 0x1,
                "valid": valid & 0x1,
            }
        elif kind in ("backup0", "backup1"):
            old = self.backup.get(addr, 0) & 0xFFFFFFFF
            new = old
            for byte in range(4):
                if (wstrb >> byte) & 1:
                    mask = 0xFF << (8 * byte)
                    new = (new & ~mask) | (data & mask)
            self.backup[addr] = new & 0xFFFFFFFF

    def drive_read_outputs(self, dut, addr):
        r_data, r_state, r_sharers, r_owner, r_valid = self.read_outputs_for_addr(addr)
        dut.dir_mem_r_data_i.value = r_data
        dut.dir_mem_r_state_i.value = r_state
        dut.dir_mem_r_sharers_i.value = r_sharers
        dut.dir_mem_r_owner_i.value = r_owner
        dut.dir_mem_r_valid_data_i.value = r_valid

    async def tick(self, dut):
        ready = self.ready_pattern[self.cycle % len(self.ready_pattern)]
        dut.dir_mem_ready_i.value = ready

        await Timer(1, unit="ns")

        if int(dut.rst_ni.value) == 0:
            dut.dir_mem_r_data_i.value = 0
            dut.dir_mem_r_state_i.value = LINE_INVALID
            dut.dir_mem_r_sharers_i.value = 0
            dut.dir_mem_r_owner_i.value = 0
            dut.dir_mem_r_valid_data_i.value = 0
            await RisingEdge(dut.clk_i)
            self.cycle += 1
            return

        valid = int(dut.dir_mem_valid_o.value)
        addr = int(dut.dir_mem_addr_o.value) & 0xFFFFFFFF
        wstrb = int(dut.dir_mem_wstrb_o.value) & 0xF
        w_data = int(dut.dir_mem_w_data_o.value) & 0xFFFFFFFF
        w_state = int(dut.dir_mem_w_state_o.value) & 0x3
        w_sharers = int(dut.dir_mem_w_sharers_o.value) & 0x3
        w_owner = int(dut.dir_mem_w_owner_o.value) & 0x1
        w_valid = int(dut.dir_mem_w_valid_data_o.value) & 0x1

        r_data, r_state, r_sharers, r_owner, r_valid = self.read_outputs_for_addr(addr)

        await RisingEdge(dut.clk_i)

        if valid and ready:
            if wstrb:
                self.commit_write(
                    addr,
                    wstrb,
                    w_data,
                    w_state,
                    w_sharers,
                    w_owner,
                    w_valid,
                )
                r_data, r_state, r_sharers, r_owner, r_valid = (
                    self.read_outputs_for_addr(addr)
                )

            self.log.append({
                "addr": addr,
                "kind": self.classify_addr(addr),
                "wstrb": wstrb,
                "w_data": w_data,
                "w_state": w_state,
                "w_sharers": w_sharers,
                "w_owner": w_owner,
                "w_valid": w_valid,
                "r_data": r_data,
                "r_state": r_state,
                "r_sharers": r_sharers,
                "r_owner": r_owner,
                "r_valid": r_valid,
            })

            dut.dir_mem_r_data_i.value = r_data
            dut.dir_mem_r_state_i.value = r_state
            dut.dir_mem_r_sharers_i.value = r_sharers
            dut.dir_mem_r_owner_i.value = r_owner
            dut.dir_mem_r_valid_data_i.value = r_valid

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

    dut.dir_mem_ready_i.value = 1
    dut.dir_mem_r_data_i.value = 0
    dut.dir_mem_r_state_i.value = LINE_INVALID
    dut.dir_mem_r_sharers_i.value = 0
    dut.dir_mem_r_owner_i.value = 0
    dut.dir_mem_r_valid_data_i.value = 0


async def wait_for_initialization(dut, mem):
    for _ in range(INIT_TIMEOUT_CYCLES):
        await Timer(1, unit="ns")
        if int(dut.dir_state_invalidated_o.value):
            return
        await mem.tick(dut)

    assert False, "directory state invalidation did not complete"


async def reset_dut(dut, mem):
    set_input_defaults(dut)
    dut.rst_ni.value = 0
    await wait_cycles(dut, mem, 5)
    dut.rst_ni.value = 1
    await wait_for_initialization(dut, mem)
    await wait_cycles(dut, mem, 3)
    mem.clear_log()


async def start_test(dut, ready_pattern=None):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    mem = DirectoryMemModel(ready_pattern=ready_pattern)
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


async def send_dirty_flush(dut, mem, cache, addr, data):
    await send_bus_request(dut, mem, cache, CACHE_CMD_EVICT_DIRTY, addr, data)


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


def assert_meta(mem, addr, state=None, sharers=None, owner=None, valid=None):
    entry = mem.meta[addr & 0x7F]
    if state is not None:
        assert entry["state"] == state, entry
    if sharers is not None:
        assert entry["sharers"] == sharers, entry
    if owner is not None:
        assert entry["owner"] == owner, entry
    if valid is not None:
        assert entry["valid"] == valid, entry


def assert_access_seen(mem, kind, addr, write=None, data=None):
    addr &= 0xFFFFFFFF
    matches = []
    for item in mem.log:
        if item["kind"] != kind or item["addr"] != addr:
            continue
        if write is not None and bool(item["wstrb"]) != write:
            continue
        if data is not None and item["w_data"] != (data & 0xFFFFFFFF):
            continue
        matches.append(item)

    assert matches, f"expected access kind={kind} addr={addr} write={write}"


def assert_meta_read_seen(mem, addr):
    assert_access_seen(mem, "metadata", addr & 0x7F, write=False)


def assert_meta_write_seen(mem, addr, state=None, sharers=None, owner=None, valid=None):
    idx = addr & 0x7F
    for item in mem.log:
        if item["kind"] != "metadata" or item["addr"] != idx or item["wstrb"] == 0:
            continue
        if state is not None and item["w_state"] != state:
            continue
        if sharers is not None and item["w_sharers"] != sharers:
            continue
        if owner is not None and item["w_owner"] != owner:
            continue
        if valid is not None and item["w_valid"] != valid:
            continue
        return

    assert False, f"expected metadata write for index {idx}"


def assert_backup_read_seen(mem, cache, addr):
    kind = "backup1" if cache else "backup0"
    assert_access_seen(mem, kind, mem.backup_addr(cache, addr), write=False)


def assert_backup_write_seen(mem, cache, addr, data):
    kind = "backup1" if cache else "backup0"
    assert_access_seen(mem, kind, mem.backup_addr(cache, addr), write=True, data=data)


async def make_modified(dut, mem, cache, addr, backup_data=0):
    mem.set_backup(cache, addr, backup_data)
    await bus_request_and_expect(
        dut,
        mem,
        cache=cache,
        command=CACHE_CMD_BUS_RDX,
        addr=addr,
        data=0,
        expected_command=DIR_CMD_BUS_RDX_ACK,
        expected_data=backup_data,
    )
    assert_meta(mem, addr, state=LINE_MODIFIED, sharers=0, owner=cache, valid=1)


async def make_shared_both(dut, mem, addr, data=0):
    mem.set_backup(0, addr, data)
    mem.set_backup(1, addr, data)
    await bus_request_and_expect(
        dut, mem, 0, CACHE_CMD_BUS_RD, addr, 0, DIR_CMD_BUS_RD_ACK, data,
    )
    await bus_request_and_expect(
        dut, mem, 1, CACHE_CMD_BUS_RD, addr, 0, DIR_CMD_BUS_RD_ACK, data,
    )
    assert_meta(mem, addr, state=LINE_SHARED, sharers=0b11, owner=0, valid=1)


async def dirty_evict(dut, mem, cache, addr, data):
    mem.clear_log()
    await send_bus_request(dut, mem, cache, CACHE_CMD_EVICT_DIRTY, addr, data)
    await expect_no_dir_packet(dut, mem, cache, cycles=20)
    await wait_cycles(dut, mem, SETTLE_CYCLES)
    assert_backup_write_seen(mem, 0, addr, data)
    assert_backup_write_seen(mem, 1, addr, data)
    assert_meta_write_seen(mem, addr, state=LINE_INVALID, sharers=0, owner=0, valid=0)
    assert_meta(mem, addr, state=LINE_INVALID, sharers=0, owner=0, valid=0)


async def clean_evict(dut, mem, cache, addr):
    mem.clear_log()
    await send_bus_request(dut, mem, cache, CACHE_CMD_EVICT_CLEAN, addr, 0)
    await expect_no_dir_packet(dut, mem, cache, cycles=20)
    await wait_cycles(dut, mem, SETTLE_CYCLES)


@cocotb.test()
async def test_reset_invalidates_all_metadata_entries(dut):
    mem = await start_test(dut)

    assert int(dut.dir_state_invalidated_o.value) == 1
    assert int(dut.dir_mem_resp_ready_o.value) == 1

    for index in range(128):
        assert_meta(mem, index, state=LINE_INVALID, sharers=0, owner=0, valid=0)


@cocotb.test()
async def test_requests_are_not_accepted_before_invalidation_finishes(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    mem = DirectoryMemModel(ready_pattern=[1, 0, 1, 0, 1])

    set_input_defaults(dut)
    dut.rst_ni.value = 0
    await wait_cycles(dut, mem, 4)
    dut.rst_ni.value = 1

    dut.c0_bus_valid_i.value = 1
    dut.c0_bus_addr_i.value = 0x10
    dut.c0_bus_cache_cmd_i.value = CACHE_CMD_BUS_RD

    for _ in range(40):
        await Timer(1, unit="ns")
        assert int(dut.dir_state_invalidated_o.value) == 0
        assert int(dut.c0_bus_ready_o.value) == 0
        await mem.tick(dut)

    dut.c0_bus_valid_i.value = 0
    dut.c0_bus_cache_cmd_i.value = CACHE_CMD_NONE


@cocotb.test()
async def test_cold_bus_rd_from_each_cache_uses_that_cache_backup(dut):
    mem = await start_test(dut)

    cases = [
        (0, 0x10, 0xAAAA0010),
        (1, 0x11, 0xBBBB0011),
    ]

    for cache, addr, data in cases:
        mem.set_backup(cache, addr, data)
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
        assert_meta(mem, addr, state=LINE_SHARED, sharers=(1 << cache), valid=1)
        assert_meta_read_seen(mem, addr)
        assert_backup_read_seen(mem, cache, addr)
        assert_backup_write_seen(mem, 0, addr, data)
        assert_backup_write_seen(mem, 1, addr, data)


@cocotb.test()
async def test_bus_rdx_direct_from_each_cache_sets_modified_owner(dut):
    mem = await start_test(dut)

    for cache, addr, data in [
        (0, 0x20, 0x11110020),
        (1, 0x21, 0x22220021),
    ]:
        mem.set_backup(cache, addr, data)
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
        assert_meta(mem, addr, state=LINE_MODIFIED, sharers=0, owner=cache, valid=1)
        assert_backup_read_seen(mem, cache, addr)
        assert_backup_write_seen(mem, 0, addr, data)
        assert_backup_write_seen(mem, 1, addr, data)


@cocotb.test()
async def test_dirty_evict_writes_both_backups_invalidates_metadata_no_ack(dut):
    mem = await start_test(dut)

    addr = 0x30
    data = 0xDEAD0030
    await make_modified(dut, mem, cache=0, addr=addr, backup_data=0x1000)
    await dirty_evict(dut, mem, cache=0, addr=addr, data=data)

    assert mem.read_backup(0, addr) == data
    assert mem.read_backup(1, addr) == data


@cocotb.test()
async def test_modified_owner_snoop_bus_rd_uses_dirty_flush_both_directions(dut):
    mem = await start_test(dut)

    cases = [
        (0, 1, 0x40, 0xFACE0040, 0xBAD00040),
        (1, 0, 0x41, 0xBEEF0041, 0xBAD00041),
    ]

    for owner, requester, addr, flush_data, ack_data in cases:
        await make_modified(dut, mem, cache=owner, addr=addr, backup_data=0x33330000)
        mem.clear_log()

        await send_bus_request(dut, mem, requester, CACHE_CMD_BUS_RD, addr, 0)
        cmd, payload, snoop_addr = await wait_for_dir_packet(dut, mem, owner)
        assert cmd == DIR_CMD_SNOOP_BUS_RD
        assert payload == 0
        assert snoop_addr == addr

        await send_dirty_flush(dut, mem, owner, addr, flush_data)
        await send_snoop_ack(dut, mem, owner, SNOOP_ACK_BUS_RD, ack_data)
        cmd, payload, ack_addr = await wait_for_dir_packet(dut, mem, requester)
        assert cmd == DIR_CMD_BUS_RD_ACK
        assert payload == flush_data
        assert ack_addr == addr

        await wait_cycles(dut, mem, SETTLE_CYCLES)
        assert_meta(mem, addr, state=LINE_SHARED, sharers=0b11, owner=0, valid=1)
        assert_backup_write_seen(mem, 0, addr, flush_data)
        assert_backup_write_seen(mem, 1, addr, flush_data)


@cocotb.test()
async def test_modified_owner_snoop_bus_rdx_uses_snoop_ack_both_directions(dut):
    mem = await start_test(dut)

    cases = [
        (0, 1, 0x44, 0xCAFE0044),
        (1, 0, 0x45, 0xCAFE0045),
    ]

    for owner, requester, addr, ack_data in cases:
        await make_modified(dut, mem, cache=owner, addr=addr, backup_data=0x44440000)
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
        assert_meta(mem, addr, state=LINE_MODIFIED, sharers=0, owner=requester, valid=1)
        assert_backup_write_seen(mem, 0, addr, ack_data)
        assert_backup_write_seen(mem, 1, addr, ack_data)


@cocotb.test()
async def test_shared_bus_rdx_and_bus_upgr_invalidate_other_sharer(dut):
    mem = await start_test(dut)

    for command, expected_ack, addr, expected_data in [
        (CACHE_CMD_BUS_RDX, DIR_CMD_BUS_RDX_ACK, 0x50, 0x50500050),
        (CACHE_CMD_BUS_UPGR, DIR_CMD_BUS_UPGR_ACK, 0x51, 0),
    ]:
        await make_shared_both(dut, mem, addr, data=0x50500050)
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
        assert_meta(mem, addr, state=LINE_MODIFIED, sharers=0, owner=0, valid=1)


@cocotb.test()
async def test_single_sharer_bus_upgr_does_not_snoop_other_cache(dut):
    mem = await start_test(dut)

    addr = 0x58
    data = 0x58580058
    mem.set_backup(0, addr, data)
    await bus_request_and_expect(
        dut, mem, 0, CACHE_CMD_BUS_RD, addr, 0, DIR_CMD_BUS_RD_ACK, data,
    )
    await bus_request_and_expect(
        dut, mem, 0, CACHE_CMD_BUS_UPGR, addr, 0, DIR_CMD_BUS_UPGR_ACK, 0,
    )
    await expect_no_dir_packet(dut, mem, 1)
    assert_meta(mem, addr, state=LINE_MODIFIED, sharers=0, owner=0, valid=1)


@cocotb.test()
async def test_clean_evict_last_sharer_and_one_of_two_sharers(dut):
    mem = await start_test(dut)

    last_addr = 0x60
    mem.set_backup(0, last_addr, 0x60600060)
    await bus_request_and_expect(
        dut, mem, 0, CACHE_CMD_BUS_RD, last_addr, 0, DIR_CMD_BUS_RD_ACK, 0x60600060,
    )
    await clean_evict(dut, mem, 0, last_addr)
    assert_meta(mem, last_addr, state=LINE_INVALID, sharers=0, owner=0, valid=0)

    shared_addr = 0x61
    await make_shared_both(dut, mem, shared_addr, data=0x61610061)
    await clean_evict(dut, mem, 0, shared_addr)
    assert_meta(mem, shared_addr, state=LINE_SHARED, sharers=0b10, owner=0, valid=1)

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
    assert_meta(mem, shared_addr, state=LINE_MODIFIED, sharers=0, owner=1, valid=1)


@cocotb.test()
async def test_repeated_same_line_state_transition_stress(dut):
    mem = await start_test(dut)

    addr = 0x70
    await make_shared_both(dut, mem, addr, data=0x70700070)

    await send_bus_request(dut, mem, 0, CACHE_CMD_BUS_UPGR, addr, 0)
    cmd, _, _ = await wait_for_dir_packet(dut, mem, 1)
    assert cmd == DIR_CMD_SNOOP_BUS_UPGR
    await send_snoop_ack(dut, mem, 1, SNOOP_ACK_BUS_UPGR, 0)
    cmd, _, _ = await wait_for_dir_packet(dut, mem, 0)
    assert cmd == DIR_CMD_BUS_UPGR_ACK
    await wait_cycles(dut, mem, SETTLE_CYCLES)
    assert_meta(mem, addr, state=LINE_MODIFIED, owner=0, valid=1)

    await send_bus_request(dut, mem, 1, CACHE_CMD_BUS_RD, addr, 0)
    cmd, _, _ = await wait_for_dir_packet(dut, mem, 0)
    assert cmd == DIR_CMD_SNOOP_BUS_RD
    await send_snoop_ack(dut, mem, 0, SNOOP_ACK_BUS_RD, 0xAAAA0070)
    cmd, payload, _ = await wait_for_dir_packet(dut, mem, 1)
    assert cmd == DIR_CMD_BUS_RD_ACK
    assert payload == 0xAAAA0070
    await wait_cycles(dut, mem, SETTLE_CYCLES)
    assert_meta(mem, addr, state=LINE_SHARED, sharers=0b11, valid=1)

    await send_bus_request(dut, mem, 1, CACHE_CMD_BUS_RDX, addr, 0)
    cmd, _, _ = await wait_for_dir_packet(dut, mem, 0)
    assert cmd == DIR_CMD_SNOOP_BUS_UPGR
    await send_snoop_ack(dut, mem, 0, SNOOP_ACK_BUS_UPGR, 0)
    cmd, payload, _ = await wait_for_dir_packet(dut, mem, 1)
    assert cmd == DIR_CMD_BUS_RDX_ACK
    assert payload == 0xAAAA0070
    await wait_cycles(dut, mem, SETTLE_CYCLES)
    assert_meta(mem, addr, state=LINE_MODIFIED, owner=1, valid=1)

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
    mem.set_backup(0, addr, data)
    await send_bus_request(dut, mem, 0, CACHE_CMD_BUS_RD, addr, 0)
    cmd, payload, got_addr = await wait_for_dir_packet(
        dut, mem, 0, hold_ready_low=6,
    )
    assert cmd == DIR_CMD_BUS_RD_ACK
    assert payload == data
    assert got_addr == addr


@cocotb.test()
async def test_directory_mem_ready_backpressure_still_completes_request(dut):
    mem = await start_test(dut, ready_pattern=[1, 0, 0, 1, 1, 0, 1])

    addr = 0x7A
    data = 0x7A7A007A
    mem.set_backup(0, addr, data)
    await bus_request_and_expect(
        dut, mem, 0, CACHE_CMD_BUS_RD, addr, 0, DIR_CMD_BUS_RD_ACK, data,
    )
    assert_meta(mem, addr, state=LINE_SHARED, sharers=0b01, valid=1)


@cocotb.test()
async def test_simultaneous_requests_are_both_served_through_wrr_arbiter(dut):
    mem = await start_test(dut)

    mem.set_backup(0, 0x74, 0x74740074)
    mem.set_backup(1, 0x75, 0x75750075)

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
async def test_directory_boundary_lines_zero_to_127(dut):
    mem = await start_test(dut)

    addresses = [0, 1, 2, 3, 4, 7, 8, 15, 16, 31, 32, 63, 64, 65, 126, 127]

    for index, addr in enumerate(addresses):
        cache = index % 2
        data = 0xABC00000 | addr
        mem.set_backup(cache, addr, data)
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
        assert_meta(mem, addr, state=LINE_SHARED, sharers=(1 << cache), valid=1)
        assert_backup_read_seen(mem, cache, addr)


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


@cocotb.test(skip=True)
async def test_out_of_range_addresses_are_not_part_of_this_controller_contract(dut):
    """Documentation test.

    This controller tracks 128 coherent line IDs. Addresses above 127 alias by
    index and should only be used if that is intentional at the system level.
    """
    assert False


def find_source_file():
    env_source = os.getenv("DIRECTORY_CONTROLLER_RTL")
    if env_source:
        return Path(env_source).resolve()

    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent / "src" / "directory_controller.sv",
        here.parent / "directory_controller.sv",
        here.parent / "directory_controller_directory_mem.sv",
        here.parent / "directory_controller_metadata_only.sv",
        here.parent.parent / "src" / "directory_controller" / "directory_controller.sv",
        here.parent.parent / "directory_controller.sv",
    ]

    for path in candidates:
        if path.exists():
            return path.resolve()

    raise FileNotFoundError(
        "Could not find directory_controller RTL. Set DIRECTORY_CONTROLLER_RTL "
        "or place directory_controller.sv in src/."
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

