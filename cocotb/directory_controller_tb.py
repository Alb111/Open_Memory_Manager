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
NUM_DIRECTORY_LINES = 128

INIT_TIMEOUT_CYCLES = 1500
TIMEOUT_CYCLES = 700


class MetadataRamModel:
    """128 by 6 metadata RAM model for controller-only testing.

    The model follows the controller's two-phase valid/ready pattern. Accepted
    reads update meta_ram_rdata_i after the clock edge, so the data is stable
    for the following response phase.
    """

    def __init__(self, ready_pattern=None):
        self.mem = [0 for _ in range(NUM_DIRECTORY_LINES)]
        self.log = []
        self.cycle = 0
        self.ready_pattern = ready_pattern or [1]

    def clear_log(self):
        self.log.clear()

    def read_index(self, index):
        return self.mem[index & 0x7F] & 0x3F

    def read_addr(self, addr):
        return self.read_index(addr & 0x7F)

    def write(self, index, data):
        self.mem[index & 0x7F] = data & 0x3F

    async def tick(self, dut):
        ready = self.ready_pattern[self.cycle % len(self.ready_pattern)]
        dut.meta_ram_ready_i.value = ready

        await Timer(1, unit="ns")

        valid = int(dut.meta_ram_valid_o.value)
        addr = int(dut.meta_ram_addr_o.value) & 0x7F
        wdata = int(dut.meta_ram_wdata_o.value) & 0x3F
        wstrb = int(dut.meta_ram_wstrb_o.value) & 0x1
        rdata = self.read_index(addr)

        await RisingEdge(dut.clk_i)

        if valid and ready:
            if wstrb:
                self.write(addr, wdata)
                rdata = self.read_index(addr)

            self.log.append({
                "addr": addr,
                "wdata": wdata,
                "wstrb": wstrb,
                "rdata": rdata,
            })
            dut.meta_ram_rdata_i.value = rdata

        self.cycle += 1


async def wait_cycles(dut, ram, cycles):
    for _ in range(cycles):
        await ram.tick(dut)


def metadata_fields(word):
    word &= 0x3F
    return {
        "state": word & 0x3,
        "sharers": (word >> 2) & 0x3,
        "owner": (word >> 4) & 0x1,
        "valid": (word >> 5) & 0x1,
    }


def metadata_matches(word, state, sharers, owner, valid=None):
    fields = metadata_fields(word)

    if fields["state"] != state:
        return False
    if fields["sharers"] != sharers:
        return False
    if fields["owner"] != owner:
        return False
    if valid is not None and fields["valid"] != valid:
        return False

    return True


def metadata_string(word):
    fields = metadata_fields(word)
    return (
        f"0b{word & 0x3F:06b} "
        f"(valid={fields['valid']}, owner={fields['owner']}, "
        f"sharers=0b{fields['sharers']:02b}, state=0b{fields['state']:02b})"
    )


def assert_metadata_fields(ram, addr, state, sharers, owner, valid=None):
    index = addr & 0x7F
    word = ram.read_index(index)

    assert metadata_matches(word, state, sharers, owner, valid), (
        f"metadata[{index}] = {metadata_string(word)}, expected "
        f"state=0b{state:02b}, sharers=0b{sharers:02b}, owner={owner}, "
        f"valid={valid if valid is not None else 'ignored'}"
    )


async def wait_for_metadata_fields(
    dut,
    ram,
    addr,
    state,
    sharers,
    owner,
    valid=None,
    timeout_cycles=TIMEOUT_CYCLES,
):
    for _ in range(timeout_cycles):
        if metadata_matches(ram.read_addr(addr), state, sharers, owner, valid):
            return
        await ram.tick(dut)

    index = addr & 0x7F
    word = ram.read_index(index)
    assert False, (
        f"metadata[{index}] did not reach expected value. Got "
        f"{metadata_string(word)}, expected state=0b{state:02b}, "
        f"sharers=0b{sharers:02b}, owner={owner}, "
        f"valid={valid if valid is not None else 'ignored'}"
    )


