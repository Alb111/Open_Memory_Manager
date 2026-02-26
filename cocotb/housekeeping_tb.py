import os
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, ClockCycles, ReadOnly
import random

async def flash_model(dut, data):
    """Simulates a flash chip bit-stream"""
    # wait for the fsm to lower csb to start the command
    await FallingEdge(dut.flash_csb_o)
    # wait for command and address phase (32 bits total) to finish
    for _ in range(32):
        await RisingEdge(dut.spi_sck_o)
    
    for byte in data:
        for i in range(8):
            await FallingEdge(dut.spi_sck_o)
            dut.spi_miso_i.value = (byte >> (7-i)) & 1


@cocotb.test()
async def test_boot_full(dut):
    """simplified full test for direct muxing"""
    cocotb.start_soon(Clock(dut.clk_i, 20, "ns").start())
    
    # reset
    dut.reset_i.value = 1
    dut.spi_miso_i.value = 0
    await ClockCycles(dut.clk_i, 10)
    dut.reset_i.value = 0
    
    #setup data, 32 bytes = 8 words
    boot_data = [i for i in range(32)]
    expected_words = []
    for i in range(0, 32, 4):
        # spi sends little endian in fsm logic
        word = (boot_data[i+3] << 24) | (boot_data[i+2] << 16) | (boot_data[i+1] << 8) | boot_data[i]
        expected_words.append(word)

    cocotb.start_soon(flash_model(dut, boot_data))

    # monitor writes
    for i in range(len(expected_words)):
        # wait for the write enable pulse to the memory controller mux
        await RisingEdge(dut.sram_wr_en_o)
        
        # capture values on the next falling edge to ensure stability
        await FallingEdge(dut.clk_i)
        actual_data = int(dut.sram_data_o.value)
        actual_addr = int(dut.sram_addr_o.value)
        
        assert actual_data == expected_words[i], f"** DATA ERROR! Word {i}: Expected {hex(expected_words[i])}, Got {hex(actual_data)}"
        assert actual_addr == (i * 4), f"** ADDR ERROR! Word {i}: Expected {hex(i*4)}, Got {hex(actual_addr)}"
        
        dut._log.info(f"** Word {i} Verified: Addr=0x{actual_addr:08x}, Data=0x{actual_data:08x}")

    # final handshake
    await RisingEdge(dut.boot_done_o)
    assert dut.cores_en_o.value == 1
    dut._log.info("** SUCCESS: Full boot verified.")


@cocotb.test()
async def test_reset_during_boot(dut):
    """check that a reset during boot clears all internal states"""
    cocotb.start_soon(Clock(dut.clk_i, 20, "ns").start())
    
    dut.reset_i.value = 1
    await ClockCycles(dut.clk_i, 5)
    dut.reset_i.value = 0
    
    flash_task = cocotb.start_soon(flash_model(dut, [0xAA]*32))
    
    # wait for spi clock to start ticking, indicates fsm is active
    await RisingEdge(dut.spi_sck_o)
    dut._log.info("Boot started, hitting reset...")
    
    dut.reset_i.value = 1
    await ClockCycles(dut.clk_i, 10)
    
    # signal checks: verify everything went back to zero/idle
    assert dut.sram_wr_en_o.value == 0, "** Error: Write enable stayed high during reset"
    assert dut.boot_done_o.value == 0, "** Error: boot_done high during reset"
    
    flash_task.cancel() 
    dut._log.info("** SUCCESS: Reset recovery verified.")



@cocotb.test()
async def test_short_boot_failure(dut):
    """check cores remain disabled if SPI stream ends/stops early"""
    cocotb.start_soon(Clock(dut.clk_i, 20, "ns").start())
    dut.reset_i.value = 1
    await ClockCycles(dut.clk_i, 5)
    dut.reset_i.value = 0

    # send only 1 word
    short_data = [0xAA, 0xBB, 0xCC, 0xDD]
    flash_task = cocotb.start_soon(flash_model(dut, short_data))
    
    dut._log.info("** Sent partial data, waiting to see if system incorrectly activates...")
    await ClockCycles(dut.clk_i, 1000) 
    
    # signal check
    # check that fsm is stuck and wait for more data state and hasnt triggered the final signals

    done_val = dut.boot_done_o.value
    en_val = dut.cores_en_o.value
    
    dut._log.info(f"** Signal Check: boot_done={done_val}, cores_en={en_val}")
    
    assert done_val == 0, "** FAIL: System reported done on partial data"
    assert en_val == 0, "** FAIL: Cores enabled on partial data"
    
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