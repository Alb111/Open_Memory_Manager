import os
import logging
from pathlib import Path
from math import ceil
from enum import IntEnum

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

hdl_toplevel = "cache_interface"

class Metadata(IntEnum):
    NULL            = 0b0000
    BusRD           = 0b0001
    BusRDX          = 0b0010
    BusUPGR         = 0b0011
    EvictClean      = 0b0100
    BusRD_Ack       = 0b0101
    BusRDX_Ack      = 0b0110
    BusUPGR_Ack     = 0b0111
    EvictDirty      = 0b1000
    SnoopBusRD      = 0b1001
    SnoopBusRDX     = 0b1010
    SnoopBusUPGR    = 0b1011
    SnoopBusRD_Ack  = 0b1101
    WhoAmI          = 0b1110
    ResetDone       = 0b1111

class CCMD1H(IntEnum):
    BusRD            = 0b0000001
    BusRDX           = 0b0000010
    BusUPGR          = 0b0000100
    EvictClean       = 0b0001000
    EvictDirty       = 0b0010000
    SnoopBusRD_Ack   = 0b0100000
    ResetDone        = 0b1000000

class DCMD1H(IntEnum):
    BusRD_Ack        = 0b0000001
    BusRDX_Ack       = 0b0000010
    BusUPGR_Ack      = 0b0000100
    SnoopBusRD       = 0b0001000
    SnoopBusRDX      = 0b0010000
    SnoopBusUPGR     = 0b0100000
    WhoAmI           = 0b1000000

async def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())

async def reset_dut(dut):
    dut.rst_ni.value = 0

    # zero all inputs
    dut.mem_valid.value = 0
    dut.mem_addr.value = 0
    dut.mem_wdata.value = 0
    dut.mem_wstrb.value = 0
    dut.cache_cmd.value = 0
    dut.req_i.value = 0
    dut.serial_i.value = 0

    await Timer(50, unit="ns")
    await FallingEdge(dut.clk_i)
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)

async def collect_message(dut):

    logger = logging.getLogger("cocotb.test")
    NUM_PINS = int(dut.NUM_TPINS.value)

    while dut.req_o.value == 0:
        await RisingEdge(dut.clk_i)

    captured_bits = 0
    bit_count = 0
    while dut.req_o.value == 1:
        bit_count += NUM_PINS
        captured_bits <<= NUM_PINS
        captured_bits += int(dut.serial_o.value)
        await RisingEdge(dut.clk_i)

    logger.info(f"Captured {bit_count} bits: {hex(captured_bits)}")

    return bit_count, captured_bits

async def send_message(dut, data, msg_len):

    logger = logging.getLogger("cocotb.test")
    NUM_PINS = int(dut.NUM_RPINS.value)

    dut.req_i.value = 1

    t_len = ceil(msg_len / NUM_PINS)
    mask = (1 << NUM_PINS) - 1

    for i in range (t_len-1, -1, -1):
        curr_data = (data >> (i*NUM_PINS)) & mask
        logger.debug(f"Iteration: {i}, Message: {hex(data)}, Sending: {curr_data}")

        dut.serial_i.value = curr_data
        await FallingEdge(dut.clk_i)
    
    dut.req_i.value = 0
    dut.serial_i.value = 0

def set_packet(dut, ccmd : CCMD1H, mem_addr, mem_wdata):

    assert 0x0 <= mem_addr <= 0xFFFFFFFF, "mem_addr must be 32 bits"
    assert 0x0 <= mem_wdata <= 0xFFFFFFFF, "mem_wdata must be 32 bits"

    dut.mem_valid.value = 1
    dut.cache_cmd.value = ccmd
    dut.mem_addr.value = mem_addr
    dut.mem_wdata.value = mem_wdata

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
async def test_send_BusRD(dut):
    NUM_PINS = int(dut.NUM_TPINS.value)

    await start_clock(dut)
    await reset_dut(dut)

    # prepare signals
    await FallingEdge(dut.clk_i)
    command = CCMD1H.BusRD
    mem_addr = 0xDEADBEEF
    mem_wdata = 0x12345678

    # set signal
    set_packet(dut,ccmd=command, mem_addr=mem_addr, mem_wdata=mem_wdata)

    # collect message
    bit_count, captured_bits = await collect_message(dut)

    # validate message
    expected_bit_count = ceil(36 / NUM_PINS) * NUM_PINS
    expected_data = (mem_addr << 4) + Metadata.BusRD

    assert bit_count == expected_bit_count, f"Expected {expected_bit_count} bits, got {bit_count}"
    assert captured_bits == expected_data, f"Expected Data {hex(expected_data)} bits, got {hex(captured_bits)}"

    await RisingEdge(dut.clk_i)