def sharer_bit(cache):
    return 0b01 if cache == 0 else 0b10


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

    dut.meta_ram_rdata_i.value = 0
    dut.meta_ram_ready_i.value = 1


async def wait_for_init_done(dut, ram):
    for _ in range(INIT_TIMEOUT_CYCLES):
        await Timer(1, unit="ns")
        if int(dut.dir_state_invalidated_o.value):
            return
        await ram.tick(dut)

    assert False, "directory metadata initialization did not complete"


async def reset_dut(dut, ram):
    set_input_defaults(dut)
    dut.rst_ni.value = 0
    await wait_cycles(dut, ram, 5)

    dut.rst_ni.value = 1
    await wait_for_init_done(dut, ram)

    for index in range(NUM_DIRECTORY_LINES):
        assert ram.read_index(index) == 0, (
            f"metadata[{index}] was not invalidated by reset"
        )

    ram.clear_log()


async def start_test(dut, ready_pattern=None):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())

    ram = MetadataRamModel(ready_pattern=ready_pattern)
    await reset_dut(dut, ram)
    return ram


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


async def send_bus_request(dut, ram, cache, command, addr, data=0):
    sig = cache_signals(dut, cache)

    sig["bus_valid"].value = 1
    sig["bus_addr"].value = addr
    sig["bus_wdata"].value = data
    sig["bus_cmd"].value = command

    for _ in range(TIMEOUT_CYCLES):
        await Timer(1, unit="ns")
        if int(sig["bus_ready"].value):
            await ram.tick(dut)
            sig["bus_valid"].value = 0
            sig["bus_addr"].value = 0
            sig["bus_wdata"].value = 0
            sig["bus_cmd"].value = CACHE_CMD_NONE
            return
        await ram.tick(dut)

    assert False, f"cache {cache} bus request was not accepted"


async def send_snoop_ack(dut, ram, cache, command, data=0):
    sig = cache_signals(dut, cache)

    sig["snoop_valid"].value = 1
    sig["snoop_data"].value = data
    sig["snoop_cmd"].value = command

    for _ in range(TIMEOUT_CYCLES):
        await Timer(1, unit="ns")
        if int(sig["snoop_ready"].value):
            await ram.tick(dut)
            sig["snoop_valid"].value = 0
            sig["snoop_data"].value = 0
            sig["snoop_cmd"].value = SNOOP_ACK_NONE
            return
        await ram.tick(dut)

    assert False, f"cache {cache} snoop ack was not accepted"


async def send_dirty_flush_during_snoop(dut, ram, cache, addr, data):
    sig = cache_signals(dut, cache)

    sig["bus_valid"].value = 1
    sig["bus_addr"].value = addr
    sig["bus_wdata"].value = data
    sig["bus_cmd"].value = CACHE_CMD_EVICT_DIRTY

    for _ in range(TIMEOUT_CYCLES):
        await Timer(1, unit="ns")
        if int(sig["bus_ready"].value):
            await ram.tick(dut)
            sig["bus_valid"].value = 0
            sig["bus_addr"].value = 0
            sig["bus_wdata"].value = 0
            sig["bus_cmd"].value = CACHE_CMD_NONE
            return
        await ram.tick(dut)

    assert False, f"cache {cache} dirty flush was not accepted during snoop"


async def wait_for_dir_packet(dut, ram, cache, hold_ready_low=0):
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
                await ram.tick(dut)
                assert int(sig["dir_valid"].value) == 1
                assert int(sig["dir_cmd"].value) == cmd
                assert int(sig["dir_data"].value) & 0xFFFFFFFF == data
                assert int(sig["dir_addr"].value) & 0xFFFFFFFF == addr

            sig["dir_ready"].value = 1
            await ram.tick(dut)
            return cmd, data, addr

        await ram.tick(dut)

    assert False, f"cache {cache} did not receive a directory packet"


async def expect_no_dir_packet(dut, ram, cache, cycles=30):
    sig = cache_signals(dut, cache)

    for _ in range(cycles):
        await Timer(1, unit="ns")
        assert int(sig["dir_valid"].value) == 0
        await ram.tick(dut)


