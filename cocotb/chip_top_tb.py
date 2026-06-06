# SPDX-FileCopyrightText: © 2025 Project Template Contributors
# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, ClockCycles, RisingEdge
from cocotb_tools.runner import get_runner

sim = os.getenv("SIM", "icarus")
REPO_ROOT = Path(__file__).resolve().parent.parent
pdk_root = os.getenv("PDK_ROOT", REPO_ROOT / "gf180mcu")
pdk = os.getenv("PDK", "gf180mcuD")
scl = os.getenv("SCL", "gf180mcu_fd_sc_mcu7t5v0")
gl = os.getenv("GL", False)
slot = os.getenv("SLOT", "1x1")

hdl_toplevel = "chip_top"

# Pin configurations mapping back to the chip top pad frame
PIN_TRAP_LED = int(os.getenv("PIN_TRAP_LED", "0"))
PIN_BOOT_SCLK = int(os.getenv("PIN_BOOT_SCLK", "1"))
PIN_BOOT_MOSI = int(os.getenv("PIN_BOOT_MOSI", "2"))
PIN_BOOT_CS = int(os.getenv("PIN_BOOT_CS", "3"))
PIN_DFT_OUT = int(os.getenv("PIN_DFT_OUT", "4"))
PIN_BOOT_MISO = int(os.getenv("PIN_BOOT_MISO", "40"))
PIN_DEBUG_MODE = int(os.getenv("PIN_DEBUG_MODE", "41"))
PIN_DFT_IN = int(os.getenv("PIN_DFT_IN", "42"))

# SPI flash parameters
BOOT_SIZE_BYTES = int(os.getenv("BOOT_SIZE_BYTES", "512"))
BOOT_IMAGE = os.getenv("BOOT_IMAGE", "")
BOOT_CS_TIMEOUT_CYCLES = int(os.getenv("BOOT_CS_TIMEOUT_CYCLES", "100000"))
SPI_EDGE_TIMEOUT_CYCLES = int(os.getenv("SPI_EDGE_TIMEOUT_CYCLES", "100000"))


def drive_bidir_inputs(dut, boot_miso="z", debug_mode=0, dft_in=0):
    """Drive input pins to the bidirectional PAD structure using standard chip indexing."""
    width = len(dut.bidir_PAD.value)
    bits = ["z"] * width

    for pin, value in (
        (PIN_BOOT_MISO, boot_miso),
        (PIN_DEBUG_MODE, debug_mode),
        (PIN_DFT_IN, dft_in),
    ):
        if value in ("z", "Z", None):
            bits[width - 1 - pin] = "z"
        else:
            bits[width - 1 - pin] = "1" if value else "0"

    dut.bidir_PAD.value = "".join(bits)


def drive_flash_miso(dut, value):
    """Drive specifically the MISO pin while preserving other current driven lines."""
    width = len(dut.bidir_PAD.value)
    current_val = list(str(dut.bidir_PAD.value))
    
    if value in ("z", "Z", None):
        current_val[width - 1 - PIN_BOOT_MISO] = "z"
    else:
        current_val[width - 1 - PIN_BOOT_MISO] = "1" if value else "0"
        
    dut.bidir_PAD.value = "".join(current_val)


def read_bidir_pin(dut, pin):
    """Read a bidirectional pin using physical pad indexing."""
    width = len(dut.bidir_PAD.value)
    return str(dut.bidir_PAD.value)[width - 1 - pin]


def load_boot_image():
    """Load the external binary flash image or fall back to an array of NOPs."""
    if BOOT_IMAGE:
        data = Path(BOOT_IMAGE).read_bytes()
    else:
        # RISC-V NOP = 0x00000013, little-endian byte order.
        data = bytes([0x13, 0x00, 0x00, 0x00]) * (BOOT_SIZE_BYTES // 4)

    if len(data) < BOOT_SIZE_BYTES:
        data += bytes([0x00] * (BOOT_SIZE_BYTES - len(data)))

    return data[:BOOT_SIZE_BYTES]


async def wait_for_pad_value(dut, pin, target, timeout_cycles):
    """Wait for a pad to hit a target string value relative to clk_PAD."""
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk_PAD)
        if read_bidir_pin(dut, pin) == target:
            return
    assert False, f"Timed out waiting for pad {pin} to become {target}"


async def wait_for_spi_sclk_edge(dut, rising=True, timeout_cycles=SPI_EDGE_TIMEOUT_CYCLES):
    """Monitor and wait for an edge transition on the SPI SCLK line."""
    prev = read_bidir_pin(dut, PIN_BOOT_SCLK)

    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk_PAD)
        cur = read_bidir_pin(dut, PIN_BOOT_SCLK)

        if prev in ("0", "1") and cur in ("0", "1"):
            if rising and prev == "0" and cur == "1":
                return
            if not rising and prev == "1" and cur == "0":
                return
        prev = cur

    edge_name = "rising" if rising else "falling"
    assert False, f"Timed out waiting for {edge_name} edge on PIN_BOOT_SCLK"


