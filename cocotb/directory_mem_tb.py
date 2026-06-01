import os
import random
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer
from cocotb_tools.runner import get_runner

from sram_models import find_sram_model


SIM = os.getenv("SIM", "icarus")
HDL_TOPLEVEL = "directory_mem"


def as_int(signal):
    return int(signal.value)


async def start_clock(dut, freq_mhz=50):
    clock = Clock(dut.clk_i, 1 / freq_mhz * 1000, unit="ns")
    cocotb.start_soon(clock.start())
    await Timer(1, unit="ns")


def set_defaults(dut):
    dut.valid_i.value = 0
    dut.addr_i.value = 0
    dut.wstrb_i.value = 0
    dut.w_data_i.value = 0
    dut.w_state_i.value = 0
    dut.w_sharers_i.value = 0
    dut.w_owner_i.value = 0
    dut.w_valid_data_i.value = 0
    dut.ready_i.value = 0
    dut.main_mem_rdata_i.value = 0
    dut.main_mem_ready_i.value = 0


async def reset(dut):
    set_defaults(dut)
    dut.rst_ni.value = 0
    await ClockCycles(dut.clk_i, 3)
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ns")


async def issue_request(
    dut,
    addr,
    wstrb=0,
    data=0,
    state=0,
    sharers=0,
    owner=0,
    valid_data=0,
):
    await FallingEdge(dut.clk_i)
    dut.addr_i.value = addr & 0xFFFFFFFF
    dut.wstrb_i.value = wstrb & 0xF
    dut.w_data_i.value = data & 0xFFFFFFFF
    dut.w_state_i.value = state & 0x3
    dut.w_sharers_i.value = sharers & 0x3
    dut.w_owner_i.value = owner & 0x1
    dut.w_valid_data_i.value = valid_data & 0x1
    dut.valid_i.value = 1
    await Timer(1, unit="ns")
    assert as_int(dut.ready_o) == 1, "directory_mem did not accept idle request"
    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ns")
    dut.valid_i.value = 0


async def complete_response(dut):
    await FallingEdge(dut.clk_i)
    dut.ready_i.value = 1
    await Timer(1, unit="ns")
    assert as_int(dut.ready_o) == 1, "ready_o should reflect ready_i in response"
    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ns")
    dut.ready_i.value = 0


async def metadata_write(dut, addr, state, sharers, owner, valid_data):
    await issue_request(
        dut,
        addr=addr,
        wstrb=0xF,
        state=state,
        sharers=sharers,
        owner=owner,
        valid_data=valid_data,
    )

    assert as_int(dut.r_state_o) == state
    assert as_int(dut.r_tag_o) == sharers
    assert as_int(dut.r_owner_o) == owner
    assert as_int(dut.r_valid_data_o) == valid_data
    assert as_int(dut.main_mem_valid_o) == 0

    await complete_response(dut)


async def metadata_read(dut, addr):
    await issue_request(dut, addr=addr, wstrb=0)
    got = {
        "state": as_int(dut.r_state_o),
        "sharers": as_int(dut.r_tag_o),
        "owner": as_int(dut.r_owner_o),
        "valid": as_int(dut.r_valid_data_o),
    }
    assert as_int(dut.main_mem_valid_o) == 0
    await complete_response(dut)
    return got


def expect_metadata(got, state, sharers, owner, valid_data):
    assert got == {
        "state": state & 0x3,
        "sharers": sharers & 0x3,
        "owner": owner & 0x1,
        "valid": valid_data & 0x1,
    }


@cocotb.test()
async def test_metadata_even_odd_lanes_round_trip_without_clobber(dut):
    await start_clock(dut)
    await reset(dut)

    await metadata_write(dut, 0x00, state=1, sharers=1, owner=0, valid_data=1)
    await metadata_write(dut, 0x01, state=2, sharers=3, owner=1, valid_data=1)

    expect_metadata(
        await metadata_read(dut, 0x00),
        state=1,
        sharers=1,
        owner=0,
        valid_data=1,
    )
    expect_metadata(
        await metadata_read(dut, 0x01),
        state=2,
        sharers=3,
        owner=1,
        valid_data=1,
    )

    await metadata_write(dut, 0x01, state=0, sharers=2, owner=0, valid_data=0)

    expect_metadata(
        await metadata_read(dut, 0x00),
        state=1,
        sharers=1,
        owner=0,
        valid_data=1,
    )
    expect_metadata(
        await metadata_read(dut, 0x01),
        state=0,
        sharers=2,
        owner=0,
        valid_data=0,
    )


