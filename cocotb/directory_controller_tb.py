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

DIRECTORY_LINE_MIN = 0
DIRECTORY_LINE_MAX = 127
DIR_META_BASE = 1792
DIR_DATA_BASE = 1920
INIT_CYCLES = 1100
TIMEOUT_CYCLES = 700


class MemoryModel:
    """Small word-addressed memory model for the controller-only test."""

    def __init__(self, ready_pattern=None):
        self.mem = {}
        self.log = []
        self.cycle = 0
        self.ready_pattern = ready_pattern or [1]

    def clear_log(self):
        self.log.clear()

    def read(self, addr):
        return self.mem.get(addr & 0x7FF, 0) & 0xFFFFFFFF

    def write(self, addr, data, wstrb):
        addr &= 0x7FF
        old = self.read(addr)
        new = old

        for byte in range(4):
            if (wstrb >> byte) & 1:
                mask = 0xFF << (8 * byte)
                new = (new & ~mask) | (data & mask)

        self.mem[addr] = new & 0xFFFFFFFF

    async def tick(self, dut):
        ready = self.ready_pattern[self.cycle % len(self.ready_pattern)]
        dut.dir_mem_ready_i.value = ready

        await Timer(1, unit="ns")

        valid = int(dut.dir_mem_valid_o.value)
        addr = int(dut.dir_mem_addr_o.value) & 0x7FF
        wdata = int(dut.dir_mem_wdata_o.value) & 0xFFFFFFFF
        wstrb = int(dut.dir_mem_wstrb_o.value) & 0xF
        rdata = self.read(addr)

        await RisingEdge(dut.clk_i)

        if valid and ready:
            if wstrb:
                self.write(addr, wdata, wstrb)
                rdata = self.read(addr)

            self.log.append({
                "addr": addr,
                "wdata": wdata,
                "wstrb": wstrb,
                "rdata": rdata,
            })
            dut.dir_mem_rdata_i.value = rdata

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

    dut.dir_mem_rdata_i.value = 0
    dut.dir_mem_ready_i.value = 1


async def reset_dut(dut, mem):
    set_input_defaults(dut)
    dut.rst_ni.value = 0
    await wait_cycles(dut, mem, 5)
    dut.rst_ni.value = 1
    await wait_cycles(dut, mem, INIT_CYCLES)
    mem.clear_log()


async def start_test(dut, ready_pattern=None):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    mem = MemoryModel(ready_pattern=ready_pattern)
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


async def expect_no_dir_packet(dut, mem, cache, cycles=30):
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
):
    await send_bus_request(dut, mem, cache, command, addr, data)
    got_cmd, got_data, got_addr = await wait_for_dir_packet(dut, mem, cache)

    assert got_cmd == expected_command, (
        f"got cmd {got_cmd:06b}, expected {expected_command:06b}"
    )
    assert got_data == expected_data & 0xFFFFFFFF, (
        f"got data 0x{got_data:08x}, expected 0x{expected_data:08x}"
    )
    assert got_addr == addr & 0xFFFFFFFF


def backing_value(mem, addr):
    return mem.read(addr)


def assert_mem_read_seen(mem, addr):
    addr &= 0x7FF
    assert any(
        item["addr"] == addr and item["wstrb"] == 0
        for item in mem.log
    ), f"expected read from memory address {addr}"


def assert_mem_write_seen(mem, addr, data):
    addr &= 0x7FF
    data &= 0xFFFFFFFF
    assert any(
        item["addr"] == addr and
        item["wstrb"] == 0xF and
        item["wdata"] == data
        for item in mem.log
    ), f"expected write of 0x{data:08x} to memory address {addr}"


def assert_directory_access_seen(mem, addr):
    index = addr & 0x7F
    meta_addr = DIR_META_BASE + index
    data_addr = DIR_DATA_BASE + index
    assert any(item["addr"] == meta_addr for item in mem.log)
    assert any(item["addr"] == data_addr for item in mem.log)