async def bus_request_and_expect(
    dut,
    ram,
    cache,
    command,
    addr,
    data,
    expected_command,
    expected_data=0,
):
    await send_bus_request(dut, ram, cache, command, addr, data)
    got_cmd, got_data, got_addr = await wait_for_dir_packet(dut, ram, cache)

    assert got_cmd == expected_command, (
        f"got cmd {got_cmd:06b}, expected {expected_command:06b}"
    )
    assert got_data == expected_data & 0xFFFFFFFF, (
        f"got data 0x{got_data:08x}, expected 0x{expected_data:08x}"
    )
    assert got_addr == addr & 0xFFFFFFFF


async def make_shared(dut, ram, cache, addr):
    await bus_request_and_expect(
        dut,
        ram,
        cache=cache,
        command=CACHE_CMD_BUS_RD,
        addr=addr,
        data=0,
        expected_command=DIR_CMD_BUS_RD_ACK,
        expected_data=0,
    )

    await wait_for_metadata_fields(
        dut,
        ram,
        addr,
        LINE_SHARED,
        sharer_bit(cache),
        owner=0,
    )


async def make_modified(dut, ram, cache, addr):
    await bus_request_and_expect(
        dut,
        ram,
        cache=cache,
        command=CACHE_CMD_BUS_RDX,
        addr=addr,
        data=0,
        expected_command=DIR_CMD_BUS_RDX_ACK,
        expected_data=0,
    )

    await wait_for_metadata_fields(
        dut,
        ram,
        addr,
        LINE_MODIFIED,
        sharers=0b00,
        owner=cache,
    )


async def dirty_evict(dut, ram, cache, addr, data):
    await send_bus_request(dut, ram, cache, CACHE_CMD_EVICT_DIRTY, addr, data)
    await wait_for_metadata_fields(
        dut,
        ram,
        addr,
        LINE_INVALID,
        sharers=0b00,
        owner=0,
        valid=0,
    )


async def clean_evict(dut, ram, cache, addr, remaining_sharers):
    await send_bus_request(dut, ram, cache, CACHE_CMD_EVICT_CLEAN, addr, 0)

    if remaining_sharers == 0:
        await wait_for_metadata_fields(
            dut,
            ram,
            addr,
            LINE_INVALID,
            sharers=0b00,
            owner=0,
            valid=0,
        )
    else:
        await wait_for_metadata_fields(
            dut,
            ram,
            addr,
            LINE_SHARED,
            sharers=remaining_sharers,
            owner=0,
        )


@cocotb.test()
async def test_reset_invalidates_all_metadata_and_blocks_requests_until_done(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())

    ram = MetadataRamModel()
    set_input_defaults(dut)

    dut.rst_ni.value = 0
    await wait_cycles(dut, ram, 5)

    dut.c0_bus_valid_i.value = 1
    dut.c0_bus_addr_i.value = 0x10
    dut.c0_bus_cache_cmd_i.value = CACHE_CMD_BUS_RD

    dut.rst_ni.value = 1

    for _ in range(20):
        await Timer(1, unit="ns")
        assert int(dut.dir_state_invalidated_o.value) == 0
        assert int(dut.c0_bus_ready_o.value) == 0
        await ram.tick(dut)

    await wait_for_init_done(dut, ram)
    assert int(dut.dir_state_invalidated_o.value) == 1

    for index in range(NUM_DIRECTORY_LINES):
        assert ram.read_index(index) == 0

    for _ in range(TIMEOUT_CYCLES):
        await Timer(1, unit="ns")
        if int(dut.c0_bus_ready_o.value):
            await ram.tick(dut)
            dut.c0_bus_valid_i.value = 0
            dut.c0_bus_cache_cmd_i.value = CACHE_CMD_NONE
            break
        await ram.tick(dut)
    else:
        assert False, "request was not accepted after invalidation completed"


@cocotb.test()
async def test_cold_bus_rd_from_both_caches_updates_sharer_metadata(dut):
    ram = await start_test(dut)

    for cache, addr in [(0, 0x10), (1, 0x11)]:
        await make_shared(dut, ram, cache, addr)
        assert_metadata_fields(
            ram,
            addr,
            LINE_SHARED,
            sharer_bit(cache),
            owner=0,
        )