@cocotb.test()
async def test_metadata_random_round_trip_against_golden(dut):
    await start_clock(dut)
    await reset(dut)

    rng = random.Random(0xD1CEC7)
    golden = {}

    for _ in range(128):
        addr = rng.randrange(128)
        state = rng.randrange(3)
        sharers = rng.randrange(4)
        owner = rng.randrange(2)
        valid_data = rng.randrange(2)

        golden[addr] = {
            "state": state,
            "sharers": sharers,
            "owner": owner,
            "valid": valid_data,
        }
        await metadata_write(dut, addr, state, sharers, owner, valid_data)

        got = await metadata_read(dut, addr)
        assert got == golden[addr], (
            f"metadata mismatch at {addr:#x}: DUT={got}, GOLDEN={golden[addr]}"
        )


@cocotb.test()
async def test_ready_i_backpressure_holds_metadata_response(dut):
    await start_clock(dut)
    await reset(dut)

    await metadata_write(dut, 0x24, state=2, sharers=1, owner=1, valid_data=1)
    await issue_request(dut, addr=0x24, wstrb=0)

    expected = (
        as_int(dut.r_state_o),
        as_int(dut.r_tag_o),
        as_int(dut.r_owner_o),
        as_int(dut.r_valid_data_o),
    )
    assert expected == (2, 1, 1, 1)

    for _ in range(4):
        assert as_int(dut.ready_o) == 0
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")
        got = (
            as_int(dut.r_state_o),
            as_int(dut.r_tag_o),
            as_int(dut.r_owner_o),
            as_int(dut.r_valid_data_o),
        )
        assert got == expected, "metadata response changed while ready_i was low"

    await complete_response(dut)


@cocotb.test()
async def test_main_memory_forwarding_waits_for_ready_and_returns_rdata(dut):
    await start_clock(dut)
    await reset(dut)

    addr = 0x700
    data = 0xDEADBEEF
    wstrb = 0xF

    dut.main_mem_ready_i.value = 0

    await FallingEdge(dut.clk_i)
    dut.addr_i.value = addr
    dut.wstrb_i.value = wstrb
    dut.w_data_i.value = data
    dut.valid_i.value = 1
    await Timer(1, unit="ns")

    assert as_int(dut.ready_o) == 1
    assert as_int(dut.main_mem_valid_o) == 1
    assert as_int(dut.main_mem_addr_o) == addr
    assert as_int(dut.main_mem_wdata_o) == data
    assert as_int(dut.main_mem_wstrb_o) == wstrb
    assert as_int(dut.main_mem_instr_o) == 0

    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ns")
    dut.valid_i.value = 0

    for _ in range(3):
        assert as_int(dut.ready_o) == 0
        assert as_int(dut.main_mem_valid_o) == 1
        assert as_int(dut.main_mem_addr_o) == addr
        assert as_int(dut.main_mem_wdata_o) == data
        assert as_int(dut.main_mem_wstrb_o) == wstrb
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")

    dut.main_mem_rdata_i.value = 0xCAFED00D
    dut.main_mem_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ns")

    assert as_int(dut.main_mem_valid_o) == 0
    assert as_int(dut.r_data_o) == 0xCAFED00D
    assert as_int(dut.ready_o) == 0

    await complete_response(dut)


def directory_mem_runner():
    proj_path = Path(__file__).resolve().parent
    sources = [
        find_sram_model(64),
        proj_path / "../src/mem_ctrl/metadata_sram64x8_array.sv",
        proj_path / "../src/mem_ctrl/directory_mem.sv",
    ]

    if SIM == "icarus":
        build_args = ["-g2012"]
    elif SIM == "verilator":
        build_args = ["--timing", "--trace", "--trace-fst", "--trace-structs"]
    else:
        build_args = []

    runner = get_runner(SIM)
    runner.build(
        sources=sources,
        hdl_toplevel=HDL_TOPLEVEL,
        always=True,
        build_args=build_args,
        waves=True,
    )

    runner.test(
        hdl_toplevel=HDL_TOPLEVEL,
        test_module="directory_mem_tb",
        waves=True,
    )


if __name__ == "__main__":
    directory_mem_runner()