async def make_modified(dut, mem, cache, addr):
    await bus_request_and_expect(
        dut,
        mem,
        cache=cache,
        command=CACHE_CMD_BUS_RDX,
        addr=addr,
        data=0,
        expected_command=DIR_CMD_BUS_RDX_ACK,
        expected_data=backing_value(mem, addr),
    )


async def dirty_evict(dut, mem, cache, addr, data):
    mem.clear_log()
    await send_bus_request(dut, mem, cache, CACHE_CMD_EVICT_DIRTY, addr, data)
    await wait_cycles(dut, mem, 80)
    assert_mem_write_seen(mem, addr, data)
    assert_directory_access_seen(mem, addr)


async def clean_evict(dut, mem, cache, addr):
    mem.clear_log()
    await send_bus_request(dut, mem, cache, CACHE_CMD_EVICT_CLEAN, addr, 0)
    await wait_cycles(dut, mem, 80)
    assert_directory_access_seen(mem, addr)


@cocotb.test()
async def test_initialization_clears_reserved_directory_regions(dut):
    mem = await start_test(dut)

    for index in range(128):
        assert mem.read(DIR_META_BASE + index) == 0
        assert mem.read(DIR_DATA_BASE + index) == 0


@cocotb.test()
async def test_cold_bus_rd_from_both_caches(dut):
    mem = await start_test(dut)

    for cache, addr in [(0, 0x10), (1, 0x11)]:
        mem.clear_log()
        await bus_request_and_expect(
            dut,
            mem,
            cache=cache,
            command=CACHE_CMD_BUS_RD,
            addr=addr,
            data=0,
            expected_command=DIR_CMD_BUS_RD_ACK,
            expected_data=0,
        )
        assert_mem_read_seen(mem, addr)
        assert_directory_access_seen(mem, addr)


@cocotb.test()
async def test_dirty_evict_writeback_and_later_readback(dut):
    mem = await start_test(dut)

    addr = 0x20
    data = 0xABCD0020

    await make_modified(dut, mem, cache=0, addr=addr)
    await dirty_evict(dut, mem, cache=0, addr=addr, data=data)

    mem.clear_log()
    await bus_request_and_expect(
        dut,
        mem,
        cache=1,
        command=CACHE_CMD_BUS_RD,
        addr=addr,
        data=0,
        expected_command=DIR_CMD_BUS_RD_ACK,
        expected_data=data,
    )
    assert_mem_read_seen(mem, addr)


@cocotb.test()
async def test_data_patterns_survive_writeback(dut):
    mem = await start_test(dut)

    cases = [
        (0x30, 0x00000000),
        (0x31, 0xFFFFFFFF),
        (0x32, 0xAAAAAAAA),
        (0x33, 0x55555555),
        (0x34, 0xDEADBEEF),
        (0x35, 0x80000001),
    ]

    for index, (addr, data) in enumerate(cases):
        owner = index % 2
        reader = 1 - owner

        await make_modified(dut, mem, cache=owner, addr=addr)
        await dirty_evict(dut, mem, cache=owner, addr=addr, data=data)

        await bus_request_and_expect(
            dut,
            mem,
            cache=reader,
            command=CACHE_CMD_BUS_RD,
            addr=addr,
            data=0,
            expected_command=DIR_CMD_BUS_RD_ACK,
            expected_data=data,
        )


@cocotb.test()
async def test_directory_boundary_lines_zero_to_127(dut):
    mem = await start_test(dut)

    addresses = [0, 1, 2, 3, 4, 7, 8, 15, 16, 31, 32, 63, 64, 65, 126, 127]

    for index, addr in enumerate(addresses):
        cache = index % 2
        mem.clear_log()
        await bus_request_and_expect(
            dut,
            mem,
            cache=cache,
            command=CACHE_CMD_BUS_RD,
            addr=addr,
            data=0,
            expected_command=DIR_CMD_BUS_RD_ACK,
            expected_data=backing_value(mem, addr),
        )
        assert_mem_read_seen(mem, addr)
        assert_directory_access_seen(mem, addr)


