import os
import sys
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, ClockCycles
import random


current_dir = Path(__file__).resolve().parent
emulation_path = current_dir.parent / "emulation" / "arbitration_cachecoh"
sys.path.append(str(emulation_path))

try:
    from weighted_round_robin import WeightedRoundRobinArbiter
except ImportError:
    print(f"Error: Could not find weighted_round_robin.py in {emulation_path}")
    sys.exit(1)

async def flash_model(dut, data):
    """Simulates a Flash chip bit-stream"""
    # Wait for the Address Phase (32 bits) to finish
    for _ in range(32):
        await RisingEdge(dut.spi_sck_o)
    
    for byte in data:
        for i in range(8):
            await FallingEdge(dut.spi_sck_o)
            dut.spi_miso_i.value = (byte >> (7-i)) & 1

@cocotb.test()
async def test_boot_with_arbiter_contention(dut):
    """Full Boot Test: 2 words with random Arbiter delays"""
    
    cocotb.start_soon(Clock(dut.clk_i, 20, "ns").start())
    
    # initialize arbiter (Housekeeping is index 0)
    weights = [1, 5] 
    arbiter = WeightedRoundRobinArbiter(num_requesters=2, weights=weights)
    
    # reset
    dut.reset_i.value = 1
    dut.arb_gnt_i.value = 0
    dut.spi_miso_i.value = 0
    await ClockCycles(dut.clk_i, 10)
    dut.reset_i.value = 0
    
    boot_data = [
        0x11, 0x22, 0x33, 0x44, # Word 0
        0x55, 0x66, 0x77, 0x88, # Word 1
        0x99, 0xAA, 0xBB, 0xCC, # Word 2
        0xDD, 0xEE, 0xFF, 0x00, # Word 3
        0x12, 0x34, 0x56, 0x78, # Word 4
        0x9A, 0xBC, 0xDE, 0xF0, # Word 5
        0x11, 0x22, 0x33, 0x44, # Word 6
        0x55, 0x66, 0x77, 0x88  # Word 7 (Total 32 bytes)
    ]
    expected_words = [
        0x44332211, 0x88776655, 0xCCBBAA99, 0x00FFEEDD,
        0x78563412, 0xF0DEBC9A, 0x44332211, 0x88776655
    ]
    
    cocotb.start_soon(flash_model(dut, boot_data))

    words_captured = 0
    while words_captured < len(expected_words):
        # 1. wait for request
        await RisingEdge(dut.arb_req_o)
        
        # 2. simulate other things happening on the bus (Wait 1-10 cycles)
        delay = random.randint(1, 10)
        await ClockCycles(dut.clk_i, delay)
        
        # 3. call python arbiter (pretending core 1 isn't requesting)
        # requests = [housekeeping, core1]
        grant_result = arbiter.arbitrate([1, 0]) 
        
        if grant_result[0] == 1:
            dut.arb_gnt_i.value = 1
            # wait for fsm to see grant and pulse write
            await RisingEdge(dut.clk_i) 
            
            if dut.sram_wr_en_o.value == 1:
                actual = int(dut.sram_data_o.value)
                assert actual == expected_words[words_captured]
                dut._log.info(f"✓ Word {words_captured} written: {hex(actual)}")
                words_captured += 1
            
            await FallingEdge(dut.clk_i)
            dut.arb_gnt_i.value = 0

    await RisingEdge(dut.boot_done_o)
    assert dut.cores_en_o.value == 1
    dut._log.info("✓ SUCCESS: Boot Sequence Complete!")

if __name__ == "__main__":
    from cocotb_tools.runner import get_runner
    
    sources = [
        current_dir / "../src/housekeeping/spi_engine.sv",
        current_dir / "../src/housekeeping/boot_fsm.sv",
        current_dir / "../src/housekeeping/housekeeping_top.sv"
    ]
    
    runner = get_runner("icarus")
    runner.build(
        sources=sources,
        hdl_toplevel="housekeeping_top",
        always=True
    )
    runner.test(
        hdl_toplevel="housekeeping_top",
        test_module="housekeeping_tb",
        waves=True
    )