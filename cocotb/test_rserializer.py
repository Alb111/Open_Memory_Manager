import os
import logging
from pathlib import Path
from math import ceil

import cocotb
from cocotb.triggers import RisingEdge, FallingEdge, Timer
from cocotb_tools.runner import get_runner
from cocotb.clock import Clock
import random


sim = os.getenv("SIM", "icarus")
pdk_root = os.getenv("PDK_ROOT", Path("~/.ciel").expanduser())
pdk = os.getenv("PDK", "gf180mcuD")
scl = os.getenv("SCL", "gf180mcu_fd_sc_mcu7t5v0")
gl = os.getenv("GL", False)
slot = os.getenv("SLOT", "1x1")

hdl_toplevel = "rserializer"



async def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())

async def reset_dut(dut):
    dut.rst_ni.value = 0
    dut.ready_i.value = 0
    dut.serial_i.value = 0
    dut.req_i.value = 0
    await Timer(50, unit="ns")
    await FallingEdge(dut.clk_i)
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)

class CycleCounter:
    def __init__(self, clock_signal):
        self.count = 0
        self.clk = clock_signal

    async def start(self):
        while True:
            await cocotb.triggers.RisingEdge(self.clk)
            self.count += 1

def bstr_to_grouped_list(bstr : int, group_size : int, group_cnt : int):
    mask = 0
    for i in range(group_size):
        mask = (mask << 1) + 1
    print(mask)

    output_list = [None] * group_cnt
    for i in range(group_cnt):
        output_list[i] = bstr & mask
        bstr = bstr >> group_size

    return output_list

# ─── Tests ────────────────────────────────────────────────────────────────────
@cocotb.test
async def test_single(dut):

    NUM_PINS = int(dut.NUM_PINS.value)
    MAX_MSG_LEN = int(dut.MAX_MSG_LEN.value)

    logger = logging.getLogger("cocotb.test")
    msg_lens = {1,2,4,12,36,68}
    
    for msg_len in msg_lens:
        await start_clock(dut)
        await reset_dut(dut)

        # Prepare signals
        await FallingEdge(dut.clk_i)
        test_data = 0x123ABCDEFDEADBEEF # 0001_0010_0011_1010_1011_1100_1101_1110_1111_1101_1110_1010_1101_1011_1110_1110_1111
        
        dut.req_i.value = 1

        serial_list = bstr_to_grouped_list(
            bstr=test_data,
            group_size=NUM_PINS,
            group_cnt= ceil(MAX_MSG_LEN / NUM_PINS)
        )
        
        msg_cycles = ceil(msg_len / NUM_PINS)

        for i in range(msg_cycles-1, -1, -1):
            dut.serial_i.value = serial_list[i]
            await FallingEdge(dut.clk_i)
        
        dut.req_i.value = 0

        await RisingEdge(dut.clk_i)
        await FallingEdge(dut.clk_i)

        mask = 2 ** msg_len - 1
        data = int(dut.data_o.value) & mask
        expected = test_data & mask
        logger.info(f"Captured Message: {hex(data)}, Expected Message Length: {msg_len}")
        assert data == expected, f"Expected data {hex(expected)}, got {hex(data)}, whole data: {hex(dut.data_o.value)}"
        assert int(dut.valid_o.value) == 1, f"valid_o not high after tranmission finished"

        await RisingEdge(dut.clk_i)