@cocotb.test()
async def test_modified_owner_snoop_bus_rd_both_directions(dut):
    mem = await start_test(dut)

    for owner, requester, addr, data in [
        (0, 1, 0x40, 0xFACE0040),
        (1, 0, 0x41, 0xBEEF0041),
    ]:
        await make_modified(dut, mem, cache=owner, addr=addr)

        await send_bus_request(dut, mem, requester, CACHE_CMD_BUS_RD, addr, 0)
        cmd, payload, snoop_addr = await wait_for_dir_packet(dut, mem, owner)
        assert cmd == DIR_CMD_SNOOP_BUS_RD
        assert payload == 0
        assert snoop_addr == addr

        await send_snoop_ack(dut, mem, owner, SNOOP_ACK_BUS_RD, data)
        cmd, payload, ack_addr = await wait_for_dir_packet(dut, mem, requester)
        assert cmd == DIR_CMD_BUS_RD_ACK
        assert payload == data
        assert ack_addr == addr


@cocotb.test()
async def test_modified_owner_snoop_bus_rdx_both_directions(dut):
    mem = await start_test(dut)

    for owner, requester, addr, data in [
        (0, 1, 0x44, 0xCAFE0044),
        (1, 0, 0x45, 0xCAFE0045),
    ]:
        await make_modified(dut, mem, cache=owner, addr=addr)

        await send_bus_request(dut, mem, requester, CACHE_CMD_BUS_RDX, addr, 0)
        cmd, payload, snoop_addr = await wait_for_dir_packet(dut, mem, owner)
        assert cmd == DIR_CMD_SNOOP_BUS_RDX
        assert payload == 0
        assert snoop_addr == addr

        await send_snoop_ack(dut, mem, owner, SNOOP_ACK_BUS_RDX, data)
        cmd, payload, ack_addr = await wait_for_dir_packet(dut, mem, requester)
        assert cmd == DIR_CMD_BUS_RDX_ACK
        assert payload == data
        assert ack_addr == addr


@cocotb.test()
async def test_shared_bus_rdx_and_bus_upgr_invalidate_other_sharer(dut):
    mem = await start_test(dut)

    for command, expected_ack, addr in [
        (CACHE_CMD_BUS_RDX, DIR_CMD_BUS_RDX_ACK, 0x50),
        (CACHE_CMD_BUS_UPGR, DIR_CMD_BUS_UPGR_ACK, 0x51),
    ]:
        await bus_request_and_expect(
            dut, mem, 0, CACHE_CMD_BUS_RD, addr, 0, DIR_CMD_BUS_RD_ACK, 0,
        )
        await bus_request_and_expect(
            dut, mem, 1, CACHE_CMD_BUS_RD, addr, 0, DIR_CMD_BUS_RD_ACK, 0,
        )

        await send_bus_request(dut, mem, 0, command, addr, 0)
        cmd, payload, snoop_addr = await wait_for_dir_packet(dut, mem, 1)
        assert cmd == DIR_CMD_SNOOP_BUS_UPGR
        assert payload == 0
        assert snoop_addr == addr

        await send_snoop_ack(dut, mem, 1, SNOOP_ACK_BUS_UPGR, 0)
        cmd, payload, ack_addr = await wait_for_dir_packet(dut, mem, 0)
        assert cmd == expected_ack
        assert payload == 0
        assert ack_addr == addr


@cocotb.test()
async def test_single_sharer_bus_upgr_does_not_snoop_other_cache(dut):
    mem = await start_test(dut)

    addr = 0x58
    await bus_request_and_expect(
        dut, mem, 0, CACHE_CMD_BUS_RD, addr, 0, DIR_CMD_BUS_RD_ACK, 0,
    )
    await bus_request_and_expect(
        dut, mem, 0, CACHE_CMD_BUS_UPGR, addr, 0, DIR_CMD_BUS_UPGR_ACK, 0,
    )
    await expect_no_dir_packet(dut, mem, 1)