@cocotb.test()
async def test_cold_bus_rdx_from_both_caches_updates_modified_owner(dut):
    ram = await start_test(dut)

    for cache, addr in [(0, 0x20), (1, 0x21)]:
        await make_modified(dut, ram, cache, addr)
        assert_metadata_fields(
            ram,
            addr,
            LINE_MODIFIED,
            sharers=0b00,
            owner=cache,
        )


@cocotb.test()
async def test_read_and_exclusive_acks_return_zero_data(dut):
    ram = await start_test(dut)

    for cache, command, expected_cmd, addr in [
        (0, CACHE_CMD_BUS_RD, DIR_CMD_BUS_RD_ACK, 0x30),
        (1, CACHE_CMD_BUS_RD, DIR_CMD_BUS_RD_ACK, 0x31),
        (0, CACHE_CMD_BUS_RDX, DIR_CMD_BUS_RDX_ACK, 0x32),
        (1, CACHE_CMD_BUS_RDX, DIR_CMD_BUS_RDX_ACK, 0x33),
    ]:
        await bus_request_and_expect(
            dut,
            ram,
            cache,
            command,
            addr,
            data=0xCAFE0000 | addr,
            expected_command=expected_cmd,
            expected_data=0,
        )


@cocotb.test()
async def test_directory_boundary_lines_zero_to_127(dut):
    ram = await start_test(dut)

    addresses = [0, 1, 2, 3, 4, 7, 8, 15, 16, 31, 32, 63, 64, 65, 126, 127]

    for index, addr in enumerate(addresses):
        cache = index % 2
        await make_shared(dut, ram, cache, addr)
        assert_metadata_fields(
            ram,
            addr,
            LINE_SHARED,
            sharer_bit(cache),
            owner=0,
        )


@cocotb.test()
async def test_modified_owner_snoop_bus_rd_both_directions(dut):
    ram = await start_test(dut)

    for owner, requester, addr, snoop_data in [
        (0, 1, 0x40, 0xFACE0040),
        (1, 0, 0x41, 0xBEEF0041),
    ]:
        await make_modified(dut, ram, cache=owner, addr=addr)

        await send_bus_request(dut, ram, requester, CACHE_CMD_BUS_RD, addr, 0)
        cmd, payload, snoop_addr = await wait_for_dir_packet(dut, ram, owner)
        assert cmd == DIR_CMD_SNOOP_BUS_RD
        assert payload == 0
        assert snoop_addr == addr

        await send_snoop_ack(dut, ram, owner, SNOOP_ACK_BUS_RD, snoop_data)
        cmd, payload, ack_addr = await wait_for_dir_packet(dut, ram, requester)
        assert cmd == DIR_CMD_BUS_RD_ACK
        assert payload == 0
        assert ack_addr == addr

        await wait_for_metadata_fields(
            dut,
            ram,
            addr,
            LINE_SHARED,
            sharers=0b11,
            owner=0,
        )


@cocotb.test()
async def test_modified_owner_snoop_bus_rdx_both_directions(dut):
    ram = await start_test(dut)

    for owner, requester, addr, snoop_data in [
        (0, 1, 0x44, 0xCAFE0044),
        (1, 0, 0x45, 0xCAFE0045),
    ]:
        await make_modified(dut, ram, cache=owner, addr=addr)

        await send_bus_request(dut, ram, requester, CACHE_CMD_BUS_RDX, addr, 0)
        cmd, payload, snoop_addr = await wait_for_dir_packet(dut, ram, owner)
        assert cmd == DIR_CMD_SNOOP_BUS_RDX
        assert payload == 0
        assert snoop_addr == addr

        await send_snoop_ack(dut, ram, owner, SNOOP_ACK_BUS_RDX, snoop_data)
        cmd, payload, ack_addr = await wait_for_dir_packet(dut, ram, requester)
        assert cmd == DIR_CMD_BUS_RDX_ACK
        assert payload == 0
        assert ack_addr == addr

        await wait_for_metadata_fields(
            dut,
            ram,
            addr,
            LINE_MODIFIED,
            sharers=0b00,
            owner=requester,
        )


