import os
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, ClockCycles, ReadOnly
import random

async def flash_model(dut, data):
    """Simulates a flash chip bit-stream"""
    # wait for address phase (32 bits) to finish
    for _ in range(32):
        await RisingEdge(dut.spi_sck_o)
    
    for byte in data:
        for i in range(8):
            await FallingEdge(dut.spi_sck_o)
            dut.spi_miso_i.value = (byte >> (7-i)) & 1



@cocotb.test()
async def test_boot_with_arbiter(dut):
    """Full Boot Test: 8 words with randomized bus grant delays"""
    
    cocotb.start_soon(Clock(dut.clk_i, 20, "ns").start())
    
    # initial state
    dut.reset_i.value = 1
    dut.arb_gnt_i.value = 0
    dut.spi_miso_i.value = 0
    await ClockCycles(dut.clk_i, 10)
    dut.reset_i.value = 0
    
    boot_data = [
        0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 
        0x99, 0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF, 0x00,
        0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC, 0xDE, 0xF0, 
        0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88   
    ]
    expected_words = [
        0x44332211, 0x88776655, 0xCCBBAA99, 0x00FFEEDD,
        0x78563412, 0xF0DEBC9A, 0x44332211, 0x88776655
    ]
    
    cocotb.start_soon(flash_model(dut, boot_data))

    words_captured = 0
    while words_captured < len(expected_words):
        # 1. wair for the boot fsm to request the bus
        await RisingEdge(dut.arb_req_o)
        
        # 2. simulate arbiter is busy for 1-10 cycles
        delay = random.randint(1, 10)
        await ClockCycles(dut.clk_i, delay)
        
        # 3. grant the bus
        dut.arb_gnt_i.value = 1
        
        # 4. wait for the fsm to perform the sram write
        #fsm pulses sram_wr_en_o when it sees gnt and sck is ready
        await RisingEdge(dut.sram_wr_en_o)

        # wait until the end of the clock cycle so the data is stable
        await FallingEdge(dut.clk_i)
        
        # sample data to verify its correct at the moment of the write
        actual = int(dut.sram_data_o.value)
        assert actual == expected_words[words_captured], f"Data Mismatch!!! Word {words_captured}"
        
        dut._log.info(f"** Word {words_captured} written: {hex(actual)}")
        words_captured += 1
        
        # 5. release the grant after the write cycle completes
        await FallingEdge(dut.clk_i)
        dut.arb_gnt_i.value = 0

    # verify final activation signals
    await RisingEdge(dut.boot_done_o)
    assert dut.cores_en_o.value == 1
    dut._log.info("** SUCCESS: boot sequence complete!!!! ***")



@cocotb.test()
async def test_boot_full(dut):
    """full test with 32-bit formatting and checks"""
    cocotb.start_soon(Clock(dut.clk_i, 20, "ns").start())
    
    # 1. reset
    dut.reset_i.value = 1
    await ClockCycles(dut.clk_i, 5)
    dut.reset_i.value = 0
    
    # 2. setup data
    boot_data = [i for i in range(32)]
    expected_words = []
    for i in range(0, 32, 4):
        word = (boot_data[i+3] << 24) | (boot_data[i+2] << 16) | (boot_data[i+1] << 8) | boot_data[i]
        expected_words.append(word)

    cocotb.start_soon(flash_model(dut, boot_data))

    # moniter
    for i in range(len(expected_words)):
        if dut.arb_req_o.value == 1:
            await FallingEdge(dut.arb_req_o)
        await RisingEdge(dut.arb_req_o)
        
        await ReadOnly() # lock sim for reading
        
        actual_data = int(dut.sram_data_o.value)
        actual_addr = int(dut.sram_addr_o.value)
        
        # check against python calculated word
        assert actual_data == expected_words[i], f"DATA ERROR! Word {i}: Expected 0x{expected_words[i]:08x}, Got 0x{actual_data:08x}"
        assert actual_addr == (i * 4), f"ADDR ERROR! Word {i}: Expected 0x{(i*4):08x}, Got 0x{actual_addr:08x}"

        # exit read only phase before driving signals
        await FallingEdge(dut.clk_i) 
        
        # 4. grant accesss
        dut.arb_gnt_i.value = 1
        await RisingEdge(dut.sram_wr_en_o)
        await FallingEdge(dut.clk_i)
        dut.arb_gnt_i.value = 0
        
        dut._log.info(f"** Word {i} Verified: Addr=0x{actual_addr:08x}, Data=0x{actual_data:08x}")



@cocotb.test()
async def test_reset_during_boot(dut):
    """Check that a reset during boot clears all internal states"""
    clock = Clock(dut.clk_i, 20, "ns")
    cocotb.start_soon(clock.start())
    
    dut.reset_i.value = 1
    await ClockCycles(dut.clk_i, 5)
    dut.reset_i.value = 0
    
    flash_task = cocotb.start_soon(flash_model(dut, [0xAA]*32))
    
    # wait for 1st activity
    await RisingEdge(dut.arb_req_o)
    dut._log.info("Boot started, hitting reset...")
    
    dut.reset_i.value = 1
    await ClockCycles(dut.clk_i, 10)
    
    # assertion check if hardware actually responded to reset
    assert dut.arb_req_o.value == 0, "Error: Request stayed high during reset"
    assert dut.sram_addr_o.value == 0, "Error: Address didn't clear"
    assert dut.boot_done_o.value == 0, "Error: boot_done high during reset"
    
    flash_task.cancel() 
    dut._log.info("** SUCESSS: Reset recovery verified.")



@cocotb.test()
async def test_short_boot_failure(dut):
    """Check cores remain disabled if SPI stream ends/stops early"""
    cocotb.start_soon(Clock(dut.clk_i, 20, "ns").start())
    dut.reset_i.value = 1
    await ClockCycles(dut.clk_i, 5)
    dut.reset_i.value = 0

    # send only 1 word
    short_data = [0xAA, 0xBB, 0xCC, 0xDD]
    flash_task = cocotb.start_soon(flash_model(dut, short_data))
    
    dut._log.info("Sent partial data, waiting to see if system incorrectly activates...")
    await ClockCycles(dut.clk_i, 1000) 
    
    # signal check
    # check that fsm is stuck and wait for more data state and hasnt triggered the final signals

    done_val = dut.boot_done_o.value
    en_val = dut.cores_en_o.value
    
    dut._log.info(f"Signal Check: boot_done={done_val}, cores_en={en_val}")
    
    assert done_val == 0, "FAIL: System reported done on partial data"
    assert en_val == 0, "FAIL: Cores enabled on partial data"
    
    flash_task.cancel()
    dut._log.info("** SUCCESS: Short boot failure (Security Check) passed.")


if __name__ == "__main__":
    from cocotb_tools.runner import get_runner
    proj_path = Path(__file__).resolve().parent
    sim = os.getenv("SIM", "icarus")

    sources = [
        proj_path / "../src/housekeeping/spi_engine.sv",
        proj_path / "../src/housekeeping/boot_fsm.sv",
        proj_path / "../src/housekeeping/housekeeping_top.sv"
    ]
    
    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel="housekeeping_top",
        always=True,
        waves=True
    )
    runner.test(
        hdl_toplevel="housekeeping_top",
        test_module="housekeeping_tb",
        waves=True
    )