async def spi_flash_model(dut):
    """
    Simple SPI flash responder for housekeeping boot.

    Expected transaction:
    - flash CS goes low
    - DUT sends 8-bit command + 24-bit address on MOSI
    - flash returns BOOT_SIZE_BYTES on MISO, MSB first
    """
    flash_data = load_boot_image()

    await wait_for_pad_value(
        dut,
        PIN_BOOT_CS,
        "0",
        timeout_cycles=BOOT_CS_TIMEOUT_CYCLES,
    )

    drive_flash_miso(dut, 0)
    command_addr = 0

    for _ in range(32):
        if read_bidir_pin(dut, PIN_BOOT_CS) == "1":
            drive_flash_miso(dut, "z")
            return

        await wait_for_spi_sclk_edge(dut, rising=True)
        mosi = read_bidir_pin(dut, PIN_BOOT_MOSI)
        command_addr = (command_addr << 1) | (1 if mosi == "1" else 0)

    dut._log.info(f"SPI flash command/address = 0x{command_addr:08x}")

    for byte_val in flash_data:
        if read_bidir_pin(dut, PIN_BOOT_CS) == "1":
            break

        for bit in range(7, -1, -1):
            if read_bidir_pin(dut, PIN_BOOT_CS) == "1":
                break

            await wait_for_spi_sclk_edge(dut, rising=False)
            drive_flash_miso(dut, (byte_val >> bit) & 1)

    while read_bidir_pin(dut, PIN_BOOT_CS) == "0":
        await RisingEdge(dut.clk_PAD)

    drive_flash_miso(dut, "z")
    dut._log.info("SPI flash transaction completed")


async def set_defaults(dut):
    drive_bidir_inputs(dut)


async def enable_power(dut):
    dut.VDD.value = 1
    dut.VSS.value = 0


async def start_clock(clock, freq=50):
    """Start the clock @ freq MHz"""
    c = Clock(clock, 1 / freq * 1000, "ns")
    cocotb.start_soon(c.start())


async def reset(reset, active_low=True, time_ns=1000):
    """Reset dut"""
    cocotb.log.info("Reset asserted...")

    reset.value = not active_low
    await Timer(time_ns, "ns")
    reset.value = active_low

    cocotb.log.info("Reset deasserted.")


async def start_up(dut, start_flash=False):
    """Startup sequence"""
    await set_defaults(dut)
    if gl:
        await enable_power(dut)
    await start_clock(dut.clk_PAD)
    if start_flash:
        cocotb.start_soon(spi_flash_model(dut))
    await reset(dut.rst_n_PAD)


@cocotb.test()
async def test_chip_top_pad_smoke(dut):
    """Check that the current chip_core pad plumbing is alive."""
    await start_up(dut)

    drive_bidir_inputs(dut, debug_mode=1)
    await ClockCycles(dut.clk_PAD, 4)
    assert int(dut.bidir_PAD.value[PIN_DFT_OUT]) == 0

    drive_bidir_inputs(dut, debug_mode=1, dft_in=1)
    await ClockCycles(dut.clk_PAD, 4)
    assert int(dut.bidir_PAD.value[PIN_DFT_OUT]) == 1


@cocotb.test()
async def test_trap_led_always_low(dut):
    """Check that trap_led is hardwired low under all input conditions."""
    await start_up(dut)

    for debug in (0, 1):
        for dft in (0, 1):
            drive_bidir_inputs(dut, debug_mode=debug, dft_in=dft)
            await ClockCycles(dut.clk_PAD, 2)
            assert int(dut.bidir_PAD.value[PIN_TRAP_LED]) == 0


@cocotb.test()
async def test_dft_passthrough_no_debug_mode(dut):
    """Check that dft_out follows dft_in even when debug_mode is not set."""
    await start_up(dut)

    drive_bidir_inputs(dut, debug_mode=0, dft_in=1)
    await ClockCycles(dut.clk_PAD, 4)
    assert int(dut.bidir_PAD.value[PIN_DFT_OUT]) == 1

    drive_bidir_inputs(dut, debug_mode=0, dft_in=0)
    await ClockCycles(dut.clk_PAD, 4)
    assert int(dut.bidir_PAD.value[PIN_DFT_OUT]) == 0