@cocotb.test()
async def test_clean_evict_last_sharer_and_one_of_two_sharers(dut):
    mem = await start_test(dut)

    last_addr = 0x60
    await bus_request_and_expect(
        dut, mem, 0, CACHE_CMD_BUS_RD, last_addr, 0, DIR_CMD_BUS_RD_ACK, 0,
    )
    await clean_evict(dut, mem, 0, last_addr)

    mem.clear_log()
    await bus_request_and_expect(
        dut, mem, 1, CACHE_CMD_BUS_RD, last_addr, 0, DIR_CMD_BUS_RD_ACK, 0,
    )
    assert_mem_read_seen(mem, last_addr)

    shared_addr = 0x61
    await bus_request_and_expect(
        dut, mem, 0, CACHE_CMD_BUS_RD, shared_addr, 0, DIR_CMD_BUS_RD_ACK, 0,
    )
    await bus_request_and_expect(
        dut, mem, 1, CACHE_CMD_BUS_RD, shared_addr, 0, DIR_CMD_BUS_RD_ACK, 0,
    )
    await clean_evict(dut, mem, 0, shared_addr)

    await bus_request_and_expect(
        dut, mem, 1, CACHE_CMD_BUS_UPGR, shared_addr, 0, DIR_CMD_BUS_UPGR_ACK, 0,
    )
    await expect_no_dir_packet(dut, mem, 0)


@cocotb.test()
async def test_repeated_same_line_state_transition_stress(dut):
    mem = await start_test(dut)

    addr = 0x70
    data_a = 0xAAAA0070
    data_b = 0xBBBB0070

    await bus_request_and_expect(
        dut, mem, 0, CACHE_CMD_BUS_RD, addr, 0, DIR_CMD_BUS_RD_ACK, 0,
    )
    await bus_request_and_expect(
        dut, mem, 1, CACHE_CMD_BUS_RD, addr, 0, DIR_CMD_BUS_RD_ACK, 0,
    )

    await send_bus_request(dut, mem, 0, CACHE_CMD_BUS_UPGR, addr, 0)
    cmd, _, _ = await wait_for_dir_packet(dut, mem, 1)
    assert cmd == DIR_CMD_SNOOP_BUS_UPGR
    await send_snoop_ack(dut, mem, 1, SNOOP_ACK_BUS_UPGR, 0)
    cmd, _, _ = await wait_for_dir_packet(dut, mem, 0)
    assert cmd == DIR_CMD_BUS_UPGR_ACK

    await send_bus_request(dut, mem, 1, CACHE_CMD_BUS_RD, addr, 0)
    cmd, _, _ = await wait_for_dir_packet(dut, mem, 0)
    assert cmd == DIR_CMD_SNOOP_BUS_RD
    await send_snoop_ack(dut, mem, 0, SNOOP_ACK_BUS_RD, data_a)
    cmd, payload, _ = await wait_for_dir_packet(dut, mem, 1)
    assert cmd == DIR_CMD_BUS_RD_ACK
    assert payload == data_a

    await send_bus_request(dut, mem, 1, CACHE_CMD_BUS_UPGR, addr, 0)
    cmd, _, _ = await wait_for_dir_packet(dut, mem, 0)
    assert cmd == DIR_CMD_SNOOP_BUS_UPGR
    await send_snoop_ack(dut, mem, 0, SNOOP_ACK_BUS_UPGR, 0)
    cmd, _, _ = await wait_for_dir_packet(dut, mem, 1)
    assert cmd == DIR_CMD_BUS_UPGR_ACK

    await dirty_evict(dut, mem, 1, addr, data_b)
    await bus_request_and_expect(
        dut, mem, 0, CACHE_CMD_BUS_RD, addr, 0, DIR_CMD_BUS_RD_ACK, data_b,
    )