@cocotb.test
async def test_send_EvictDirty(dut):
    NUM_PINS = int(dut.NUM_TPINS.value)

    await start_clock(dut)
    await reset_dut(dut)

    # prepare signals
    await FallingEdge(dut.clk_i)
    command = CCMD1H.EvictDirty
    mem_addr = 0xDEADBEEF
    mem_wdata = 0x12345678

    # set signal
    set_packet(dut,ccmd=command, mem_addr=mem_addr, mem_wdata=mem_wdata)

    # collect message
    bit_count, captured_bits = await collect_message(dut)

    # validate message
    expected_bit_count = ceil(68 / NUM_PINS) * NUM_PINS
    expected_data = (mem_wdata << 36) + (mem_addr << 4) + Metadata.EvictDirty

    assert bit_count == expected_bit_count, f"Expected {expected_bit_count} bits, got {bit_count}"
    assert captured_bits == expected_data, f"Expected Data {hex(expected_data)} bits, got {hex(captured_bits)}"

    await RisingEdge(dut.clk_i)

@cocotb.test
async def test_send_SnoopBusRD_Ack(dut):
    NUM_PINS = int(dut.NUM_TPINS.value)

    await start_clock(dut)
    await reset_dut(dut)

    # prepare signals
    await FallingEdge(dut.clk_i)
    command = CCMD1H.SnoopBusRD_Ack
    mem_addr = 0xDEADBEEF
    mem_wdata = 0x12345678

    # set signal
    set_packet(dut,ccmd=command, mem_addr=mem_addr, mem_wdata=mem_wdata)

    # collect message
    bit_count, captured_bits = await collect_message(dut)

    # validate message
    expected_bit_count = ceil(36 / NUM_PINS) * NUM_PINS
    expected_data = (mem_wdata << 4) + Metadata.SnoopBusRD_Ack

    assert bit_count == expected_bit_count, f"Expected {expected_bit_count} bits, got {bit_count}"
    assert captured_bits == expected_data, f"Expected Data {hex(expected_data)} bits, got {hex(captured_bits)}"

    await RisingEdge(dut.clk_i)

@cocotb.test
async def test_send_ResetDone(dut):
    NUM_PINS = int(dut.NUM_TPINS.value)

    await start_clock(dut)
    await reset_dut(dut)

    # prepare signals
    await FallingEdge(dut.clk_i)
    command = CCMD1H.ResetDone
    mem_addr = 0xDEADBEEF
    mem_wdata = 0x12345678

    # set signal
    set_packet(dut,ccmd=command, mem_addr=mem_addr, mem_wdata=mem_wdata)

    # collect message
    bit_count, captured_bits = await collect_message(dut)

    # validate message
    expected_bit_count = ceil(4 / NUM_PINS) * NUM_PINS
    expected_data = Metadata.ResetDone

    assert bit_count == expected_bit_count, f"Expected {expected_bit_count} bits, got {bit_count}"
    assert captured_bits == expected_data, f"Expected Data {hex(expected_data)} bits, got {hex(captured_bits)}"
    
    await RisingEdge(dut.clk_i)

@cocotb.test
async def test_receive_WhoAmI(dut):

    await start_clock(dut)
    await reset_dut(dut)

    # prepare signals
    await FallingEdge(dut.clk_i)
    command = Metadata.WhoAmI
    expected_cpu_id = 0xA1
    expected_message = (expected_cpu_id << 4) + command
    expected_msg_len = 12

    # send message
    await FallingEdge(dut.clk_i)
    await send_message(dut, data=expected_message, msg_len=expected_msg_len)

    # validate message
    await FallingEdge(dut.clk_i)
    assert dut.mem_ready.value == 0, "mem_ready should not be high after WhoAmI command"
    await FallingEdge(dut.clk_i)
    cpu_id = int(dut.cpu_id.value)
    assert cpu_id == expected_cpu_id, f"Expected CPU_ID {expected_cpu_id}, got {cpu_id}"
    assert dut.mem_ready.value == 0, "mem_ready should not be high after WhoAmI command"

    await RisingEdge(dut.clk_i)

