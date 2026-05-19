
import os
import logging
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge, ClockCycles
from cocotb_tools.runner import get_runner

sim = os.getenv("SIM", "icarus")
hdl_toplevel = "directory_controller"

LINE_INVALID = 0b00
LINE_SHARED = 0b01
LINE_MODIFIED = 0b10

CACHE_CMD_NONE = 0b00000
CACHE_CMD_BUS_RD = 0b00001
CACHE_CMD_BUS_RDX = 0b00010
CACHE_CMD_BUS_UPGR = 0b00100
CACHE_CMD_EVICT_CLEAN = 0b01000
CACHE_CMD_EVICT_DIRTY = 0b10000

SNOOP_ACK_BUS_RD = 0b001
SNOOP_ACK_BUS_RDX = 0b010
SNOOP_ACK_BUS_UPGR = 0b100

DIR_CMD_BUS_RD_ACK = 0b000001
DIR_CMD_BUS_RDX_ACK = 0b000010
DIR_CMD_BUS_UPGR_ACK = 0b000100
DIR_CMD_SNOOP_BUS_RD = 0b001000
DIR_CMD_SNOOP_BUS_RDX = 0b010000
DIR_CMD_SNOOP_BUS_UPGR = 0b100000


def write_sram_stubs(proj_path: Path) -> Path:
    stub_path = proj_path / "cocotb" / "sram_models.sv"
    stub_path.write_text(
        """
`timescale 1ns/1ps
`default_nettype none

module gf180mcu_fd_ip_sram__sram512x8m8wm1 (
  input  wire       CLK,
  input  wire       CEN,
  input  wire       GWEN,
  input  wire [7:0] WEN,
  input  wire [8:0] A,
  input  wire [7:0] D,
  output reg  [7:0] Q,
  inout  wire       VDD,
  inout  wire       VSS
);
  reg [7:0] mem[0:511];
  integer i;

  initial begin
    Q = 8'h00;
    for (i = 0; i < 512; i = i + 1) begin
      mem[i] = 8'h00;
    end
  end

  always @(posedge CLK) begin
    if (!CEN) begin
      if (!GWEN) begin
        for (i = 0; i < 8; i = i + 1) begin
          if (!WEN[i]) begin
            mem[A][i] <= D[i];
          end
        end
      end
      Q <= mem[A];
    end
  end
endmodule

module gf180mcu_fd_ip_sram__sram64x8m8wm1 (
  input  wire       CLK,
  input  wire       CEN,
  input  wire       GWEN,
  input  wire [7:0] WEN,
  input  wire [5:0] A,
  input  wire [7:0] D,
  output reg  [7:0] Q,
  inout  wire       VDD,
  inout  wire       VSS
);
  reg [7:0] mem[0:63];
  integer i;

  initial begin
    Q = 8'h00;
    for (i = 0; i < 64; i = i + 1) begin
      mem[i] = 8'h00;
    end
  end

  always @(posedge CLK) begin
    if (!CEN) begin
      if (!GWEN) begin
        for (i = 0; i < 8; i = i + 1) begin
          if (!WEN[i]) begin
            mem[A][i] <= D[i];
          end
        end
      end
      Q <= mem[A];
    end
  end
endmodule

`default_nettype wire
"""
    )
    return stub_path


def find_source(proj_path: Path, candidates: list[Path]) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    candidate_list = "\n".join(str(path) for path in candidates)
    raise FileNotFoundError(f"Could not find source file. Tried:\n{candidate_list}")


def initialize_inputs(dut):
    dut.c0_bus_valid_i.value = 0
    dut.c0_bus_addr_i.value = 0
    dut.c0_bus_wdata_i.value = 0
    dut.c0_bus_cache_cmd_i.value = 0
    dut.c0_snoop_valid_i.value = 0
    dut.c0_snoop_data_i.value = 0
    dut.c0_snoop_cache_cmd_i.value = 0
    dut.c0_dir_ready_i.value = 1

    dut.c1_bus_valid_i.value = 0
    dut.c1_bus_addr_i.value = 0
    dut.c1_bus_wdata_i.value = 0
    dut.c1_bus_cache_cmd_i.value = 0
    dut.c1_snoop_valid_i.value = 0
    dut.c1_snoop_data_i.value = 0
    dut.c1_snoop_cache_cmd_i.value = 0
    dut.c1_dir_ready_i.value = 1

    dut.status_valid_i.value = 0
    dut.status_index_i.value = 0
    dut.status_ready_i.value = 1


