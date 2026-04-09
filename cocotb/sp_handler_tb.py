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

    #2. test data regs write & ouput pins
    #write 0xA5 (10100101)
    test_data = 0xA5
    await cpu_write(dut, 0x8000_0010, test_data)
    await RisingEdge(dut.clk_i)
    assert dut.gpio_pins_o.value == test_data, f"ERROR: Pins expected {hex(test_data)}, got {hex(dut.gpio_pins_o.value)}"
    dut._log.info(f"SUCCESS: Physical pins match data register: {hex(int(dut.gpio_pins_o.value))}")

    #3.test data regs read back
    # can cpu read back what it just wrote
    val = await cpu_read(dut, 0x8000_0010)
    assert val == test_data, f"ERROR: Readback failed. Wrote {hex(test_data)}, Read {hex(val)}"

    #4.test CSR/ dir regs
    # set alt pins as input/ouput (0x3C = 00111100)
    test_dir = 0x3C
    await cpu_write(dut, 0x8000_0018, test_dir)
    val = await cpu_read(dut, 0x8000_0018)
    assert val == test_dir, f"ERROR: CSR Readback failed. Expected {hex(test_dir)}, got {hex(val)}"
    assert dut.gpio_dir_o.value == test_dir, "ERROR: Physical direction wires not updating"

    #5. test input pins (outside world talking to the cpu)
    # simulate a sensor pulling a pin high externally
    dut.gpio_pins_i.value = 0xDB # 11011011
    await Timer(10, unit="ns") 
    val = await cpu_read(dut, 0x8000_0010)


    #mmio currently returns the internal register
    #if we wants to read the actual pin state,adjust RTL

    dut._log.info(f"INPUT TEST: External pins set to {hex(0xDB)}")

    #6.test passthru
    # access memory addr that shouldnt trigger mmio
    mem_addr = 0x1234_5678
    dut.addr_i.value = mem_addr
    dut.wr_en_i.value = 0
    await FallingEdge(dut.clk_i)
    assert dut.ack_o.value == 0, "ERROR: ACK went high for a non-special address!"
    assert dut.passthru_addr_o.value == mem_addr, "ERROR: Passthrough address corrupted"
    dut._log.info(f"SUCCESS: Address {hex(mem_addr)} correctly passed through.")

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
    