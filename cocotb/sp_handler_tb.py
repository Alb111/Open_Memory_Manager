import os
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge, FallingEdge, ClockCycles
from cocotb_tools.runner import get_runner


sim = os.getenv("SIM", "icarus")
pdk_root = os.getenv("PDK_ROOT", Path("~/.ciel").expanduser())
pdk = os.getenv("PDK", "gf180mcuD")
scl = os.getenv("SCL", "gf180mcu_fd_sc_mcu7t5v0")
gl = os.getenv("GL", False)
slot = os.getenv("SLOT", "1x1")

hdl_toplevel = "sp_addr_handler"

# helper funcs
async def setup_reset(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    dut.rst_ni.value = 0
    dut.gpio_pins_i.value = 0
    dut.ser_tx_ready_i.value = 0
    await Timer(20, unit="ns")
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)

async def cpu_write(dut, addr, data):
    """Simulates a CPU writing to an address"""
    dut.addr_i.value = addr
    dut.wr_data_i.value = data
    dut.wr_en_i.value = 1
    await RisingEdge(dut.clk_i) # hardware captures data here
    dut.wr_en_i.value = 0
    dut._log.info(f"CPU WRITE: Addr={hex(addr)}, Data={hex(data)}")



async def cpu_read(dut, addr):
    """Simulates a CPU reading from an address"""
    dut.addr_i.value = addr
    dut.wr_en_i.value = 0
    await FallingEdge(dut.clk_i) # read on falling edge to ensure stable data
    val = int(dut.rd_data_o.value)
    dut._log.info(f"CPU READ:  Addr={hex(addr)}, Result={hex(val)}")
    return val

# main test
@cocotb.test()
async def full_mmio_test(dut):
    await setup_reset(dut)
    dut._log.info("--- Starting MMIO Testbench ---")

    # test 1: whoami
    val = await cpu_read(dut, 0x8000_0000)
    assert val == 0xA1B2C3D4, "WHOAMI Failed"

    # test 2: csr / write
    # set pin 0 to input (0), pin 1 to output (1) -> csr = 0x02
    await cpu_write(dut, 0x8000_0018, 0x02)
    
    # try to write '1' to both pins (0x03)
    await cpu_write(dut, 0x8000_0010, 0x03)
    
    # pin 1 should be 1, pin 0 should stay 0 (bc its an input)
    val = await cpu_read(dut, 0x8000_0010)
    assert (val & 0x02) == 0x02, "Output pin failed to update"
    assert (val & 0x01) == 0x00, "Input pin was overwritten! Safety logic failed."

    # test 3: serializer handshake
    # When writing to data, ser_tx_valid_o should go high
    dut.ser_tx_ready_i.value = 0
    await cpu_write(dut, 0x8000_0010, 0xAA)
    assert dut.ser_tx_valid_o.value == 1, "Serializer Valid signal didn't trigger"
    dut.ser_tx_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    await Timer(1, unit="ns") 
    assert dut.ser_tx_valid_o.value == 0, "Serializer Valid didn't clear after Ready"
    
    # simulate aeriliazer saying "im ready"
    await RisingEdge(dut.clk_i)
    dut.ser_tx_ready_i.value = 1
    await RisingEdge(dut.clk_i)
    assert dut.ser_tx_valid_o.value == 0, "Serializer Valid didn't clear after Ready"

    # test 4: external input read
    dut.gpio_pins_i.value = 0x01 # Pull Pin 0 high externally
    await Timer(1, unit="ns")
    val = await cpu_read(dut, 0x8000_0010)
    assert (val & 0x01) == 0x01, "Failed to read external pin state"

    # test 5: random reset
    await cpu_write(dut, 0x8000_0018, 0xFF) # All outputs
    dut.rst_ni.value = 0
    await Timer(5, unit="ns")
    dut.rst_ni.value = 1
    val = await cpu_read(dut, 0x8000_0018)
    assert val == 0x00, "Registers did not clear on reset"

    dut._log.info("Done! All tests passed!")

    
def sp_handler_tb_runner():
    proj_path = Path(__file__).resolve().parent

    sources = [
        proj_path / "../src/mmio/mmio.sv",
        proj_path / "../src/mmio/sp_addr_handler.sv"
    ]

    build_args = []
    if sim == "icarus":
        pass
    if sim == "verilator":
        build_args = ["--timing", "--trace", "--trace-fst", "--trace-structs"]

    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel="sp_addr_handler",
        always=True,
        build_args=build_args,
        waves=True
    )

    runner.test(hdl_toplevel="sp_addr_handler", test_module="sp_handler_tb", waves=True)

if __name__ == "__main__":
    sp_handler_tb_runner()
    