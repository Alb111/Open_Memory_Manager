import os
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, ClockCycles

@cocotb.test()
async def test_simple_boot(dut):
    """send 4 bytes, check SRAM write"""
    
    # start clock
    cocotb.start_soon(Clock(dut.clk_i, 20, "ns").start())
    
    # reset
    dut.reset_i.value = 1
    dut.spi_miso_i.value = 0
    await ClockCycles(dut.clk_i, 10)
    dut.reset_i.value = 0
    await ClockCycles(dut.clk_i, 5)
    
    dut._log.info("Starting Boot Sequence...")
    
    # 1. wait for comandn (1 byte) and addr (3 bytes) phase to complete
    # total 32 rising edges of sck
    for _ in range(32):
        await RisingEdge(dut.spi_sck_o)
    
    dut._log.info("Address phase finished. Sending Flash Data...")

    # 2. feed actual data
    flash_data = [0xAA, 0xBB, 0xCC, 0xDD]
    
    for val in flash_data:
        for i in range(8):
            # drive miso on the falling edge so it's stable for the rising edge
            await FallingEdge(dut.spi_sck_o)
            dut.spi_miso_i.value = (val >> (7-i)) & 1
            
        dut._log.info(f"Flash provided byte: {hex(val)}")

    #3. wait for the srma write enable to pulse
    await RisingEdge(dut.sram_wr_en_o)
    
    await ClockCycles(dut.clk_i, 1)
    
    actual = int(dut.sram_data_o.value)
    expected = 0xDDCCBBAA # little-endian assembly
    
    dut._log.info(f"SRAM Wrote!!! Data: 0x{actual:08X}")
    
    assert actual == expected, f"ERROR: Expected 0x{expected:08X}, got 0x{actual:08X}"
    dut._log.info("success: boot fsm assembled word correctly!!!!!!!!!")

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
    runner.build(sources=sources, hdl_toplevel="housekeeping_top", always=True, waves=True)
    runner.test(hdl_toplevel="housekeeping_top", test_module="housekeeping_tb", waves=True)