@cocotb.test
async def test_const_send(dut):

    NUM_PINS = int(dut.NUM_PINS.value)
    MAX_MSG_LEN = int(dut.MAX_MSG_LEN.value)

    logger = logging.getLogger("cocotb.test")
    await start_clock(dut)
    await reset_dut(dut)

    msg_lens = {1,2,4,12,36,68}

    await FallingEdge(dut.clk_i)
    for msg_len in msg_lens:

        # Prepare signals
        test_data = 0x123ABCDEFDEADBEEF # 0001_0010_0011_1010_1011_1100_1101_1110_1111_1101_1110_1010_1101_1011_1110_1110_1111
        
        dut.req_i.value = 1

        serial_list = bstr_to_grouped_list(
            bstr=test_data,
            group_size=NUM_PINS,
            group_cnt= ceil(MAX_MSG_LEN / NUM_PINS)
        )
        
        msg_cycles = ceil(msg_len / NUM_PINS)

        for i in range(msg_cycles-1, -1, -1):
            dut.serial_i.value = serial_list[i]
            await FallingEdge(dut.clk_i)
        
        dut.req_i.value = 0

        await RisingEdge(dut.clk_i)
        await FallingEdge(dut.clk_i)

        mask = 2 ** msg_len - 1
        data = int(dut.data_o.value) & mask
        expected = test_data & mask
        logger.info(f"Captured Message: {hex(data)}, Expected Message Length: {msg_len}")
        assert data == expected, f"Expected data {hex(expected)}, got {hex(data)}, whole data: {hex(dut.data_o.value)}"
        assert int(dut.valid_o.value) == 1, f"valid_o not high after tranmission finished"

@cocotb.test
async def test_delayed_send(dut):

    NUM_PINS = int(dut.NUM_PINS.value)
    MAX_MSG_LEN = int(dut.MAX_MSG_LEN.value)

    logger = logging.getLogger("cocotb.test")
    await start_clock(dut)
    await reset_dut(dut)

    msg_lens = {1,2,4,12,36,68}

    await FallingEdge(dut.clk_i)
    for msg_len in msg_lens:

        for _ in range(10):
            await FallingEdge(dut.clk_i)

        # Prepare signals
        test_data = 0x123ABCDEFDEADBEEF # 0001_0010_0011_1010_1011_1100_1101_1110_1111_1101_1110_1010_1101_1011_1110_1110_1111
        
        dut.req_i.value = 1

        serial_list = bstr_to_grouped_list(
            bstr=test_data,
            group_size=NUM_PINS,
            group_cnt= ceil(MAX_MSG_LEN / NUM_PINS)
        )
        
        msg_cycles = ceil(msg_len / NUM_PINS)

        for i in range(msg_cycles-1, -1, -1):
            dut.serial_i.value = serial_list[i]
            await FallingEdge(dut.clk_i)
        
        dut.req_i.value = 0

        await RisingEdge(dut.clk_i)
        await FallingEdge(dut.clk_i)

        mask = 2 ** msg_len - 1
        data = int(dut.data_o.value) & mask
        expected = test_data & mask
        logger.info(f"Captured Message: {hex(data)}, Expected Message Length: {msg_len}")
        assert data == expected, f"Expected data {hex(expected)}, got {hex(data)}, whole data: {hex(dut.data_o.value)}"
        assert int(dut.valid_o.value) == 1, f"valid_o not high after tranmission finished"

@cocotb.test
async def test_valid_o_single(dut):

    NUM_PINS = int(dut.NUM_PINS.value)
    MAX_MSG_LEN = int(dut.MAX_MSG_LEN.value)

    logger = logging.getLogger("cocotb.test")
    await start_clock(dut)
    await reset_dut(dut)

    assert dut.valid_o.value == 0, "valid_o, should be low before message sent"

    await FallingEdge(dut.clk_i)
    # Prepare signals
    msg_len = 12
    test_data = 0x123ABCDEFDEADBEEF # 0001_0010_0011_1010_1011_1100_1101_1110_1111_1101_1110_1010_1101_1011_1110_1110_1111
    
    dut.req_i.value = 1

    serial_list = bstr_to_grouped_list(
        bstr=test_data,
        group_size=NUM_PINS,
        group_cnt= ceil(MAX_MSG_LEN / NUM_PINS)
    )
    
    msg_cycles = ceil(msg_len / NUM_PINS)

    for i in range(msg_cycles-1, -1, -1):
        dut.serial_i.value = serial_list[i]
        await FallingEdge(dut.clk_i)
        assert dut.valid_o.value == 0, "valid_o, should be low while message being received"

    
    dut.req_i.value = 0

    await RisingEdge(dut.clk_i)
    await FallingEdge(dut.clk_i)

    mask = 2 ** msg_len - 1
    data = int(dut.data_o.value) & mask
    expected = test_data & mask
    logger.info(f"Captured Message: {hex(data)}, Expected Message Length: {msg_len}")
    assert data == expected, f"Expected data {hex(expected)}, got {hex(data)}, whole data: {hex(dut.data_o.value)}"
    assert int(dut.valid_o.value) == 1, f"valid_o not high after tranmission finished"

    dut.ready_i.value = 1

    await RisingEdge(dut.clk_i)
    await FallingEdge(dut.clk_i)
    assert dut.valid_o.value == 0, "valid_o, should be high after ready-valid handshake"

    await RisingEdge(dut.clk_i)

