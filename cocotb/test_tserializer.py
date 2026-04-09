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

hdl_toplevel = "tserializer"



async def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())

async def reset_dut(dut):
    dut.rst_n.value = 0
    dut.valid_i.value = 0
    dut.data_in.value = 0
    dut.msg_type.value = 0
    await Timer(50, unit="ns")
    await FallingEdge(dut.clk_i)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk_i)

async def collect_message(dut):

    logger = logging.getLogger("cocotb.test")
    NUM_PINS = len(dut.serial_o)
    captured_bits = 0
    bit_count = 0
    while int(dut.current_state.value) == 1:
        bit_count += NUM_PINS
        captured_bits <<= NUM_PINS
        captured_bits += int(dut.serial_o.value)
        await RisingEdge(dut.clk_i)

    logger.info(f"Captured {bit_count} bits: {bin(captured_bits)}")

    return bit_count, captured_bits

class CycleCounter:
    def __init__(self, clock_signal):
        self.count = 0
        self.clk = clock_signal

    async def start(self):
        while True:
            await cocotb.triggers.RisingEdge(self.clk)
            self.count += 1


# ─── Tests ────────────────────────────────────────────────────────────────────
@cocotb.test
async def test_simple_t0(dut):

    NUM_PINS = len(dut.serial_o)

    msg_type = 0
    msg_len = int(dut.MSG_LEN_0.value)
    logger = logging.getLogger("cocotb.test")
    await start_clock(dut)
    await reset_dut(dut)

    # Prepare signals
    await FallingEdge(dut.clk_i)
    test_data = 0x123ABCDEFDEADBEEF # 0001_0010_0011_1010_1011_1100_1101_1110_1111_1101_1110_1010_1101_1011_1110_1110_1111
    dut.msg_type.value = msg_type
    dut.data_in.value = test_data
    dut.valid_i.value = 1
    
    while (dut.ready_o.value != 0):
        await FallingEdge(dut.clk_i)
    dut.valid_i.value = 0 
    await RisingEdge(dut.clk_i)

    # Wait for SEND state
    while int(dut.current_state.value) != 1: 
        await RisingEdge(dut.clk_i)
    
    logger.info("FSM entered SEND state. Capturing serial bits...")

    # Capture serial output until DONE
    bit_count, captured_bits = await collect_message(dut)

    # Validation
    expected_bit_count = ceil(msg_len / NUM_PINS) * NUM_PINS
    expected_mask = 2 ** expected_bit_count - 1

    expected_value = test_data & expected_mask

    assert bit_count == expected_bit_count, f"Expected {expected_bit_count} bits, got {bit_count}"
    assert int(dut.current_state.value) == 0, "Should be in IDLE state"
    assert captured_bits == expected_value, f"Expected data: {expected_value}, got {captured_bits}"

    await RisingEdge(dut.clk_i)

@cocotb.test
async def test_simple_t1(dut):

    NUM_PINS = len(dut.serial_o)

    msg_type = 1
    msg_len = int(dut.MSG_LEN_1.value)
    logger = logging.getLogger("cocotb.test")
    await start_clock(dut)
    await reset_dut(dut)

    # Prepare signals
    await FallingEdge(dut.clk_i)
    test_data = 0x123ABCDEFDEADBEEF # 0001_0010_0011_1010_1011_1100_1101_1110_1111_1101_1110_1010_1101_1011_1110_1110_1111
    dut.msg_type.value = msg_type
    dut.data_in.value = test_data
    dut.valid_i.value = 1
    
    while (dut.ready_o.value != 0):
        await FallingEdge(dut.clk_i)
    dut.valid_i.value = 0 
    await RisingEdge(dut.clk_i)

    # Wait for SEND state
    while int(dut.current_state.value) != 1: 
        await RisingEdge(dut.clk_i)
    
    logger.info("FSM entered SEND state. Capturing serial bits...")

    # Capture serial output until DONE
    bit_count, captured_bits = await collect_message(dut)

    # Validation
    expected_bit_count = ceil(msg_len / NUM_PINS) * NUM_PINS
    expected_mask = 2 ** expected_bit_count - 1

    expected_value = test_data & expected_mask

    assert bit_count == expected_bit_count, f"Expected {expected_bit_count} bits, got {bit_count}"
    assert int(dut.current_state.value) == 0, "Should be in IDLE state"
    assert captured_bits == expected_value, f"Expected data: {expected_value}, got {captured_bits}"

    await RisingEdge(dut.clk_i)