async def reset_dut(dut):
    initialize_inputs(dut)
    dut.rst_ni.value = 0
    await ClockCycles(dut.clk_i, 5)
    dut.rst_ni.value = 1
    await ClockCycles(dut.clk_i, 2)


async def wait_for_controller_ready(dut):
    dut.status_valid_i.value = 1
    dut.status_index_i.value = 0
    for _ in range(1400):
        await RisingEdge(dut.clk_i)
        if int(dut.status_ready_o.value) == 1:
            dut.status_valid_i.value = 0
            return
    assert False, "directory controller did not become ready after memory reset"


async def issue_bus_request(dut, cache, cmd, addr, data=0):
    if cache == 0:
        dut.c0_bus_valid_i.value = 1
        dut.c0_bus_addr_i.value = addr
        dut.c0_bus_wdata_i.value = data
        dut.c0_bus_cache_cmd_i.value = cmd
        ready = dut.c0_bus_ready_o
    else:
        dut.c1_bus_valid_i.value = 1
        dut.c1_bus_addr_i.value = addr
        dut.c1_bus_wdata_i.value = data
        dut.c1_bus_cache_cmd_i.value = cmd
        ready = dut.c1_bus_ready_o

    while int(ready.value) == 0:
        await RisingEdge(dut.clk_i)

    await RisingEdge(dut.clk_i)

    if cache == 0:
        dut.c0_bus_valid_i.value = 0
        dut.c0_bus_cache_cmd_i.value = 0
    else:
        dut.c1_bus_valid_i.value = 0
        dut.c1_bus_cache_cmd_i.value = 0


async def issue_simultaneous_requests(dut, c0_addr, c1_addr):
    dut.c0_bus_valid_i.value = 1
    dut.c0_bus_addr_i.value = c0_addr
    dut.c0_bus_wdata_i.value = 0xC0000000 | c0_addr
    dut.c0_bus_cache_cmd_i.value = CACHE_CMD_BUS_RD

    dut.c1_bus_valid_i.value = 1
    dut.c1_bus_addr_i.value = c1_addr
    dut.c1_bus_wdata_i.value = 0xC1000000 | c1_addr
    dut.c1_bus_cache_cmd_i.value = CACHE_CMD_BUS_RD

    while int(dut.c0_bus_ready_o.value) == 0 and int(dut.c1_bus_ready_o.value) == 0:
        await RisingEdge(dut.clk_i)

    c0_ready = int(dut.c0_bus_ready_o.value)
    c1_ready = int(dut.c1_bus_ready_o.value)
    await RisingEdge(dut.clk_i)

    dut.c0_bus_valid_i.value = 0
    dut.c1_bus_valid_i.value = 0
    dut.c0_bus_cache_cmd_i.value = 0
    dut.c1_bus_cache_cmd_i.value = 0

    if c0_ready:
        return 0
    if c1_ready:
        return 1
    assert False, "no simultaneous request was accepted"


async def wait_dir_message(dut, cache):
    if cache == 0:
        valid = dut.c0_dir_valid_o
    else:
        valid = dut.c1_dir_valid_o

    while int(valid.value) == 0:
        await RisingEdge(dut.clk_i)

    if cache == 0:
        result = {
            "cmd": int(dut.c0_dir_cmd_o.value),
            "addr": int(dut.c0_dir_addr_o.value),
            "data": int(dut.c0_dir_data_o.value),
        }
    else:
        result = {
            "cmd": int(dut.c1_dir_cmd_o.value),
            "addr": int(dut.c1_dir_addr_o.value),
            "data": int(dut.c1_dir_data_o.value),
        }

    await RisingEdge(dut.clk_i)
    return result


