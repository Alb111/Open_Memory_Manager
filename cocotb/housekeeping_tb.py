import os
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, ClockCycles, Timer
import random

FLASH_DATA = [
    0xDE, 0xAD, 0xBE, 0xEF,   # word 0
    0xCA, 0xFE, 0xBA, 0xBE,   # word 1
    0x12, 0x34, 0x56, 0x78,   # word 2
    0xAB, 0xCD, 0xEF, 0x01,   # word 3
    0x11, 0x22, 0x33, 0x44,   # word 4
    0x55, 0x66, 0x77, 0x88,   # word 5
    0x99, 0xAA, 0xBB, 0xCC,   # word 6
    0xDD, 0xEE, 0xFF, 0x00,   # word 7  → 32 bytes total (BOOT_SIZE=32)
]

async def flash_model(dut, num_bytes):
    """Simulates a spi NOR flash chip bit-stream"""
    # wait for csb to go low (transaction start)
    while dut.flash_csb_o.value != 0:
        await RisingEdge(dut.clk_i)

    # receive 1 cmd byte + 3 addr bytes
    for _ in range(4 * 8):
        await RisingEdge(dut.spi_sck_o)   # ignore incoming bits

    # drive data bytes out on MISO
    for byte_idx in range(num_bytes):
        byte_val = FLASH_DATA[byte_idx % len(FLASH_DATA)]
        for bit in range(7, -1, -1):          # msb first
            dut.spi_miso_i.value = (byte_val >> bit) & 1
            await RisingEdge(dut.spi_sck_o)   # hold until next rising edge

    dut.spi_miso_i.value = 0

async def apply_reset(dut, cycles=5):
    dut.reset_i.value = 1
    dut.pass_thru_en_i.value = 0
    dut.ext_sck_i.value = 0
    dut.ext_mosi_i.value = 0
    dut.ext_csb_i.value = 1
    dut.spi_miso_i.value = 0
    await ClockCycles(dut.clk_i, cycles)
    dut.reset_i.value = 0

async def wait_for_boot_done(dut, timeout_cycles=50_000):
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk_i)
        if dut.boot_done_o.value == 1:
            return True
    return False


@cocotb.test()
async def test_reset_during_boot(dut):
    """check that a reset during boot clears all internal states"""
    #sram_wr_en, cores_en, and boot_done = 0 and flash_csb =1
    
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())

    dut.reset_i.value = 1
    dut.pass_thru_en_i.value = 0
    dut.spi_miso_i.value = 0
    dut.ext_sck_i.value = 0
    dut.ext_mosi_i.value = 0
    dut.ext_csb_i.value = 1

    await ClockCycles(dut.clk_i, 3)

    assert dut.sram_wr_en_o.value == 0,   "sram_wr_en should be 0 during reset"
    assert dut.cores_en_o.value   == 0,   "cores_en should be 0 during reset"
    assert dut.boot_done_o.value  == 0,   "boot_done should be 0 during reset"

    dut._log.info(" *** PASS - reset holds outputs low")

# @cocotb.test()
# async def test_boot_full(dut):
#     """simplified full test for direct muxing"""
#     cocotb.start_soon(Clock(dut.clk_i, 20, "ns").start())
    
#     # reset
#     dut.reset_i.value = 1
#     dut.spi_miso_i.value = 0
#     await ClockCycles(dut.clk_i, 10)
#     dut.reset_i.value = 0
    
#     #setup data, 32 bytes = 8 words
#     boot_data = [i for i in range(32)]
#     expected_words = []
#     for i in range(0, 32, 4):
#         # spi sends little endian in fsm logic
#         word = (boot_data[i+3] << 24) | (boot_data[i+2] << 16) | (boot_data[i+1] << 8) | boot_data[i]
#         expected_words.append(word)

#     cocotb.start_soon(flash_model(dut, boot_data))

#     # monitor writes
#     for i in range(len(expected_words)):
#         # wait for the write enable pulse to the memory controller mux
#         await RisingEdge(dut.sram_wr_en_o)
        
#         # capture values on the next falling edge to ensure stability
#         await FallingEdge(dut.clk_i)
#         actual_data = int(dut.sram_data_o.value)
#         actual_addr = int(dut.sram_addr_o.value)
        
#         assert actual_data == expected_words[i], f"** DATA ERROR! Word {i}: Expected {hex(expected_words[i])}, Got {hex(actual_data)}"
#         assert actual_addr == (i * 4), f"** ADDR ERROR! Word {i}: Expected {hex(i*4)}, Got {hex(actual_addr)}"
        
#         dut._log.info(f"** Word {i} Verified: Addr=0x{actual_addr:08x}, Data=0x{actual_data:08x}")

#     # final handshake
#     await RisingEdge(dut.boot_done_o)
#     assert dut.cores_en_o.value == 1
#     dut._log.info("** SUCCESS: Full boot verified.")


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