@cocotb.test
async def test_simple_t2(dut):

    NUM_PINS = len(dut.serial_o)

    msg_type = 2
    msg_len = int(dut.MSG_LEN_2.value)
    logger = logging.getLogger("cocotb.test")
    await start_clock(dut)
    await reset_dut(dut)

    # Prepare signals
    await FallingEdge(dut.clk_i)
    test_data = 0x123ABCDEFDEADBEEF # 0001_0010_0011_1010_1011_1100_1101_1110_1111_1101_1110_1010_1101_1011_1110_1110_1111
    dut.msg_type.value = msg_type
    dut.data_in.value = test_data
    dut.valid_i.value = 1
    
    while (dut.ready_o.value != 0):
        await FallingEdge(dut.clk_i)
    dut.valid_i.value = 0 
    await RisingEdge(dut.clk_i)

    # Wait for SEND state
    while int(dut.current_state.value) != 1: 
        await RisingEdge(dut.clk_i)
    
    logger.info("FSM entered SEND state. Capturing serial bits...")

    # Capture serial output until DONE
    bit_count, captured_bits = await collect_message(dut)

    # Validation
    expected_bit_count = ceil(msg_len / NUM_PINS) * NUM_PINS
    expected_mask = 2 ** expected_bit_count - 1

    expected_value = test_data & expected_mask

    assert bit_count == expected_bit_count, f"Expected {expected_bit_count} bits, got {bit_count}"
    assert int(dut.current_state.value) == 0, "Should be in IDLE state"
    assert captured_bits == expected_value, f"Expected data: {expected_value}, got {captured_bits}"

    await RisingEdge(dut.clk_i)

@cocotb.test
async def test_simple_t3(dut):

    NUM_PINS = len(dut.serial_o)

    msg_type = 3
    msg_len = int(dut.MSG_LEN_3.value)
    logger = logging.getLogger("cocotb.test")
    await start_clock(dut)
    await reset_dut(dut)

    # Prepare signals
    await FallingEdge(dut.clk_i)
    test_data = 0x123ABCDEFDEADBEEF # 0001_0010_0011_1010_1011_1100_1101_1110_1111_1101_1110_1010_1101_1011_1110_1110_1111
    dut.msg_type.value = msg_type
    dut.data_in.value = test_data
    dut.valid_i.value = 1
    
    while (dut.ready_o.value != 0):
        await FallingEdge(dut.clk_i)
    dut.valid_i.value = 0 
    await RisingEdge(dut.clk_i)

    # Wait for SEND state
    while int(dut.current_state.value) != 1: 
        await RisingEdge(dut.clk_i)
    
    logger.info("FSM entered SEND state. Capturing serial bits...")

    # Capture serial output until DONE
    bit_count, captured_bits = await collect_message(dut)

    # Validation
    expected_bit_count = ceil(msg_len / NUM_PINS) * NUM_PINS
    expected_mask = 2 ** expected_bit_count - 1

    expected_value = test_data & expected_mask

    assert bit_count == expected_bit_count, f"Expected {expected_bit_count} bits, got {bit_count}"
    assert int(dut.current_state.value) == 0, "Should be in IDLE state"
    assert captured_bits == expected_value, f"Expected data: {expected_value}, got {captured_bits}"

    await RisingEdge(dut.clk_i)