@cocotb.test()
async def test_simultaneous_requests_are_both_served_round_robin(dut):
    mem = await start_test(dut)

    dut.c0_bus_valid_i.value = 1
    dut.c0_bus_addr_i.value = 0x74
    dut.c0_bus_cache_cmd_i.value = CACHE_CMD_BUS_RD
    dut.c1_bus_valid_i.value = 1
    dut.c1_bus_addr_i.value = 0x75
    dut.c1_bus_cache_cmd_i.value = CACHE_CMD_BUS_RD

    await mem.tick(dut)

    dut.c0_bus_valid_i.value = 0
    dut.c0_bus_cache_cmd_i.value = CACHE_CMD_NONE

    cmd, payload, addr = await wait_for_dir_packet(dut, mem, 0)
    assert cmd == DIR_CMD_BUS_RD_ACK
    assert payload == 0
    assert addr == 0x74

    for _ in range(TIMEOUT_CYCLES):
        await Timer(1, unit="ns")
        if int(dut.c1_bus_ready_o.value):
            await mem.tick(dut)
            dut.c1_bus_valid_i.value = 0
            dut.c1_bus_cache_cmd_i.value = CACHE_CMD_NONE
            break
        await mem.tick(dut)
    else:
        assert False, "cache 1 request was not accepted after cache 0"

    cmd, payload, addr = await wait_for_dir_packet(dut, mem, 1)
    assert cmd == DIR_CMD_BUS_RD_ACK
    assert payload == 0
    assert addr == 0x75


@cocotb.test()
async def test_output_ready_backpressure_holds_ack_packet_stable(dut):
    mem = await start_test(dut)

    addr = 0x78
    await send_bus_request(dut, mem, 0, CACHE_CMD_BUS_RD, addr, 0)
    cmd, payload, got_addr = await wait_for_dir_packet(
        dut, mem, 0, hold_ready_low=6,
    )
    assert cmd == DIR_CMD_BUS_RD_ACK
    assert payload == 0
    assert got_addr == addr


@cocotb.test()
async def test_memory_ready_backpressure_still_completes_request(dut):
    mem = await start_test(dut, ready_pattern=[1, 0, 0, 1, 1, 0, 1])

    addr = 0x7A
    await bus_request_and_expect(
        dut, mem, 0, CACHE_CMD_BUS_RD, addr, 0, DIR_CMD_BUS_RD_ACK, 0,
    )
    assert_directory_access_seen(mem, addr)


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
        data = rng.getrandbits(32)

        await make_modified(dut, mem, owner, addr)
        await dirty_evict(dut, mem, owner, addr, data)
        await bus_request_and_expect(
            dut,
            mem,
            reader,
            CACHE_CMD_BUS_RD,
            addr,
            0,
            DIR_CMD_BUS_RD_ACK,
            data,
        )


@cocotb.test(skip=True)
async def test_out_of_range_addresses_are_not_part_of_this_controller_contract(dut):
    """Documentation test.

    This controller intentionally tracks only 128 coherent line IDs, 0 through
    127. Addresses above that range should be routed through the normal system
    memory path, not this directory controller path.
    """
    assert False


def find_source_file():
    env_source = os.getenv("DIRECTORY_CONTROLLER_RTL")
    if env_source:
        return Path(env_source).resolve()

    here = Path(__file__).resolve()
    candidates = [
        here.parent / "directory_controller_only.sv",
        here.parent / "directory_controller.sv",
        here.parent.parent / "src" / "directory_controller.sv",
        here.parent.parent / "directory_controller_only.sv",
    ]

    for path in candidates:
        if path.exists():
            return path

    raise FileNotFoundError(
        "Could not find directory_controller RTL. Set DIRECTORY_CONTROLLER_RTL "
        "or place directory_controller_only.sv next to this testbench."
    )


def run_tests():
    source = find_source_file()

    if SIM == "icarus":
        build_args = ["-g2012"]
    elif SIM == "verilator":
        build_args = ["--timing", "--trace", "--trace-fst"]
    else:
        build_args = []

    runner = get_runner(SIM)
    runner.build(
        sources=[source],
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