@cocotb.test()
async def test_shared_bus_rdx_and_bus_upgr_invalidate_other_sharer(dut):
    ram = await start_test(dut)

    for command, expected_ack, addr in [
        (CACHE_CMD_BUS_RDX, DIR_CMD_BUS_RDX_ACK, 0x50),
        (CACHE_CMD_BUS_UPGR, DIR_CMD_BUS_UPGR_ACK, 0x51),
    ]:
        await make_shared(dut, ram, 0, addr)
        await bus_request_and_expect(
            dut,
            ram,
            cache=1,
            command=CACHE_CMD_BUS_RD,
            addr=addr,
            data=0,
            expected_command=DIR_CMD_BUS_RD_ACK,
            expected_data=0,
        )
        await wait_for_metadata_fields(
            dut,
            ram,
            addr,
            LINE_SHARED,
            sharers=0b11,
            owner=0,
        )

        await send_bus_request(dut, ram, 0, command, addr, 0)
        cmd, payload, snoop_addr = await wait_for_dir_packet(dut, ram, 1)
        assert cmd == DIR_CMD_SNOOP_BUS_UPGR
        assert payload == 0
        assert snoop_addr == addr

        await send_snoop_ack(dut, ram, 1, SNOOP_ACK_BUS_UPGR, 0)
        cmd, payload, ack_addr = await wait_for_dir_packet(dut, ram, 0)
        assert cmd == expected_ack
        assert payload == 0
        assert ack_addr == addr

        await wait_for_metadata_fields(
            dut,
            ram,
            addr,
            LINE_MODIFIED,
            sharers=0b00,
            owner=0,
        )


@cocotb.test()
async def test_single_sharer_bus_upgr_does_not_snoop_other_cache(dut):
    ram = await start_test(dut)

    addr = 0x58
    await make_shared(dut, ram, 0, addr)

    await bus_request_and_expect(
        dut,
        ram,
        cache=0,
        command=CACHE_CMD_BUS_UPGR,
        addr=addr,
        data=0,
        expected_command=DIR_CMD_BUS_UPGR_ACK,
        expected_data=0,
    )

    await wait_for_metadata_fields(
        dut,
        ram,
        addr,
        LINE_MODIFIED,
        sharers=0b00,
        owner=0,
    )

    await expect_no_dir_packet(dut, ram, 1)


@cocotb.test()
async def test_clean_evict_last_sharer_and_one_of_two_sharers(dut):
    ram = await start_test(dut)

    last_addr = 0x60
    await make_shared(dut, ram, 0, last_addr)
    await clean_evict(dut, ram, 0, last_addr, remaining_sharers=0b00)
    await expect_no_dir_packet(dut, ram, 0)

    await make_shared(dut, ram, 1, last_addr)
    assert_metadata_fields(
        ram,
        last_addr,
        LINE_SHARED,
        sharer_bit(1),
        owner=0,
    )

    shared_addr = 0x61
    await make_shared(dut, ram, 0, shared_addr)
    await bus_request_and_expect(
        dut,
        ram,
        cache=1,
        command=CACHE_CMD_BUS_RD,
        addr=shared_addr,
        data=0,
        expected_command=DIR_CMD_BUS_RD_ACK,
        expected_data=0,
    )
    await wait_for_metadata_fields(
        dut,
        ram,
        shared_addr,
        LINE_SHARED,
        sharers=0b11,
        owner=0,
    )

    await clean_evict(dut, ram, 0, shared_addr, remaining_sharers=0b10)

    await bus_request_and_expect(
        dut,
        ram,
        cache=1,
        command=CACHE_CMD_BUS_UPGR,
        addr=shared_addr,
        data=0,
        expected_command=DIR_CMD_BUS_UPGR_ACK,
        expected_data=0,
    )

    await expect_no_dir_packet(dut, ram, 0)