@cocotb.test
async def test_const_send(dut):
    NUM_PINS = len(dut.serial_o)

    logger = logging.getLogger("cocotb.test")
    await start_clock(dut)
    await reset_dut(dut)

    # Prepare signals
    await FallingEdge(dut.clk_i)
    test_data0 = 0x123ABCDEFDEADBEEF # 0001_0010_0011_1010_1011_1100_1101_1110_1111_1101_1110_1010_1101_1011_1110_1110_1111
    test_data1 = 0xABCDEF09876543210
    dut.msg_type.value = 1
    dut.data_in.value = test_data0
    dut.valid_i.value = 1
    
    while (dut.ready_o.value != 0):
        await FallingEdge(dut.clk_i)
    dut.msg_type.value = 3
    dut.data_in.value = test_data1
    await RisingEdge(dut.clk_i)

    # Wait for SEND state
    while int(dut.current_state.value) != 1: 
        await RisingEdge(dut.clk_i)
    
    logger.info("FSM entered SEND state. Capturing serial bits...")

    # Capture serial output until DONE
    bit_count, captured_bits = await collect_message(dut)

    # Validation
    expected_bit_count = ceil(int(dut.MSG_LEN_1.value) / NUM_PINS) * NUM_PINS
    expected_mask = 2 ** expected_bit_count - 1

    expected_value = test_data0 & expected_mask

    assert bit_count == expected_bit_count, f"Expected {expected_bit_count} bits, got {bit_count}"
    assert int(dut.current_state.value) == 0, "Should be in IDLE state"
    assert captured_bits == expected_value, f"Expected data: {expected_value}, got {captured_bits}"

    await RisingEdge(dut.clk_i)

    # Capture serial output until DONE (part 2)
    bit_count, captured_bits = await collect_message(dut)

    # Validation (part 2)
    expected_bit_count = ceil(int(dut.MSG_LEN_3.value) / NUM_PINS) * NUM_PINS
    expected_mask = 2 ** expected_bit_count - 1 

    expected_value = test_data1 & expected_mask

    assert bit_count == expected_bit_count, f"Expected {expected_bit_count} bits, got {bit_count}"
    assert int(dut.current_state.value) == 0, "Should be in IDLE state"
    assert captured_bits == expected_value, f"Expected data: {expected_value}, got {captured_bits}"

@cocotb.test
async def test_single_spaced_send(dut):
    NUM_PINS = len(dut.serial_o)

    logger = logging.getLogger("cocotb.test")
    await start_clock(dut)
    await reset_dut(dut)

    # Prepare signals
    await FallingEdge(dut.clk_i)
    test_data0 = 0x123ABCDEFDEADBEEF # 0001_0010_0011_1010_1011_1100_1101_1110_1111_1101_1110_1010_1101_1011_1110_1110_1111
    test_data1 = 0xABCDEF09876543210
    dut.msg_type.value = 1
    dut.data_in.value = test_data0
    dut.valid_i.value = 1
    
    while (dut.ready_o.value != 0):
        await FallingEdge(dut.clk_i)
    dut.msg_type.value = 3
    dut.data_in.value = test_data1
    dut.valid_i.value = 0
    await RisingEdge(dut.clk_i)

    # Wait for SEND state
    while int(dut.current_state.value) != 1: 
        await RisingEdge(dut.clk_i)
    
    logger.info("FSM entered SEND state. Capturing serial bits...")

    # Capture serial output until DONE
    bit_count, captured_bits = await collect_message(dut)

    # Validation
    expected_bit_count = ceil(int(dut.MSG_LEN_1.value) / NUM_PINS) * NUM_PINS
    expected_mask = 2 ** expected_bit_count - 1

    expected_value = test_data0 & expected_mask

    assert bit_count == expected_bit_count, f"Expected {expected_bit_count} bits, got {bit_count}"
    assert int(dut.current_state.value) == 0, "Should be in IDLE state"
    assert captured_bits == expected_value, f"Expected data: {expected_value}, got {captured_bits}"

    await RisingEdge(dut.clk_i)
    assert int(dut.current_state.value) == 0, "Should be in IDLE state"

    dut.valid_i.value = 1
    while int(dut.current_state.value) != 1:
        await RisingEdge(dut.clk_i)

    # Capture serial output until DONE (part 2)
    bit_count, captured_bits = await collect_message(dut)

    # Validation (part 2)
    expected_bit_count = ceil(int(dut.MSG_LEN_3.value) / NUM_PINS) * NUM_PINS
    expected_mask = 2 ** expected_bit_count - 1

    expected_value = test_data1 & expected_mask

    assert bit_count == expected_bit_count, f"Expected {expected_bit_count} bits, got {bit_count}"
    assert int(dut.current_state.value) == 0, "Should be in IDLE state"
    assert captured_bits == expected_value, f"Expected data: {expected_value}, got {captured_bits}"

