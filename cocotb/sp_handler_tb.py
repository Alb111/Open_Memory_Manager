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
    dut.rst_in.value = 0
    await Timer(20, unit="ns")
    dut.rst_in.value = 1
    await RisingEdge(dut.clk_i)

async def cpu_write(dut, addr, data):
    """Simulates a CPU writing to an address"""
    dut.addr_i.value = addr
    dut.wr_data_i.value = data
    dut.wr_en_i.value = 1
    await RisingEdge(dut.clk_i) # hardware captures data here
    # clear enable after edge
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
async def thorough_mmio_test(dut):
    await setup_reset(dut)
    dut._log.info("--- Starting MMIO Testbench ---")

    #1.test whoami
    expected_id = 0xA1B2C3D4
    val = await cpu_read(dut, 0x8000_0000)
    assert val == expected_id, f"ERROR: WHOAMI expected {hex(expected_id)}, got {hex(val)}"

    # 2.config dir (csr)
    # set pin 0 and pin 7 as outputs (1) others as inputs (0)-> 0b10000001 = 0x81
    test_dir = 0x81
    await cpu_write(dut, 0x8000_0018, test_dir)
    await RisingEdge(dut.clk_i)
    assert int(dut.gpio_dir_o.value) == test_dir, f"CSR Update failed: got {hex(int(dut.gpio_dir_o.value))}"
    dut._log.info(f"SUCCESS: CSR set to {hex(test_dir)}")

    # 3.test indiv pin writes (ouput mode)
    # write 1 to pin 0 (addr 0x8000_0010)
    await cpu_write(dut, 0x8000_0010, 1)
    # write 1 to pin 7 (addr 0x8000_0017)
    await cpu_write(dut, 0x8000_0017, 1)
    await RisingEdge(dut.clk_i) # Allow settling
    assert int(dut.gpio_pins_o.value) == 0x81, f"Expected 0x81, got {hex(int(dut.gpio_pins_o.value))}"
    dut._log.info("SUCCESS: Individual pin writes (0 and 7) verified.")

    # 4.test write protection (input mode)
    #try to write 1 to pin 1 (addr 0x8000_0011), which is input
    await cpu_write(dut, 0x8000_0011, 1)
    await RisingEdge(dut.clk_i)
    assert (int(dut.gpio_pins_o.value) & 0x02) == 0, "ERROR: Wrote to an INPUT pin!"
    dut._log.info("SUCCESS: Input pin correctly rejected write request.")

    # 5.test redaing external inputs
    # sim external world pulling pin 1 high
    dut.gpio_pins_i.value = 0x02 # Pin 1 is high
    await Timer(1, unit="ns")
    val = await cpu_read(dut, 0x8000_0011) # Read Pin 1 address
    assert val == 1, f"ERROR: Failed to read external input on Pin 1. Got {val}"
    dut._log.info("SUCCESS: Verified reading external data from input pin.")

    # 6.test passthru
    mem_addr = 0x1234_5678
    dut.addr_i.value = mem_addr
    dut.wr_en_i.value = 0
    await FallingEdge(dut.clk_i)
    assert dut.ack_o.value == 0, "ERROR: ACK active for non-special address!"
    assert dut.passthru_addr_o.value == mem_addr, "Address passthrough corrupted"

    dut._log.info("--- ALL MMIO AND HANDLER TESTS PASSED!!!! ---")

    
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
    