@cocotb.test
async def test_receive_BusRD_Ack(dut):

    await start_clock(dut)
    await reset_dut(dut)

    # prepare signals
    await FallingEdge(dut.clk_i)
    command = Metadata.BusRD_Ack
    expected_dcmd = DCMD1H.BusRD_Ack
    expected_mem_rdata = 0xDEADBEEF
    expected_message = (expected_mem_rdata << 4) + command
    expected_msg_len = 36

    # send message
    await send_message(dut, data=expected_message, msg_len=expected_msg_len)

    # validate message
    await FallingEdge(dut.clk_i)
    mem_rdata = int(dut.mem_rdata.value)
    directory_cmd = int(dut.directory_cmd.value)

    assert mem_rdata == expected_mem_rdata, f"Expected mem_rdata {expected_mem_rdata}, got {mem_rdata}"
    assert directory_cmd == expected_dcmd, f"Expected directory_cmd {expected_dcmd}, got {directory_cmd}"
    assert dut.mem_ready.value == 1, "mem_ready should not be high after WhoAmI command"

    await RisingEdge(dut.clk_i)

@cocotb.test
async def test_receive_BusUPGR_Ack(dut):

    await start_clock(dut)
    await reset_dut(dut)

    # prepare signals
    await FallingEdge(dut.clk_i)
    command = Metadata.BusUPGR_Ack
    expected_dcmd = DCMD1H.BusUPGR_Ack
    expected_message = command
    expected_msg_len = 4

    # send message
    await send_message(dut, data=expected_message, msg_len=expected_msg_len)

    # validate message
    await FallingEdge(dut.clk_i)
    directory_cmd = int(dut.directory_cmd.value)

    assert directory_cmd == expected_dcmd, f"Expected directory_cmd {expected_dcmd}, got {directory_cmd}"
    assert dut.mem_ready.value == 1, "mem_ready should not be high after WhoAmI command"

    await RisingEdge(dut.clk_i)
    
@cocotb.test
async def test_receive_SnoopBusRDX(dut):

    await start_clock(dut)
    await reset_dut(dut)

    # prepare signals
    await FallingEdge(dut.clk_i)
    command = Metadata.SnoopBusRDX
    expected_dcmd = DCMD1H.SnoopBusRDX
    expected_mem_rdata = 0xDEADBEEF
    expected_message = (expected_mem_rdata << 4) + command
    expected_msg_len = 36

    # send message
    await send_message(dut, data=expected_message, msg_len=expected_msg_len)

    # validate message
    await FallingEdge(dut.clk_i)
    mem_rdata = int(dut.mem_rdata.value)
    directory_cmd = int(dut.directory_cmd.value)

    assert mem_rdata == expected_mem_rdata, f"Expected mem_rdata {expected_mem_rdata}, got {mem_rdata}"
    assert directory_cmd == expected_dcmd, f"Expected directory_cmd {expected_dcmd}, got {directory_cmd}"
    assert dut.mem_ready.value == 1, "mem_ready should not be high after WhoAmI command"

    await RisingEdge(dut.clk_i)

# ─── Running ──────────────────────────────────────────────────────────────────

def cache_interface_runner():
    proj_path = Path(__file__).resolve().parent

    sources = [
        proj_path / "../src/interposer_interface/cache_interface.sv",
        proj_path / "../src/interposer_interface/rserializer.sv",
        proj_path / "../src/interposer_interface/tserializer.sv",
    ]

    configs = [
        {"NUM_TPINS": 1, "NUM_RPINS": 1},
        {"NUM_TPINS": 4, "NUM_RPINS": 4},
        {"NUM_TPINS": 9, "NUM_RPINS": 9},
    ]

    for config in configs:
        run_id = f"tp{config['NUM_TPINS']}_rp{config['NUM_RPINS']}"

        build_args = []
        if sim == "icarus":
            build_args += ["-g2012", f"-P{hdl_toplevel}.NUM_TPINS={config['NUM_TPINS']}", f"-P{hdl_toplevel}.NUM_RPINS={config['NUM_RPINS']}"]
        if sim == "verilator":
            build_args += ["--timing", "--trace", "--trace-fst", "--trace-structs", f"-GNUM_TPINS={config['NUM_TPINS']}", f"-GNUM_RPINS={config['NUM_RPINS']}"]
        
        runner = get_runner(sim)
        runner.build(
            sources=sources,
            hdl_toplevel=hdl_toplevel,
            always=True,
            build_args=build_args,
            waves=True,
            build_dir=f"sim_build_ci_{run_id}"
        )

        runner.test(
            hdl_toplevel=hdl_toplevel,
            test_module="test_cache_interface",
            waves=True,
            build_dir=f"sim_build_ci_{run_id}"
        )

if __name__ == "__main__":
    cache_interface_runner()

