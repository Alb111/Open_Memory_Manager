import os
import logging
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge, ClockCycles
from cocotb_tools.runner import get_runner

sim = os.getenv("SIM", "icarus")
hdl_toplevel = "directory_metadata_table"

LINE_INVALID = 0b00
LINE_SHARED = 0b01
LINE_MODIFIED = 0b10


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
    dut.read_valid_i.value = 0
    dut.read_index_i.value = 0
    dut.read_ready_i.value = 1

    dut.write_valid_i.value = 0
    dut.write_index_i.value = 0
    dut.write_state_i.value = 0
    dut.write_sharers_i.value = 0
    dut.write_owner_i.value = 0
    dut.write_data_valid_i.value = 0
    dut.write_data_i.value = 0
    dut.write_done_ready_i.value = 1

    dut.status_valid_i.value = 0
    dut.status_index_i.value = 0
    dut.status_ready_i.value = 1


async def reset_dut(dut):
    initialize_inputs(dut)
    dut.rst_ni.value = 0
    await ClockCycles(dut.clk_i, 5)
    dut.rst_ni.value = 1
    await ClockCycles(dut.clk_i, 2)


async def wait_for_table_ready(dut):
    dut.status_valid_i.value = 1
    dut.status_index_i.value = 0

    for _ in range(1200):
        await RisingEdge(dut.clk_i)
        if int(dut.status_ready_o.value) == 1:
            dut.status_valid_i.value = 0
            break
    else:
        assert False, "metadata table did not become ready after memory reset"

    for _ in range(50):
        await RisingEdge(dut.clk_i)
        if int(dut.status_valid_o.value) == 1:
            await RisingEdge(dut.clk_i)
            return