@cocotb.test()
async def test_dirty_evict_invalidates_metadata_and_sends_no_ack(dut):
    ram = await start_test(dut)

    for cache, addr, data in [
        (0, 0x66, 0xAAAA0066),
        (1, 0x67, 0xBBBB0067),
    ]:
        await make_modified(dut, ram, cache, addr)
        await dirty_evict(dut, ram, cache, addr, data)
        await expect_no_dir_packet(dut, ram, cache)
        assert_metadata_fields(
            ram,
            addr,
            LINE_INVALID,
            sharers=0b00,
            owner=0,
            valid=0,
        )


@cocotb.test()
async def test_dirty_flush_during_wait_snoop_is_accepted_and_discarded(dut):
    ram = await start_test(dut)

    addr = 0x68
    await make_modified(dut, ram, cache=0, addr=addr)

    await send_bus_request(dut, ram, 1, CACHE_CMD_BUS_RD, addr, 0)
    cmd, payload, snoop_addr = await wait_for_dir_packet(dut, ram, 0)
    assert cmd == DIR_CMD_SNOOP_BUS_RD
    assert payload == 0
    assert snoop_addr == addr

    await send_dirty_flush_during_snoop(dut, ram, 0, addr, 0xDEAD0068)

    await send_snoop_ack(dut, ram, 0, SNOOP_ACK_BUS_RD, 0xFEED0068)
    cmd, payload, ack_addr = await wait_for_dir_packet(dut, ram, 1)
    assert cmd == DIR_CMD_BUS_RD_ACK
    assert payload == 0
    assert ack_addr == addr

    await wait_for_metadata_fields(
        dut,
        ram,
        addr,
        LINE_SHARED,
        sharers=0b11,
        owner=0,
    )


@cocotb.test()
async def test_repeated_same_line_state_transition_stress(dut):
    ram = await start_test(dut)

    addr = 0x70

    await make_shared(dut, ram, 0, addr)
    await bus_request_and_expect(
        dut,
        ram,
        cache=1,
        command=CACHE_CMD_BUS_RD,
        addr=addr,
        data=0,
        expected_command=DIR_CMD_BUS_RD_ACK,
        expected_data=0,
    )
    await wait_for_metadata_fields(
        dut,
        ram,
        addr,
        LINE_SHARED,
        sharers=0b11,
        owner=0,
    )

    await send_bus_request(dut, ram, 0, CACHE_CMD_BUS_UPGR, addr, 0)
    cmd, payload, snoop_addr = await wait_for_dir_packet(dut, ram, 1)
    assert cmd == DIR_CMD_SNOOP_BUS_UPGR
    assert payload == 0
    assert snoop_addr == addr
    await send_snoop_ack(dut, ram, 1, SNOOP_ACK_BUS_UPGR, 0)

    cmd, payload, ack_addr = await wait_for_dir_packet(dut, ram, 0)
    assert cmd == DIR_CMD_BUS_UPGR_ACK
    assert payload == 0
    assert ack_addr == addr
    await wait_for_metadata_fields(
        dut,
        ram,
        addr,
        LINE_MODIFIED,
        sharers=0b00,
        owner=0,
    )

    await send_bus_request(dut, ram, 1, CACHE_CMD_BUS_RD, addr, 0)
    cmd, payload, snoop_addr = await wait_for_dir_packet(dut, ram, 0)
    assert cmd == DIR_CMD_SNOOP_BUS_RD
    assert payload == 0
    assert snoop_addr == addr
    await send_snoop_ack(dut, ram, 0, SNOOP_ACK_BUS_RD, 0xAAAA0070)

    cmd, payload, ack_addr = await wait_for_dir_packet(dut, ram, 1)
    assert cmd == DIR_CMD_BUS_RD_ACK
    assert payload == 0
    assert ack_addr == addr
    await wait_for_metadata_fields(
        dut,
        ram,
        addr,
        LINE_SHARED,
        sharers=0b11,
        owner=0,
    )

    await send_bus_request(dut, ram, 1, CACHE_CMD_BUS_UPGR, addr, 0)
    cmd, payload, snoop_addr = await wait_for_dir_packet(dut, ram, 0)
    assert cmd == DIR_CMD_SNOOP_BUS_UPGR
    assert payload == 0
    assert snoop_addr == addr
    await send_snoop_ack(dut, ram, 0, SNOOP_ACK_BUS_UPGR, 0)

    cmd, payload, ack_addr = await wait_for_dir_packet(dut, ram, 1)
    assert cmd == DIR_CMD_BUS_UPGR_ACK
    assert payload == 0
    assert ack_addr == addr
    await wait_for_metadata_fields(
        dut,
        ram,
        addr,
        LINE_MODIFIED,
        sharers=0b00,
        owner=1,
    )

    await dirty_evict(dut, ram, 1, addr, 0xBBBB0070)
    await make_shared(dut, ram, 0, addr)


