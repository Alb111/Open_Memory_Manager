# SPDX-License-Identifier: Apache-2.0
#
# Cocotb tests for cache_controller.sv using mocked SRAM ports.
#
# The DUT still instantiates msi_protocol.sv. These tests exercise that MSI
# logic through the controller inputs, rather than driving msi_protocol directly.

import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


NUM_SETS = 64
WORDS_PER_LINE = 4
SET_WIDTH = 6
WORD_WIDTH = 2
TAG_SHIFT = SET_WIDTH + WORD_WIDTH + 2

CACHE_CMD_NONE = 0b000_000_000
CACHE_CMD_BUS_RD = 0b000_000_001
CACHE_CMD_BUS_RDX = 0b000_000_010
CACHE_CMD_BUS_UPGR = 0b000_000_100
CACHE_CMD_EVICT_CLEAN = 0b000_001_000
CACHE_CMD_EVICT_DIRTY = 0b000_010_000
CACHE_CMD_SNOOP_BUS_RD_ACK = 0b000_100_000
CACHE_CMD_SNOOP_BUS_RDX_ACK = 0b001_000_000
CACHE_CMD_SNOOP_BUS_UPGR_ACK = 0b010_000_000

DIR_CMD_BUS_RD_ACK = 0b001
DIR_CMD_BUS_RDX_ACK = 0b010
DIR_CMD_BUS_UPGR_ACK = 0b100

SNOOP_CMD_BUS_RD = 0b001
SNOOP_CMD_BUS_RDX = 0b010
SNOOP_CMD_BUS_UPGR = 0b100


def build_addr(tag, set_idx, word_idx):
    """Build a 32-bit address from tag, set index, and word index."""
    return (
        ((tag & ((1 << (32 - TAG_SHIFT)) - 1)) << TAG_SHIFT)
        | ((set_idx & ((1 << SET_WIDTH) - 1)) << (WORD_WIDTH + 2))
        | ((word_idx & ((1 << WORD_WIDTH) - 1)) << 2)
    )


def get_set(addr):
    """Extract cache set index from address."""
    return (addr >> (WORD_WIDTH + 2)) & ((1 << SET_WIDTH) - 1)


def get_word(addr):
    """Extract cache word index from address."""
    return (addr >> 2) & ((1 << WORD_WIDTH) - 1)


def merge_word(old_data, new_data, strb):
    """Apply byte write strobes to a 32-bit word."""
    merged = old_data

    for byte_idx in range(4):
        if (strb >> byte_idx) & 1:
            mask = 0xFF << (byte_idx * 8)
            merged = (merged & ~mask) | (new_data & mask)

    return merged & 0xFFFF_FFFF


class MockSram:
    """Mock SRAM model connected to cache controller data-cache ports."""

    def __init__(self, dut):
        self.dut = dut
        self.mem = {}

    def key(self, set_idx, word_idx):
        """Return dictionary key for mocked SRAM."""
        return (set_idx & 0x3F, word_idx & 0x3)

    def read(self, set_idx, word_idx):
        """Read a mocked SRAM word."""
        return self.mem.get(self.key(set_idx, word_idx), 0)

    def write(self, set_idx, word_idx, data, strb):
        """Write a mocked SRAM word with byte strobes."""
        old_data = self.read(set_idx, word_idx)
        self.mem[self.key(set_idx, word_idx)] = merge_word(
            old_data,
            data,
            strb,
        )

    def read_addr(self, addr):
        """Read mocked SRAM using a full address."""
        return self.read(get_set(addr), get_word(addr))

    def write_addr(self, addr, data, strb):
        """Write mocked SRAM using a full address."""
        self.write(get_set(addr), get_word(addr), data, strb)

    async def settle(self):
        """Drive read data according to current SRAM read address."""
        await Timer(1, units="ps")

        set_idx = int(self.dut.data_cache_rd_set_o.value)
        word_idx = int(self.dut.data_cache_rd_word_o.value)

        self.dut.data_cache_rd_data_i.value = self.read(set_idx, word_idx)

        await Timer(1, units="ps")

    async def tick(self):
        """Advance one cycle and capture writes into the mocked SRAM."""
        await self.settle()

        if int(self.dut.data_cache_wr_en_o.value) == 1:
            set_idx = int(self.dut.data_cache_wr_set_o.value)
            word_idx = int(self.dut.data_cache_wr_word_o.value)
            data = int(self.dut.data_cache_wr_data_o.value)
            strb = int(self.dut.data_cache_wr_strb_o.value)

            self.write(set_idx, word_idx, data, strb)

        await RisingEdge(self.dut.clk_i)
        await Timer(1, units="ps")