@cocotb.test
async def test_multi_spaced_send(dut):

    NUM_PINS = len(dut.serial_o)

    logger = logging.getLogger("cocotb.test")
    await start_clock(dut)
    await reset_dut(dut)

    # Prepare signals
    await FallingEdge(dut.clk_i)
    test_data0 = 0x123ABCDEFDEADBEEF # 0001_0010_0011_1010_1011_1100_1101_1110_1111_1101_1110_1010_1101_1011_1110_1110_1111
    test_data1 = 0xABCDEF09876543210
    dut.msg_type.value = 0
    dut.data_in.value = test_data0
    dut.valid_i.value = 1
    
    while (dut.ready_o.value != 0):
        await FallingEdge(dut.clk_i)
    dut.msg_type.value = 2
    dut.data_in.value = test_data1
    dut.valid_i.value = 0
    await RisingEdge(dut.clk_i)

    # Wait for SEND state
    while int(dut.current_state.value) != 1: 
        await RisingEdge(dut.clk_i)
    
    logger.info("FSM entered SEND state. Capturing serial bits...")

    # Capture serial output until DONE
    bit_count, captured_bits = await collect_message(dut)

    # Validation
    expected_bit_count = ceil(int(dut.MSG_LEN_0.value) / NUM_PINS) * NUM_PINS
    expected_mask = 2 ** expected_bit_count - 1

    expected_value = test_data0 & expected_mask

    assert bit_count == expected_bit_count, f"Expected {expected_bit_count} bits, got {bit_count}"
    assert int(dut.current_state.value) == 0, "Should be in IDLE state"
    assert captured_bits == expected_value, f"Expected data: {expected_value}, got {captured_bits}"

    await RisingEdge(dut.clk_i)
    assert int(dut.current_state.value) == 0, "Should be in IDLE state"

    for _ in range(100):
        await(RisingEdge(dut.clk_i))

    dut.valid_i.value = 1
    while int(dut.current_state.value) != 1:
        await RisingEdge(dut.clk_i)

    # Capture serial output until DONE (part 2)
    bit_count, captured_bits = await collect_message(dut)

    # Validation (part 2)
    expected_bit_count = ceil(int(dut.MSG_LEN_2.value) / NUM_PINS) * NUM_PINS
    expected_mask = 2 ** expected_bit_count -1

    expected_value = test_data1 & expected_mask

    assert bit_count == expected_bit_count, f"Expected {expected_bit_count} bits, got {bit_count}"
    assert int(dut.current_state.value) == 0, "Should be in IDLE state"
    assert captured_bits == expected_value, f"Expected data: {expected_value}, got {captured_bits}"


# ─── Running ──────────────────────────────────────────────────────────────────

def tserializer_runner():
    proj_path = Path(__file__).resolve().parent

    sources = [
        proj_path / "../src/interposer_interface/tserializer.sv",
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
            build_dir=f"sim_build_ts_{run_id}"
        )

        runner.test(
            hdl_toplevel=hdl_toplevel,
            test_module="test_tserializer",
            waves=True,
            build_dir=f"sim_build_ts_{run_id}"
        )

if __name__ == "__main__":
    tserializer_runner()