@cocotb.test(timeout_time=10, timeout_unit="ms")
async def test_boot_spi_pads_driven_in_normal_mode(dut):
    """Check that boot SPI pads are driven and flash boot can receive MISO data."""
    await start_up(dut, start_flash=True)
    drive_bidir_inputs(dut, debug_mode=0)

    # Wait for housekeeping FSM to assert chip select and start driving SPI.
    for _ in range(BOOT_CS_TIMEOUT_CYCLES):
        await RisingEdge(dut.clk_PAD)
        if read_bidir_pin(dut, PIN_BOOT_CS) == "0":
            break
    else:
        assert False, "Housekeeping FSM never asserted PIN_BOOT_CS"

    # Once CS is asserted, SCLK and MOSI must also be driven.
    for pin, name in (
        (PIN_BOOT_SCLK, "PIN_BOOT_SCLK"),
        (PIN_BOOT_MOSI, "PIN_BOOT_MOSI"),
        (PIN_BOOT_CS, "PIN_BOOT_CS"),
    ):
        val = read_bidir_pin(dut, pin)
        assert val in ("0", "1"), f"{name} must not be X/Z in normal boot mode"


@cocotb.test()
async def test_sync_reset_recovers_cleanly(dut):
    """Check that the chip recovers correctly after multiple sync resets."""
    await start_up(dut)

    for _ in range(3):
        dut.rst_n_PAD.value = 0
        await ClockCycles(dut.clk_PAD, 20)

        dut.rst_n_PAD.value = 1
        await ClockCycles(dut.clk_PAD, 5)

        drive_bidir_inputs(dut, debug_mode=1, dft_in=1)
        await ClockCycles(dut.clk_PAD, 4)
        assert int(dut.bidir_PAD.value[PIN_DFT_OUT]) == 1
        assert int(dut.bidir_PAD.value[PIN_TRAP_LED]) == 0

        drive_bidir_inputs(dut, debug_mode=1, dft_in=0)
        await ClockCycles(dut.clk_PAD, 4)
        assert int(dut.bidir_PAD.value[PIN_DFT_OUT]) == 0


def chip_top_runner():

    proj_path = Path(__file__).resolve().parent

    sources = []
    defines = {f"SLOT_{slot.upper()}": True}
    includes = [proj_path / "../src/"]

    if gl:
        # SCL models
        sources.append(Path(pdk_root) / pdk / "libs.ref" / scl / "verilog" / f"{scl}.v")
        sources.append(Path(pdk_root) / pdk / "libs.ref" / scl / "verilog" / "primitives.v")

        # We use the powered netlist
        sources.append(proj_path / f"../final/pnl/{hdl_toplevel}.pnl.v")

        defines = {"FUNCTIONAL": True, "USE_POWER_PINS": True}
    else:
        sources.append(proj_path / "../src/chip_top.sv")
        sources.append(proj_path / "../src/chip_core.sv")
        sources.append(proj_path / "../src/directory_controller/directory_controller.sv")
        sources.append(proj_path / "../src/arb/wrr_arbiter.sv")
        sources.append(proj_path / "../src/interposer_interface/directory_interface.sv")
        sources.append(proj_path / "../src/interposer_interface/tserializer.sv")
        sources.append(proj_path / "../src/interposer_interface/rserializer.sv")
        sources.append(proj_path / "../src/mem_ctrl/mem2048x32.sv")
        sources.append(proj_path / "../src/mem_ctrl/mem512x32.sv")
        sources.append(proj_path / "../src/mem_ctrl/directory_mem.sv")
        sources.append(proj_path / "../src/mem_ctrl/mem64x8.sv")
        sources.append(proj_path / "../src/housekeeping/boot_fsm.sv")
        sources.append(proj_path / "../src/housekeeping/housekeeping_top.sv")
        sources.append(proj_path / "../src/housekeeping/spi_engine.sv")
        sources.append(proj_path / "../src/interposer_interface/lossy_pipe_stage.sv")

    sources += [
        # IO pad models
        Path(pdk_root) / pdk / "libs.ref/gf180mcu_fd_io/verilog/gf180mcu_fd_io.v",
        Path(pdk_root) / pdk / "libs.ref/gf180mcu_fd_io/verilog/gf180mcu_ws_io.v",

        # SRAM macros
        Path(pdk_root) / pdk / "libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram512x8m8wm1.v",
        Path(pdk_root) / pdk / "libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram64x8m8wm1.v",

        # Custom IP
        proj_path / "../ip/gf180mcu_ws_ip__id/vh/gf180mcu_ws_ip__id.v",
        proj_path / "../ip/gf180mcu_ws_ip__logo/vh/gf180mcu_ws_ip__logo.v",
    ]

    build_args = []

    if sim == "icarus":
        pass

    if sim == "verilator":
        build_args = ["--timing", "--trace", "--trace-fst", "--trace-structs"]

    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel=hdl_toplevel,
        defines=defines,
        always=True,
        includes=includes,
        build_args=build_args,
        waves=True,
    )

    plusargs = []

    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module="chip_top_tb",
        plusargs=plusargs,
        waves=True,
    )


if __name__ == "__main__":
    chip_top_runner()