async def reset_dut(dut):
    """Reset DUT and initialize all input ports."""
    dut.rst_ni.value = 0

    dut.mem_valid_i.value = 0
    dut.mem_addr_i.value = 0
    dut.mem_wdata_i.value = 0
    dut.mem_wstrb_i.value = 0

    dut.flush_valid_i.value = 0
    dut.flush_addr_i.value = 0

    dut.data_cache_rd_data_i.value = 0
    dut.data_cache_ready_i.value = 1

    dut.cache_ready_i.value = 1

    dut.bus_valid_i.value = 0
    dut.bus_data_i.value = 0
    dut.bus_dircmd_i.value = 0

    dut.snoop_valid_i.value = 0
    dut.snoop_data_i.value = 0
    dut.snoop_dircmd_i.value = 0

    await RisingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)

    dut.rst_ni.value = 1

    await RisingEdge(dut.clk_i)
    await Timer(1, units="ps")


async def start(dut):
    """Start clock, reset DUT, and return mocked SRAM object."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())
    await reset_dut(dut)
    return MockSram(dut)


def drive_cpu_read(dut, addr):
    """Drive a CPU read request."""
    dut.mem_valid_i.value = 1
    dut.mem_addr_i.value = addr
    dut.mem_wdata_i.value = 0
    dut.mem_wstrb_i.value = 0


def drive_cpu_write(dut, addr, data, strb=0xF):
    """Drive a CPU write request."""
    dut.mem_valid_i.value = 1
    dut.mem_addr_i.value = addr
    dut.mem_wdata_i.value = data
    dut.mem_wstrb_i.value = strb


def clear_cpu(dut):
    """Clear CPU request inputs."""
    dut.mem_valid_i.value = 0
    dut.mem_addr_i.value = 0
    dut.mem_wdata_i.value = 0
    dut.mem_wstrb_i.value = 0


def clear_bus(dut):
    """Clear directory bus response inputs."""
    dut.bus_valid_i.value = 0
    dut.bus_data_i.value = 0
    dut.bus_dircmd_i.value = 0


def clear_snoop(dut):
    """Clear snoop request inputs."""
    dut.snoop_valid_i.value = 0
    dut.snoop_data_i.value = 0
    dut.snoop_dircmd_i.value = 0


def assert_cache_cmd(dut, cmd, addr=None, data=None):
    """Check outgoing cache-interface command."""
    assert int(dut.cache_valid_o.value) == 1
    assert int(dut.cache_cmd_o.value) == cmd

    if addr is not None:
        assert int(dut.cache_addr_o.value) == addr

    if data is not None:
        assert int(dut.cache_data_o.value) == data


async def complete_bus_ack(dut, sram, ack_cmd, data):
    """Drive a directory bus ack and complete pending CPU request."""
    dut.bus_valid_i.value = 1
    dut.bus_dircmd_i.value = ack_cmd
    dut.bus_data_i.value = data

    await sram.settle()

    assert int(dut.bus_ready_o.value) == 1
    assert int(dut.mem_ready_o.value) == 1

    await sram.tick()

    clear_bus(dut)
    clear_cpu(dut)

    await sram.tick()


async def read_miss_fill(dut, sram, addr, fill_data):
    """Cause a read miss and complete it with a directory fill."""
    drive_cpu_read(dut, addr)

    await sram.settle()

    assert int(dut.mem_ready_o.value) == 0
    assert_cache_cmd(dut, CACHE_CMD_BUS_RD, addr=addr)

    await sram.tick()

    dut.bus_valid_i.value = 1
    dut.bus_dircmd_i.value = DIR_CMD_BUS_RD_ACK
    dut.bus_data_i.value = fill_data

    await sram.settle()

    assert int(dut.mem_ready_o.value) == 1
    assert int(dut.mem_rdata_o.value) == fill_data
    assert int(dut.data_cache_wr_en_o.value) == 1
    assert int(dut.data_cache_wr_data_o.value) == fill_data

    await sram.tick()

    clear_bus(dut)
    clear_cpu(dut)

    await sram.tick()


async def write_miss_fill(dut, sram, addr, store_data, strb=0xF, fill_data=0):
    """Cause a write miss and complete it with a directory fill."""
    expected = merge_word(fill_data, store_data, strb)

    drive_cpu_write(dut, addr, store_data, strb)

    await sram.settle()

    assert int(dut.mem_ready_o.value) == 0
    assert_cache_cmd(dut, CACHE_CMD_BUS_RDX, addr=addr)

    await sram.tick()

    dut.bus_valid_i.value = 1
    dut.bus_dircmd_i.value = DIR_CMD_BUS_RDX_ACK
    dut.bus_data_i.value = fill_data

    await sram.settle()

    assert int(dut.mem_ready_o.value) == 1
    assert int(dut.data_cache_wr_en_o.value) == 1
    assert int(dut.data_cache_wr_data_o.value) == expected

    await sram.tick()

    clear_bus(dut)
    clear_cpu(dut)

    await sram.tick()

    assert sram.read_addr(addr) == expected


async def read_hit(dut, sram, addr, expected):
    """Check CPU read hit."""
    drive_cpu_read(dut, addr)

    await sram.settle()

    assert int(dut.cache_valid_o.value) == 0
    assert int(dut.mem_ready_o.value) == 1
    assert int(dut.mem_rdata_o.value) == expected

    await sram.tick()

    clear_cpu(dut)

    await sram.tick()


async def write_hit_modified(dut, sram, addr, data, strb=0xF):
    """Check CPU write hit in Modified state."""
    old_data = sram.read_addr(addr)
    expected = merge_word(old_data, data, strb)

    drive_cpu_write(dut, addr, data, strb)

    await sram.settle()

    assert int(dut.cache_valid_o.value) == 0
    assert int(dut.mem_ready_o.value) == 1
    assert int(dut.data_cache_wr_en_o.value) == 1
    assert int(dut.data_cache_wr_strb_o.value) == strb

    await sram.tick()

    clear_cpu(dut)

    await sram.tick()

    assert sram.read_addr(addr) == expected


async def write_shared_upgrade(dut, sram, addr, data, strb=0xF):
    """Check CPU write hit in Shared state requiring upgrade."""
    old_data = sram.read_addr(addr)
    expected = merge_word(old_data, data, strb)

    drive_cpu_write(dut, addr, data, strb)

    await sram.settle()

    assert int(dut.mem_ready_o.value) == 0
    assert_cache_cmd(dut, CACHE_CMD_BUS_UPGR, addr=addr)

    await sram.tick()

    dut.bus_valid_i.value = 1
    dut.bus_dircmd_i.value = DIR_CMD_BUS_UPGR_ACK

    # The current RTL merges pending stores against bus_data_i during upgrade.
    # Drive the current cached data here so this test checks intended data merge.
    dut.bus_data_i.value = old_data

    await sram.settle()

    assert int(dut.mem_ready_o.value) == 1
    assert int(dut.data_cache_wr_en_o.value) == 1
    assert int(dut.data_cache_wr_data_o.value) == expected

    await sram.tick()

    clear_bus(dut)
    clear_cpu(dut)

    await sram.tick()

    assert sram.read_addr(addr) == expected


@cocotb.test()
async def test_read_miss_shared_then_read_hit(dut):
    """Test I read miss to S, followed by S read hit."""
    sram = await start(dut)

    addr = build_addr(tag=0x12, set_idx=3, word_idx=1)
    fill_data = 0x1234_5678

    await read_miss_fill(dut, sram, addr, fill_data)
    await read_hit(dut, sram, addr, fill_data)


@cocotb.test()
async def test_write_miss_modified_then_read_hit(dut):
    """Test I write miss to M, followed by M read hit."""
    sram = await start(dut)

    addr = build_addr(tag=0x22, set_idx=4, word_idx=2)
    store_data = 0xCAFE_BABE

    await write_miss_fill(dut, sram, addr, store_data)
    await read_hit(dut, sram, addr, store_data)


@cocotb.test()
async def test_shared_write_upgrade_then_modified_write_hit(dut):
    """Test S write upgrade, then M write hit."""
    sram = await start(dut)

    addr = build_addr(tag=0x33, set_idx=5, word_idx=0)

    await read_miss_fill(dut, sram, addr, 0xAAAA_5555)
    await write_shared_upgrade(dut, sram, addr, 0xDEAD_BEEF)
    await read_hit(dut, sram, addr, 0xDEAD_BEEF)

    await write_hit_modified(dut, sram, addr, 0xFACE_CAFE, strb=0xF)
    await read_hit(dut, sram, addr, 0xFACE_CAFE)


@cocotb.test()
async def test_modified_byte_strobes_preserve_unwritten_bytes(dut):
    """Test byte strobes on Modified write hits."""
    sram = await start(dut)

    addr = build_addr(tag=0x44, set_idx=6, word_idx=3)

    await write_miss_fill(dut, sram, addr, 0x1122_3344)

    cases = [
        (0xAAAA_AA99, 0x1, 0x1122_3399),
        (0xAAAA_8800, 0x2, 0x1122_8899),
        (0xAA77_0000, 0x4, 0x1177_8899),
        (0x6600_0000, 0x8, 0x6677_8899),
    ]

    for data, strb, expected in cases:
        await write_hit_modified(dut, sram, addr, data, strb=strb)
        await read_hit(dut, sram, addr, expected)


@cocotb.test()
async def test_clean_replacement_sends_clean_evict_then_new_read(dut):
    """Test replacing a clean Shared line."""
    sram = await start(dut)

    old_addr = build_addr(tag=0x51, set_idx=7, word_idx=1)
    new_addr = build_addr(tag=0x52, set_idx=7, word_idx=1)
    old_data = 0x0102_0304
    new_data = 0xA0B0_C0D0

    await read_miss_fill(dut, sram, old_addr, old_data)

    drive_cpu_read(dut, new_addr)

    await sram.settle()

    assert int(dut.mem_ready_o.value) == 0
    assert int(dut.cache_valid_o.value) == 0

    await sram.tick()
    await sram.settle()

    assert_cache_cmd(dut, CACHE_CMD_EVICT_CLEAN, addr=old_addr, data=old_data)

    await sram.tick()
    await sram.settle()

    assert_cache_cmd(dut, CACHE_CMD_BUS_RD, addr=new_addr)

    await sram.tick()

    dut.bus_valid_i.value = 1
    dut.bus_dircmd_i.value = DIR_CMD_BUS_RD_ACK
    dut.bus_data_i.value = new_data

    await sram.settle()

    assert int(dut.mem_ready_o.value) == 1
    assert int(dut.mem_rdata_o.value) == new_data

    await sram.tick()

    clear_bus(dut)
    clear_cpu(dut)

    await sram.tick()
    await read_hit(dut, sram, new_addr, new_data)


@cocotb.test()
async def test_dirty_replacement_sends_latest_dirty_data(dut):
    """Test replacing a dirty Modified line sends latest dirty data."""
    sram = await start(dut)

    old_addr = build_addr(tag=0x61, set_idx=8, word_idx=2)
    new_addr = build_addr(tag=0x62, set_idx=8, word_idx=2)
    dirty_data = 0x0BAD_F00D
    new_data = 0xABCD_EF01

    await write_miss_fill(dut, sram, old_addr, dirty_data)

    drive_cpu_read(dut, new_addr)

    await sram.settle()

    assert int(dut.mem_ready_o.value) == 0

    await sram.tick()
    await sram.settle()

    assert_cache_cmd(dut, CACHE_CMD_EVICT_DIRTY, addr=old_addr, data=dirty_data)

    await sram.tick()
    await sram.settle()

    assert_cache_cmd(dut, CACHE_CMD_BUS_RD, addr=new_addr)

    await sram.tick()

    dut.bus_valid_i.value = 1
    dut.bus_dircmd_i.value = DIR_CMD_BUS_RD_ACK
    dut.bus_data_i.value = new_data

    await sram.settle()

    assert int(dut.mem_ready_o.value) == 1
    assert int(dut.mem_rdata_o.value) == new_data

    await sram.tick()

    clear_bus(dut)
    clear_cpu(dut)

    await sram.tick()


@cocotb.test()
async def test_flush_invalid_shared_and_modified_lines(dut):
    """Test flush behavior for Invalid, Shared, and Modified lines."""
    sram = await start(dut)

    invalid_addr = build_addr(tag=0x70, set_idx=9, word_idx=0)
    shared_addr = build_addr(tag=0x71, set_idx=10, word_idx=1)
    modified_addr = build_addr(tag=0x72, set_idx=11, word_idx=2)

    dut.flush_valid_i.value = 1
    dut.flush_addr_i.value = invalid_addr

    await sram.settle()

    assert int(dut.flush_ready_o.value) == 1
    assert int(dut.cache_valid_o.value) == 0

    await sram.tick()

    dut.flush_valid_i.value = 0

    await sram.tick()

    await read_miss_fill(dut, sram, shared_addr, 0x2222_3333)

    dut.flush_valid_i.value = 1
    dut.flush_addr_i.value = shared_addr

    await sram.settle()

    assert int(dut.flush_ready_o.value) == 1
    assert_cache_cmd(dut, CACHE_CMD_EVICT_CLEAN, addr=shared_addr, data=0x2222_3333)

    await sram.tick()

    dut.flush_valid_i.value = 0

    await sram.tick()

    drive_cpu_read(dut, shared_addr)

    await sram.settle()

    assert_cache_cmd(dut, CACHE_CMD_BUS_RD, addr=shared_addr)

    clear_cpu(dut)

    await sram.tick()

    await write_miss_fill(dut, sram, modified_addr, 0x4444_5555)

    dut.flush_valid_i.value = 1
    dut.flush_addr_i.value = modified_addr

    await sram.settle()

    assert int(dut.flush_ready_o.value) == 1
    assert_cache_cmd(
        dut,
        CACHE_CMD_EVICT_DIRTY,
        addr=modified_addr,
        data=0x4444_5555,
    )

    await sram.tick()

    dut.flush_valid_i.value = 0

    await sram.tick()

    drive_cpu_read(dut, modified_addr)

    await sram.settle()

    assert_cache_cmd(dut, CACHE_CMD_BUS_RD, addr=modified_addr)


async def drive_snoop(dut, sram, addr, cmd):
    """Drive a directory snoop request."""
    dut.snoop_valid_i.value = 1
    dut.snoop_data_i.value = addr
    dut.snoop_dircmd_i.value = cmd

    await sram.settle()

    assert int(dut.snoop_ready_o.value) == 1


@cocotb.test()
async def test_snoop_cases_from_invalid_state_are_ignored(dut):
    """Test snoops while line is Invalid."""
    sram = await start(dut)

    addr = build_addr(tag=0x80, set_idx=12, word_idx=0)

    for cmd in [SNOOP_CMD_BUS_RD, SNOOP_CMD_BUS_RDX, SNOOP_CMD_BUS_UPGR]:
        await drive_snoop(dut, sram, addr, cmd)

        assert int(dut.cache_valid_o.value) == 0

        await sram.tick()

        clear_snoop(dut)

        await sram.tick()


@cocotb.test()
async def test_snoop_cases_from_shared_state(dut):
    """Test snoops while lines are Shared."""
    sram = await start(dut)

    addr_rd = build_addr(tag=0x90, set_idx=13, word_idx=0)
    addr_rdx = build_addr(tag=0x91, set_idx=14, word_idx=1)
    addr_upgr = build_addr(tag=0x92, set_idx=15, word_idx=2)

    await read_miss_fill(dut, sram, addr_rd, 0xAAAA_0001)
    await drive_snoop(dut, sram, addr_rd, SNOOP_CMD_BUS_RD)

    assert int(dut.cache_valid_o.value) == 0

    await sram.tick()

    clear_snoop(dut)

    await sram.tick()
    await read_hit(dut, sram, addr_rd, 0xAAAA_0001)

    await read_miss_fill(dut, sram, addr_rdx, 0xBBBB_0002)
    await drive_snoop(dut, sram, addr_rdx, SNOOP_CMD_BUS_RDX)

    assert_cache_cmd(dut, CACHE_CMD_SNOOP_BUS_UPGR_ACK, addr=addr_rdx)

    await sram.tick()

    clear_snoop(dut)

    await sram.tick()

    drive_cpu_read(dut, addr_rdx)

    await sram.settle()

    assert_cache_cmd(dut, CACHE_CMD_BUS_RD, addr=addr_rdx)

    clear_cpu(dut)

    await sram.tick()

    await read_miss_fill(dut, sram, addr_upgr, 0xCCCC_0003)
    await drive_snoop(dut, sram, addr_upgr, SNOOP_CMD_BUS_UPGR)

    assert_cache_cmd(dut, CACHE_CMD_SNOOP_BUS_UPGR_ACK, addr=addr_upgr)

    await sram.tick()

    clear_snoop(dut)

    await sram.tick()

    drive_cpu_read(dut, addr_upgr)

    await sram.settle()

    assert_cache_cmd(dut, CACHE_CMD_BUS_RD, addr=addr_upgr)


@cocotb.test()
async def test_snoop_cases_from_modified_state(dut):
    """Test snoops while lines are Modified."""
    sram = await start(dut)

    addr_rd = build_addr(tag=0xA0, set_idx=16, word_idx=0)
    addr_rdx = build_addr(tag=0xA1, set_idx=17, word_idx=1)
    addr_upgr = build_addr(tag=0xA2, set_idx=18, word_idx=2)

    await write_miss_fill(dut, sram, addr_rd, 0x1111_AAAA)
    await drive_snoop(dut, sram, addr_rd, SNOOP_CMD_BUS_RD)

    assert_cache_cmd(
        dut,
        CACHE_CMD_SNOOP_BUS_RD_ACK,
        addr=addr_rd,
        data=0x1111_AAAA,
    )

    await sram.tick()

    clear_snoop(dut)

    await sram.tick()
    await read_hit(dut, sram, addr_rd, 0x1111_AAAA)

    # After M to S downgrade, a CPU write must request an upgrade.
    drive_cpu_write(dut, addr_rd, 0x2222_BBBB, 0xF)

    await sram.settle()

    assert_cache_cmd(dut, CACHE_CMD_BUS_UPGR, addr=addr_rd)

    clear_cpu(dut)

    await sram.tick()

    await write_miss_fill(dut, sram, addr_rdx, 0x3333_CCCC)
    await drive_snoop(dut, sram, addr_rdx, SNOOP_CMD_BUS_RDX)

    assert_cache_cmd(
        dut,
        CACHE_CMD_SNOOP_BUS_RDX_ACK,
        addr=addr_rdx,
        data=0x3333_CCCC,
    )

    await sram.tick()

    clear_snoop(dut)

    await sram.tick()

    drive_cpu_read(dut, addr_rdx)

    await sram.settle()

    assert_cache_cmd(dut, CACHE_CMD_BUS_RD, addr=addr_rdx)

    clear_cpu(dut)

    await sram.tick()

    # M + BusUPGR is illegal in the MSI helper. This controller should still
    # recover by invalidating safely and not deadlocking. The current RTL may
    # send an invalidation ack; if it does, check that it is the safe ack.
    await write_miss_fill(dut, sram, addr_upgr, 0x4444_DDDD)
    await drive_snoop(dut, sram, addr_upgr, SNOOP_CMD_BUS_UPGR)

    if int(dut.cache_valid_o.value) == 1:
        assert int(dut.cache_cmd_o.value) == CACHE_CMD_SNOOP_BUS_UPGR_ACK

    await sram.tick()

    clear_snoop(dut)

    await sram.tick()

    drive_cpu_read(dut, addr_upgr)

    await sram.settle()

    assert_cache_cmd(dut, CACHE_CMD_BUS_RD, addr=addr_upgr)


@cocotb.test()
async def test_cache_interface_ready_stalls_and_holds_command(dut):
    """Test command hold while cache_interface is not ready."""
    sram = await start(dut)

    addr = build_addr(tag=0xB0, set_idx=19, word_idx=1)

    dut.cache_ready_i.value = 0

    drive_cpu_read(dut, addr)

    await sram.settle()

    assert_cache_cmd(dut, CACHE_CMD_BUS_RD, addr=addr)
    assert int(dut.mem_ready_o.value) == 0

    await sram.tick()

    for _ in range(3):
        await sram.settle()

        assert_cache_cmd(dut, CACHE_CMD_BUS_RD, addr=addr)
        assert int(dut.mem_ready_o.value) == 0

        await sram.tick()

    dut.cache_ready_i.value = 1

    await sram.settle()

    assert_cache_cmd(dut, CACHE_CMD_BUS_RD, addr=addr)

    await sram.tick()

    dut.bus_valid_i.value = 1
    dut.bus_dircmd_i.value = DIR_CMD_BUS_RD_ACK
    dut.bus_data_i.value = 0x1234_ABCD

    await sram.settle()

    assert int(dut.mem_ready_o.value) == 1
    assert int(dut.mem_rdata_o.value) == 0x1234_ABCD


@cocotb.test()
async def test_data_cache_not_ready_stalls_cpu_request(dut):
    """Test controller waits while data cache is not ready."""
    sram = await start(dut)

    addr = build_addr(tag=0xC0, set_idx=20, word_idx=0)

    dut.data_cache_ready_i.value = 0

    drive_cpu_read(dut, addr)

    await sram.settle()

    assert int(dut.mem_ready_o.value) == 0
    assert int(dut.cache_valid_o.value) == 0

    await sram.tick()

    dut.data_cache_ready_i.value = 1

    await sram.settle()

    assert_cache_cmd(dut, CACHE_CMD_BUS_RD, addr=addr)


@cocotb.test()
async def test_unexpected_bus_ack_while_idle_does_not_corrupt_state(dut):
    """Test unexpected bus ack while idle is ignored safely."""
    sram = await start(dut)

    addr = build_addr(tag=0xD0, set_idx=21, word_idx=1)

    dut.bus_valid_i.value = 1
    dut.bus_dircmd_i.value = DIR_CMD_BUS_RD_ACK
    dut.bus_data_i.value = 0xFFFF_FFFF

    await sram.settle()

    assert int(dut.bus_ready_o.value) == 0

    await sram.tick()

    clear_bus(dut)

    await read_miss_fill(dut, sram, addr, 0x1357_9BDF)
    await read_hit(dut, sram, addr, 0x1357_9BDF)

def run_tests():
    """Build and run cache_controller.sv with its MSI dependency."""
    import subprocess
    from textwrap import dedent

    sim = os.getenv("SIM", "icarus")

    # This file is:
    #
    #   Open_Memory_Manager/cocotb/cache_controller_test.py
    #
    # So repo_dir becomes:
    #
    #   Open_Memory_Manager
    repo_dir = Path(__file__).resolve().parent.parent
    src_dir = repo_dir / "src"

    verilog_sources = [
        src_dir / "msi_protocol" / "msi_protocol.sv",
        src_dir / "cache" / "rishi_stuff" / "cache_controller.sv",
    ]

    # If cache_controller.sv imports a package, add it FIRST:
    #
    # verilog_sources.insert(
    #     0,
    #     src_dir / "cache" / "rishi_stuff" / "cache_controller_pkg.sv",
    # )

    for source in verilog_sources:
        print("source:", source)
        print("exists:", source.exists())

        if not source.exists():
            raise FileNotFoundError(f"Missing Verilog source: {source}")

    sim_build_dir = Path(__file__).resolve().parent / "sim_build" / "cache_controller"
    sim_build_dir.mkdir(parents=True, exist_ok=True)

    makefile_path = sim_build_dir / "Makefile"

    verilog_sources_text = " \\\n  ".join(str(source) for source in verilog_sources)

    makefile_text = dedent(f"""\
    TOPLEVEL_LANG = verilog
    SIM ?= {sim}

    TOPLEVEL = cache_controller
    COCOTB_TEST_MODULES = {Path(__file__).stem}

    VERILOG_SOURCES = \\
        {verilog_sources_text}

    COMPILE_ARGS += -g2012

    WAVES = 1

    include $(shell cocotb-config --makefiles)/Makefile.sim
    """)

    makefile_path.write_text(makefile_text)

    subprocess.run(
        ["make", "-f", str(makefile_path)],
        cwd=Path(__file__).resolve().parent,
        check=True,
    )


if __name__ == "__main__":
    run_tests()