@cocotb.test
async def test_valid_o_new_msg(dut):
    
    NUM_PINS = int(dut.NUM_PINS.value)
    MAX_MSG_LEN = int(dut.MAX_MSG_LEN.value)

    logger = logging.getLogger("cocotb.test")
    await start_clock(dut)
    await reset_dut(dut)

    assert dut.valid_o.value == 0, "valid_o, should be low before message sent"

    await FallingEdge(dut.clk_i)
    # Prepare signals
    msg_lens = {12, 36}
    
    for msg_len in msg_lens:
        test_data = 0x123ABCDEFDEADBEEF # 0001_0010_0011_1010_1011_1100_1101_1110_1111_1101_1110_1010_1101_1011_1110_1110_1111
        
        dut.req_i.value = 1

        serial_list = bstr_to_grouped_list(
            bstr=test_data,
            group_size=NUM_PINS,
            group_cnt= ceil(MAX_MSG_LEN / NUM_PINS)
        )
        
        msg_cycles = ceil(msg_len / NUM_PINS)

        for i in range(msg_cycles-1, -1, -1):
            dut.serial_i.value = serial_list[i]
            await FallingEdge(dut.clk_i)
            assert dut.valid_o.value == 0, "valid_o, should be low while message being received"

        
        dut.req_i.value = 0

        await RisingEdge(dut.clk_i)
        await FallingEdge(dut.clk_i)

        mask = 2 ** msg_len - 1
        data = int(dut.data_o.value) & mask
        expected = test_data & mask
        logger.info(f"Captured Message: {hex(data)}, Expected Message Length: {msg_len}")
        assert data == expected, f"Expected data {hex(expected)}, got {hex(data)}, whole data: {hex(dut.data_o.value)}"
        assert int(dut.valid_o.value) == 1, f"valid_o not high after tranmission finished"

        await FallingEdge(dut.clk_i)
    await RisingEdge(dut.clk_i)


# ─── Running ──────────────────────────────────────────────────────────────────

def rserializer_runner():
    proj_path = Path(__file__).resolve().parent

    sources = [
        proj_path / "../src/interposer_interface/rserializer.sv",
    ]

    configs = [
        {"NUM_PINS": 1},
        {"NUM_PINS": 4},
        {"NUM_PINS": 9},
    ]

    for config in configs:
        run_id = f"p{config['NUM_PINS']}"

        build_args = []
        if sim == "icarus":
            build_args += ["-g2012", f"-P{hdl_toplevel}.NUM_PINS={config['NUM_PINS']}"]
        if sim == "verilator":
            build_args += ["--timing", "--trace", "--trace-fst", "--trace-structs", f"-GNUM_PINS={config['NUM_PINS']}"]
        
        runner = get_runner(sim)
        runner.build(
            sources=sources,
            hdl_toplevel=hdl_toplevel,
            always=True,
            build_args=build_args,
            waves=True,
            build_dir=f"sim_build_rs_{run_id}"
        )

        runner.test(
            hdl_toplevel=hdl_toplevel,
            test_module="test_rserializer",
            waves=True,
            build_dir=f"sim_build_rs_{run_id}"
        )

if __name__ == "__main__":
    rserializer_runner()