async def setup_dut(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    await reset_dut(dut)
    await wait_for_table_ready(dut)


async def write_entry(dut, index, state, sharers, owner, data_valid, data):
    dut.write_valid_i.value = 1
    dut.write_index_i.value = index
    dut.write_state_i.value = state
    dut.write_sharers_i.value = sharers
    dut.write_owner_i.value = owner
    dut.write_data_valid_i.value = data_valid
    dut.write_data_i.value = data

    while int(dut.write_ready_o.value) == 0:
        await RisingEdge(dut.clk_i)

    await RisingEdge(dut.clk_i)
    dut.write_valid_i.value = 0

    while int(dut.write_done_valid_o.value) == 0:
        await RisingEdge(dut.clk_i)

    await RisingEdge(dut.clk_i)


async def read_entry(dut, index):
    dut.read_valid_i.value = 1
    dut.read_index_i.value = index

    while int(dut.read_ready_o.value) == 0:
        await RisingEdge(dut.clk_i)

    await RisingEdge(dut.clk_i)
    dut.read_valid_i.value = 0

    while int(dut.read_valid_o.value) == 0:
        await RisingEdge(dut.clk_i)

    result = {
        "state": int(dut.read_state_o.value),
        "sharers": int(dut.read_sharers_o.value),
        "owner": int(dut.read_owner_o.value),
        "data_valid": int(dut.read_data_valid_o.value),
        "data": int(dut.read_data_o.value),
    }
    await RisingEdge(dut.clk_i)
    return result


async def status_entry(dut, index):
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


def assert_entry(entry, state, sharers, owner, data_valid, data):
    assert entry["state"] == state, \
        f"state mismatch: got {entry['state']}, expected {state}"
    assert entry["sharers"] == sharers, \
        f"sharers mismatch: got {entry['sharers']}, expected {sharers}"
    assert entry["owner"] == owner, \
        f"owner mismatch: got {entry['owner']}, expected {owner}"
    assert entry["data_valid"] == data_valid, \
        f"data valid mismatch: got {entry['data_valid']}, expected {data_valid}"
    assert entry["data"] == data, \
        f"data mismatch: got 0x{entry['data']:08x}, expected 0x{data:08x}"


@cocotb.test()
async def test_reset_clears_entry(dut):
    await setup_dut(dut)

    reset_entry = await status_entry(dut, 0)
    assert_entry(reset_entry, LINE_INVALID, 0b00, 0, 0, 0)


@cocotb.test()
async def test_write_then_read_entry(dut):
    await setup_dut(dut)

    await write_entry(dut, 3, LINE_SHARED, 0b01, 0, 1, 0x11112222)
    read_result = await read_entry(dut, 3)
    assert_entry(read_result, LINE_SHARED, 0b01, 0, 1, 0x11112222)


@cocotb.test()
async def test_status_read_entry(dut):
    await setup_dut(dut)

    await write_entry(dut, 3, LINE_SHARED, 0b01, 0, 1, 0x11112222)
    status_result = await status_entry(dut, 3)
    assert_entry(status_result, LINE_SHARED, 0b01, 0, 1, 0x11112222)


@cocotb.test()
async def test_multiple_indices_are_independent(dut):
    await setup_dut(dut)

    await write_entry(dut, 3, LINE_SHARED, 0b01, 0, 1, 0x11112222)
    await write_entry(dut, 4, LINE_MODIFIED, 0b00, 1, 1, 0x33334444)

    entry_three = await read_entry(dut, 3)
    entry_four = await read_entry(dut, 4)

    assert_entry(entry_three, LINE_SHARED, 0b01, 0, 1, 0x11112222)
    assert_entry(entry_four, LINE_MODIFIED, 0b00, 1, 1, 0x33334444)


@cocotb.test()
async def test_overwrite_entry(dut):
    await setup_dut(dut)

    await write_entry(dut, 3, LINE_SHARED, 0b01, 0, 1, 0x11112222)
    await write_entry(dut, 3, LINE_INVALID, 0b00, 0, 0, 0x00000000)

    overwritten = await read_entry(dut, 3)
    assert_entry(overwritten, LINE_INVALID, 0b00, 0, 0, 0x00000000)


@cocotb.test()
async def test_all_msi_metadata_combinations(dut):
    await setup_dut(dut)

    index = 10
    for state in [LINE_INVALID, LINE_SHARED, LINE_MODIFIED]:
        for sharers in range(4):
            for owner in range(2):
                for data_valid in range(2):
                    data = (
                        0xABCD0000 | (state << 12) | (sharers << 8) |
                        (owner << 4) | data_valid
                    )
                    await write_entry(dut, index, state, sharers, owner, data_valid, data)
                    entry = await read_entry(dut, index)
                    assert_entry(entry, state, sharers, owner, data_valid, data)
                    index = (index + 1) & 0x7F


@cocotb.test()
async def test_read_response_backpressure(dut):
    await setup_dut(dut)

    await write_entry(dut, 80, LINE_SHARED, 0b11, 0, 1, 0x80808080)

    dut.read_ready_i.value = 0
    dut.read_valid_i.value = 1
    dut.read_index_i.value = 80

    while int(dut.read_ready_o.value) == 0:
        await RisingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)
    dut.read_valid_i.value = 0

    while int(dut.read_valid_o.value) == 0:
        await RisingEdge(dut.clk_i)

    await ClockCycles(dut.clk_i, 3)
    assert int(dut.read_valid_o.value) == 1, \
        "read response should stay valid while read_ready_i is low"

    dut.read_ready_i.value = 1
    await RisingEdge(dut.clk_i)

    read_result = await read_entry(dut, 80)
    assert_entry(read_result, LINE_SHARED, 0b11, 0, 1, 0x80808080)


@cocotb.test()
async def test_write_priority_over_read_and_status(dut):
    await setup_dut(dut)

    dut.write_valid_i.value = 1
    dut.write_index_i.value = 90
    dut.write_state_i.value = LINE_MODIFIED
    dut.write_sharers_i.value = 0
    dut.write_owner_i.value = 1
    dut.write_data_valid_i.value = 1
    dut.write_data_i.value = 0x90909090

    dut.read_valid_i.value = 1
    dut.read_index_i.value = 90
    dut.status_valid_i.value = 1
    dut.status_index_i.value = 90

    await Timer(1, unit="ns")
    assert int(dut.write_ready_o.value) == 1, "write should have highest priority"
    assert int(dut.read_ready_o.value) == 0, "read should wait behind write"
    assert int(dut.status_ready_o.value) == 0, "status should wait behind write"

    await RisingEdge(dut.clk_i)
    dut.write_valid_i.value = 0
    dut.read_valid_i.value = 0
    dut.status_valid_i.value = 0

    while int(dut.write_done_valid_o.value) == 0:
        await RisingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)

    priority_entry = await read_entry(dut, 90)
    assert_entry(priority_entry, LINE_MODIFIED, 0, 1, 1, 0x90909090)


def run_directory_metadata_table():
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
        test_module="test_directory_table",
        waves=True,
    )


if __name__ == "__main__":
    run_directory_metadata_table()