async def read_status(dut, index):
    dut.status_valid_i.value = 1
    dut.status_index_i.value = index

    while int(dut.status_ready_o.value) == 0:
        await RisingEdge(dut.clk_i)

    await RisingEdge(dut.clk_i)
    dut.status_valid_i.value = 0

    while int(dut.status_valid_o.value) == 0:
        await RisingEdge(dut.clk_i)

    result = {
        "state": int(dut.status_state_o.value),
        "sharers": int(dut.status_sharers_o.value),
        "owner": int(dut.status_owner_o.value),
        "data_valid": int(dut.status_data_valid_o.value),
        "data": int(dut.status_data_o.value),
    }
    await RisingEdge(dut.clk_i)
    return result


async def send_dirty_flush(dut, cache, addr, data):
    if cache == 0:
        dut.c0_bus_valid_i.value = 1
        dut.c0_bus_addr_i.value = addr
        dut.c0_bus_wdata_i.value = data
        dut.c0_bus_cache_cmd_i.value = CACHE_CMD_EVICT_DIRTY
        ready = dut.c0_bus_ready_o
    else:
        dut.c1_bus_valid_i.value = 1
        dut.c1_bus_addr_i.value = addr
        dut.c1_bus_wdata_i.value = data
        dut.c1_bus_cache_cmd_i.value = CACHE_CMD_EVICT_DIRTY
        ready = dut.c1_bus_ready_o

    while int(ready.value) == 0:
        await RisingEdge(dut.clk_i)

    await RisingEdge(dut.clk_i)

    if cache == 0:
        dut.c0_bus_valid_i.value = 0
        dut.c0_bus_cache_cmd_i.value = 0
    else:
        dut.c1_bus_valid_i.value = 0
        dut.c1_bus_cache_cmd_i.value = 0


async def send_snoop_ack(dut, cache, ack_cmd):
    if cache == 0:
        dut.c0_snoop_valid_i.value = 1
        dut.c0_snoop_cache_cmd_i.value = ack_cmd
        ready = dut.c0_snoop_ready_o
    else:
        dut.c1_snoop_valid_i.value = 1
        dut.c1_snoop_cache_cmd_i.value = ack_cmd
        ready = dut.c1_snoop_ready_o

    while int(ready.value) == 0:
        await RisingEdge(dut.clk_i)

    await RisingEdge(dut.clk_i)

    if cache == 0:
        dut.c0_snoop_valid_i.value = 0
        dut.c0_snoop_cache_cmd_i.value = 0
    else:
        dut.c1_snoop_valid_i.value = 0
        dut.c1_snoop_cache_cmd_i.value = 0


def assert_dir_message(message, cmd, addr, data=None):
    assert message["cmd"] == cmd, \
        f"dir cmd mismatch: got {message['cmd']:06b}, expected {cmd:06b}"
    assert message["addr"] == addr, \
        f"dir addr mismatch: got 0x{message['addr']:08x}, expected 0x{addr:08x}"
    if data is not None:
        assert message["data"] == data, \
            f"dir data mismatch: got 0x{message['data']:08x}, expected 0x{data:08x}"


def assert_status(entry, state, sharers, owner, data_valid, data=None):
    assert entry["state"] == state, \
        f"state mismatch: got {entry['state']}, expected {state}"
    assert entry["sharers"] == sharers, \
        f"sharers mismatch: got {entry['sharers']}, expected {sharers}"
    assert entry["owner"] == owner, \
        f"owner mismatch: got {entry['owner']}, expected {owner}"
    assert entry["data_valid"] == data_valid, \
        f"data_valid mismatch: got {entry['data_valid']}, expected {data_valid}"
    if data is not None:
        assert entry["data"] == data, \
            f"data mismatch: got 0x{entry['data']:08x}, expected 0x{data:08x}"