@cocotb.test()
async def test_simultaneous_requests_are_both_served_by_wrr_arbiter(dut):
    ram = await start_test(dut)

    pending = {
        0: {"addr": 0x74, "accepted": False},
        1: {"addr": 0x75, "accepted": False},
    }

    dut.c0_bus_valid_i.value = 1
    dut.c0_bus_addr_i.value = pending[0]["addr"]
    dut.c0_bus_cache_cmd_i.value = CACHE_CMD_BUS_RD
    dut.c1_bus_valid_i.value = 1
    dut.c1_bus_addr_i.value = pending[1]["addr"]
    dut.c1_bus_cache_cmd_i.value = CACHE_CMD_BUS_RD

    accepted_order = []

    while len(accepted_order) < 2:
        await Timer(1, unit="ns")

        if int(dut.c0_bus_ready_o.value) and not pending[0]["accepted"]:
            pending[0]["accepted"] = True
            accepted_order.append(0)
            await ram.tick(dut)
            dut.c0_bus_valid_i.value = 0
            dut.c0_bus_cache_cmd_i.value = CACHE_CMD_NONE
            cmd, payload, addr = await wait_for_dir_packet(dut, ram, 0)
            assert cmd == DIR_CMD_BUS_RD_ACK
            assert payload == 0
            assert addr == pending[0]["addr"]
            continue

        if int(dut.c1_bus_ready_o.value) and not pending[1]["accepted"]:
            pending[1]["accepted"] = True
            accepted_order.append(1)
            await ram.tick(dut)
            dut.c1_bus_valid_i.value = 0
            dut.c1_bus_cache_cmd_i.value = CACHE_CMD_NONE
            cmd, payload, addr = await wait_for_dir_packet(dut, ram, 1)
            assert cmd == DIR_CMD_BUS_RD_ACK
            assert payload == 0
            assert addr == pending[1]["addr"]
            continue

        await ram.tick(dut)

    assert set(accepted_order) == {0, 1}

    await wait_for_metadata_fields(
        dut,
        ram,
        pending[0]["addr"],
        LINE_SHARED,
        sharer_bit(0),
        owner=0,
    )
    await wait_for_metadata_fields(
        dut,
        ram,
        pending[1]["addr"],
        LINE_SHARED,
        sharer_bit(1),
        owner=0,
    )


@cocotb.test()
async def test_output_ready_backpressure_holds_ack_packet_stable(dut):
    ram = await start_test(dut)

    addr = 0x78
    await send_bus_request(dut, ram, 0, CACHE_CMD_BUS_RD, addr, 0)
    cmd, payload, got_addr = await wait_for_dir_packet(
        dut,
        ram,
        0,
        hold_ready_low=6,
    )

    assert cmd == DIR_CMD_BUS_RD_ACK
    assert payload == 0
    assert got_addr == addr


@cocotb.test()
async def test_meta_ram_ready_backpressure_still_completes_request(dut):
    ram = await start_test(dut, ready_pattern=[1, 0, 0, 1, 1, 0, 1])

    addr = 0x7A
    await bus_request_and_expect(
        dut,
        ram,
        cache=0,
        command=CACHE_CMD_BUS_RD,
        addr=addr,
        data=0,
        expected_command=DIR_CMD_BUS_RD_ACK,
        expected_data=0,
    )
    await wait_for_metadata_fields(
        dut,
        ram,
        addr,
        LINE_SHARED,
        sharer_bit(0),
        owner=0,
        timeout_cycles=TIMEOUT_CYCLES * 2,
    )