async def setup_dut(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    await reset_dut(dut)
    await wait_for_controller_ready(dut)


async def create_shared_line(dut, addr, data):
    await issue_bus_request(dut, 0, CACHE_CMD_BUS_RD, addr, data)
    message = await wait_dir_message(dut, 0)
    assert_dir_message(message, DIR_CMD_BUS_RD_ACK, addr, data)


async def create_two_sharer_line(dut, addr, data):
    await create_shared_line(dut, addr, data)
    await issue_bus_request(dut, 1, CACHE_CMD_BUS_RD, addr, 0)
    message = await wait_dir_message(dut, 1)
    assert_dir_message(message, DIR_CMD_BUS_RD_ACK, addr, data)


async def create_modified_line(dut, owner_cache, addr, data):
    await issue_bus_request(dut, owner_cache, CACHE_CMD_BUS_RDX, addr, data)
    message = await wait_dir_message(dut, owner_cache)
    assert_dir_message(message, DIR_CMD_BUS_RDX_ACK, addr, data)


@cocotb.test()
async def test_round_robin_request_selection(dut):
    await setup_dut(dut)

    accepted = await issue_simultaneous_requests(dut, 0x00000001, 0x00000002)
    assert accepted == 0, "first simultaneous request should select cache 0"
    message = await wait_dir_message(dut, 0)
    assert_dir_message(message, DIR_CMD_BUS_RD_ACK, 0x00000001, 0xC0000001)

    accepted = await issue_simultaneous_requests(dut, 0x00000003, 0x00000004)
    assert accepted == 1, "second simultaneous request should select cache 1"
    message = await wait_dir_message(dut, 1)
    assert_dir_message(message, DIR_CMD_BUS_RD_ACK, 0x00000004, 0xC1000004)


@cocotb.test()
async def test_unknown_command_is_ignored(dut):
    await setup_dut(dut)

    await issue_bus_request(dut, 0, CACHE_CMD_NONE, 0x00000005, 0x55555555)
    await ClockCycles(dut.clk_i, 30)

    assert int(dut.c0_dir_valid_o.value) == 0, "unknown command should not ack"
    status = await read_status(dut, 5)
    assert_status(status, LINE_INVALID, 0b00, 0, 0)


@cocotb.test()
async def test_bus_rd_invalid_line_creates_shared_entry(dut):
    await setup_dut(dut)

    addr = 0x00000010
    await issue_bus_request(dut, 0, CACHE_CMD_BUS_RD, addr, 0x11112222)
    message = await wait_dir_message(dut, 0)

    assert_dir_message(message, DIR_CMD_BUS_RD_ACK, addr, 0x11112222)
    status = await read_status(dut, addr & 0x7F)
    assert_status(status, LINE_SHARED, 0b01, 0, 1, 0x11112222)


@cocotb.test()
async def test_bus_rd_shared_line_adds_second_sharer(dut):
    await setup_dut(dut)

    addr = 0x00000010
    await create_shared_line(dut, addr, 0x11112222)

    await issue_bus_request(dut, 1, CACHE_CMD_BUS_RD, addr, 0x33334444)
    message = await wait_dir_message(dut, 1)

    assert_dir_message(message, DIR_CMD_BUS_RD_ACK, addr, 0x11112222)
    status = await read_status(dut, addr & 0x7F)
    assert_status(status, LINE_SHARED, 0b11, 0, 1, 0x11112222)


@cocotb.test()
async def test_evict_clean_removes_sharers_and_invalidates(dut):
    await setup_dut(dut)

    addr = 0x00000010
    await create_two_sharer_line(dut, addr, 0x11112222)

    await issue_bus_request(dut, 0, CACHE_CMD_EVICT_CLEAN, addr, 0)
    status = await read_status(dut, addr & 0x7F)
    assert_status(status, LINE_SHARED, 0b10, 0, 1, 0x11112222)

    await issue_bus_request(dut, 1, CACHE_CMD_EVICT_CLEAN, addr, 0)
    status = await read_status(dut, addr & 0x7F)
    assert_status(status, LINE_INVALID, 0b00, 0, 1, 0x11112222)


@cocotb.test()
async def test_bus_rdx_invalid_line_creates_modified_owner(dut):
    await setup_dut(dut)

    addr = 0x00000020
    await issue_bus_request(dut, 0, CACHE_CMD_BUS_RDX, addr, 0xBBBB0001)
    message = await wait_dir_message(dut, 0)

    assert_dir_message(message, DIR_CMD_BUS_RDX_ACK, addr, 0xBBBB0001)
    status = await read_status(dut, addr & 0x7F)
    assert_status(status, LINE_MODIFIED, 0b00, 0, 1, 0xBBBB0001)


@cocotb.test()
async def test_evict_dirty_stores_data_and_invalidates(dut):
    await setup_dut(dut)

    addr = 0x00000020
    await create_modified_line(dut, 0, addr, 0xBBBB0001)

    await issue_bus_request(dut, 0, CACHE_CMD_EVICT_DIRTY, addr, 0xDDDD0002)
    status = await read_status(dut, addr & 0x7F)
    assert_status(status, LINE_INVALID, 0b00, 0, 1, 0xDDDD0002)


@cocotb.test()
async def test_bus_rd_reuses_stored_dirty_data(dut):
    await setup_dut(dut)

    addr = 0x00000020
    await create_modified_line(dut, 0, addr, 0xBBBB0001)
    await issue_bus_request(dut, 0, CACHE_CMD_EVICT_DIRTY, addr, 0xDDDD0002)

    await issue_bus_request(dut, 1, CACHE_CMD_BUS_RD, addr, 0)
    message = await wait_dir_message(dut, 1)

    assert_dir_message(message, DIR_CMD_BUS_RD_ACK, addr, 0xDDDD0002)
    status = await read_status(dut, addr & 0x7F)
    assert_status(status, LINE_SHARED, 0b10, 0, 1, 0xDDDD0002)


@cocotb.test()
async def test_bus_upgr_single_sharer_completes_without_snoop(dut):
    await setup_dut(dut)

    addr = 0x00000020
    await create_modified_line(dut, 0, addr, 0xBBBB0001)
    await issue_bus_request(dut, 0, CACHE_CMD_EVICT_DIRTY, addr, 0xDDDD0002)
    await issue_bus_request(dut, 1, CACHE_CMD_BUS_RD, addr, 0)
    message = await wait_dir_message(dut, 1)
    assert_dir_message(message, DIR_CMD_BUS_RD_ACK, addr, 0xDDDD0002)

    await issue_bus_request(dut, 1, CACHE_CMD_BUS_UPGR, addr, 0)
    message = await wait_dir_message(dut, 1)

    assert_dir_message(message, DIR_CMD_BUS_UPGR_ACK, addr, 0)
    status = await read_status(dut, addr & 0x7F)
    assert_status(status, LINE_MODIFIED, 0b00, 1, 1, 0xDDDD0002)


@cocotb.test()
async def test_bus_upgr_two_sharers_snoops_other_cache(dut):
    await setup_dut(dut)

    addr = 0x00000030
    await create_two_sharer_line(dut, addr, 0xCCCC0001)

    await issue_bus_request(dut, 0, CACHE_CMD_BUS_UPGR, addr, 0)
    message = await wait_dir_message(dut, 1)
    assert_dir_message(message, DIR_CMD_SNOOP_BUS_UPGR, addr, 0)

    await send_snoop_ack(dut, 1, SNOOP_ACK_BUS_UPGR)
    message = await wait_dir_message(dut, 0)

    assert_dir_message(message, DIR_CMD_BUS_UPGR_ACK, addr, 0)
    status = await read_status(dut, addr & 0x7F)
    assert_status(status, LINE_MODIFIED, 0b00, 0, 1, 0xCCCC0001)


@cocotb.test()
async def test_bus_rdx_shared_line_uses_snoop_bus_upgr(dut):
    await setup_dut(dut)

    addr = 0x00000040
    await create_two_sharer_line(dut, addr, 0xDDDD0001)

    await issue_bus_request(dut, 1, CACHE_CMD_BUS_RDX, addr, 0)
    message = await wait_dir_message(dut, 0)
    assert_dir_message(message, DIR_CMD_SNOOP_BUS_UPGR, addr, 0)

    await send_snoop_ack(dut, 0, SNOOP_ACK_BUS_UPGR)
    message = await wait_dir_message(dut, 1)

    assert_dir_message(message, DIR_CMD_BUS_RDX_ACK, addr, 0xDDDD0001)
    status = await read_status(dut, addr & 0x7F)
    assert_status(status, LINE_MODIFIED, 0b00, 1, 1, 0xDDDD0001)


@cocotb.test()
async def test_bus_rd_remote_modified_forwards_dirty_data(dut):
    await setup_dut(dut)

    addr = 0x00000050
    await create_modified_line(dut, 0, addr, 0xEEEE0001)

    await issue_bus_request(dut, 1, CACHE_CMD_BUS_RD, addr, 0)
    message = await wait_dir_message(dut, 0)
    assert_dir_message(message, DIR_CMD_SNOOP_BUS_RD, addr, 0)

    await send_dirty_flush(dut, 0, addr, 0xEEEE1234)
    await send_snoop_ack(dut, 0, SNOOP_ACK_BUS_RD)
    message = await wait_dir_message(dut, 1)

    assert_dir_message(message, DIR_CMD_BUS_RD_ACK, addr, 0xEEEE1234)
    status = await read_status(dut, addr & 0x7F)
    assert_status(status, LINE_SHARED, 0b11, 0, 1, 0xEEEE1234)


@cocotb.test()
async def test_bus_rdx_remote_modified_forwards_dirty_data(dut):
    await setup_dut(dut)

    addr = 0x00000060
    await create_modified_line(dut, 0, addr, 0xFFFF0001)

    await issue_bus_request(dut, 1, CACHE_CMD_BUS_RDX, addr, 0)
    message = await wait_dir_message(dut, 0)
    assert_dir_message(message, DIR_CMD_SNOOP_BUS_RDX, addr, 0)

    await send_dirty_flush(dut, 0, addr, 0xFFFF1234)
    await send_snoop_ack(dut, 0, SNOOP_ACK_BUS_RDX)
    message = await wait_dir_message(dut, 1)

    assert_dir_message(message, DIR_CMD_BUS_RDX_ACK, addr, 0xFFFF1234)
    status = await read_status(dut, addr & 0x7F)
    assert_status(status, LINE_MODIFIED, 0b00, 1, 1, 0xFFFF1234)


@cocotb.test()
async def test_directory_response_backpressure(dut):
    await setup_dut(dut)

    addr = 0x00000070
    dut.c0_dir_ready_i.value = 0
    await issue_bus_request(dut, 0, CACHE_CMD_BUS_RD, addr, 0x77770001)

    while int(dut.c0_dir_valid_o.value) == 0:
        await RisingEdge(dut.clk_i)

    assert int(dut.c0_dir_cmd_o.value) == DIR_CMD_BUS_RD_ACK
    await ClockCycles(dut.clk_i, 3)
    assert int(dut.c0_dir_valid_o.value) == 1, \
        "directory response should remain valid during backpressure"

    dut.c0_dir_ready_i.value = 1
    message = await wait_dir_message(dut, 0)

    assert_dir_message(message, DIR_CMD_BUS_RD_ACK, addr, 0x77770001)
    status = await read_status(dut, addr & 0x7F)
    assert_status(status, LINE_SHARED, 0b01, 0, 1, 0x77770001)


def run_directory_controller():
    proj_path = Path(__file__).resolve().parent.parent
    sram_stub = write_sram_stubs(proj_path)
    mem128x32 = find_source(
        proj_path,
        [
            proj_path / "src" / "mem_ctrl" / "cache_dir_memory" / "mem128x32.sv",
            proj_path / "src" / "mem128x32.sv",
        ],
    )

    sources = [
        sram_stub,
        mem128x32,
        proj_path / "src" / "directory_metadata_table.sv",
        proj_path / "src" / "directory_controller.sv",
    ]

    build_args = []
    if sim == "icarus":
        build_args = ["-g2012"]
    if sim == "verilator":
        build_args = ["--timing", "--trace", "--trace-fst", "--trace-structs"]

    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel=hdl_toplevel,
        always=True,
        build_args=build_args,
        waves=True,
    )

    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module="test_directory",
        waves=True,
    )


if __name__ == "__main__":
    run_directory_controller()