@cocotb.test()
async def test_seeded_random_metadata_state_smoke(dut):
    ram = await start_test(dut)
    rng = random.Random(187)
    used = set()

    for _ in range(16):
        while True:
            addr = rng.randint(DIRECTORY_LINE_MIN, DIRECTORY_LINE_MAX)
            if addr not in used:
                used.add(addr)
                break

        owner = rng.randint(0, 1)
        other = 1 - owner

        await make_modified(dut, ram, owner, addr)

        await send_bus_request(dut, ram, other, CACHE_CMD_BUS_RD, addr, 0)
        cmd, payload, snoop_addr = await wait_for_dir_packet(dut, ram, owner)
        assert cmd == DIR_CMD_SNOOP_BUS_RD
        assert payload == 0
        assert snoop_addr == addr

        await send_snoop_ack(
            dut,
            ram,
            owner,
            SNOOP_ACK_BUS_RD,
            rng.getrandbits(32),
        )
        cmd, payload, ack_addr = await wait_for_dir_packet(dut, ram, other)
        assert cmd == DIR_CMD_BUS_RD_ACK
        assert payload == 0
        assert ack_addr == addr

        await wait_for_metadata_fields(
            dut,
            ram,
            addr,
            LINE_SHARED,
            sharers=0b11,
            owner=0,
        )

        await clean_evict(
            dut,
            ram,
            owner,
            addr,
            remaining_sharers=sharer_bit(other),
        )

        await bus_request_and_expect(
            dut,
            ram,
            cache=other,
            command=CACHE_CMD_BUS_UPGR,
            addr=addr,
            data=0,
            expected_command=DIR_CMD_BUS_UPGR_ACK,
            expected_data=0,
        )

        await wait_for_metadata_fields(
            dut,
            ram,
            addr,
            LINE_MODIFIED,
            sharers=0b00,
            owner=other,
        )

        await dirty_evict(dut, ram, other, addr, rng.getrandbits(32))


@cocotb.test(skip=True)
async def test_out_of_range_addresses_alias_by_low_7_bits_in_this_controller(dut):
    """Documentation test.

    The directory controller owns 128 coherent line indices. The metadata RAM
    address is request_addr[6:0], so addresses outside 0 through 127 alias by
    design unless the system routes them elsewhere before reaching this block.
    """
    assert False


def find_source_file():
    env_source = os.getenv("DIRECTORY_CONTROLLER_RTL")
    if env_source:
        return Path(env_source).resolve()

    here = Path(__file__).resolve()
    candidates = [
        here.parent / "directory_controller_metadata_only.sv",
        here.parent / "directory_controller_only.sv",
        here.parent / "directory_controller.sv",
        here.parent.parent / "src" / "directory_controller.sv",
        here.parent.parent / "src" / "directory_controller_metadata_only.sv",
        here.parent.parent / "directory_controller_only.sv",
    ]

    for path in candidates:
        if path.exists():
            return path.resolve()

    raise FileNotFoundError(
        "Could not find directory_controller RTL. Set DIRECTORY_CONTROLLER_RTL "
        "or place directory_controller_metadata_only.sv next to this testbench."
    )


def find_arbiter_file():
    env_source = os.getenv("WRR_ARBITER_RTL")
    if env_source:
        return Path(env_source).resolve()

    here = Path(__file__).resolve()
    candidates = [
        here.parent / "wrr_arbiter.sv",
        here.parent.parent / "src" / "arb" / "wrr_arbiter.sv",
        here.parent.parent / "wrr_arbiter.sv",
    ]

    for path in candidates:
        if path.exists():
            return path.resolve()

    raise FileNotFoundError(
        "Could not find wrr_arbiter RTL. Set WRR_ARBITER_RTL or place "
        "wrr_arbiter.sv next to this testbench."
    )


def run_tests():
    directory_source = find_source_file()
    arbiter_source = find_arbiter_file()

    if SIM == "icarus":
        build_args = ["-g2012"]
    elif SIM == "verilator":
        build_args = ["--timing", "--trace", "--trace-fst"]
    else:
        build_args = []

    runner = get_runner(SIM)
    runner.build(
        sources=[arbiter_source, directory_source],
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

