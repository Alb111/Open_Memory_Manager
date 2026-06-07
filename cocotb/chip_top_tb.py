# SPDX-FileCopyrightText: © 2025 Project Template Contributors
# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, ClockCycles, RisingEdge
from cocotb_tools.runner import get_runner


# -----------------------------------------------------------------------------
# Environment / build configuration
# -----------------------------------------------------------------------------

sim = os.getenv("SIM", "icarus")

REPO_ROOT = Path(__file__).resolve().parent.parent
pdk_root = Path(os.getenv("PDK_ROOT", REPO_ROOT / "gf180mcu"))
pdk = os.getenv("PDK", "gf180mcuD")
scl = os.getenv("SCL", "gf180mcu_fd_sc_mcu7t5v0")
slot = os.getenv("SLOT", "1x1")

hdl_toplevel = "chip_top"


def env_flag(name, default="0"):
    return os.getenv(name, default).lower() in ("1", "true", "yes", "on")


gl = env_flag("GL")
sdf = env_flag("SDF")
sdf_file = os.getenv("SDF_FILE", "")
sdf_corner = os.getenv("SDF_CORNER", "max_tt_025C_5v00")

# The actual chip target is 20 MHz = 50 ns period.
CLOCK_FREQ_MHZ = float(os.getenv("CLOCK_FREQ_MHZ", "20"))
RESET_TIME_NS = int(os.getenv("RESET_TIME_NS", "1000"))

# Pin configurations mapping back to the chip top pad frame.
PIN_TRAP_LED = int(os.getenv("PIN_TRAP_LED", "0"))
PIN_BOOT_SCLK = int(os.getenv("PIN_BOOT_SCLK", "1"))
PIN_BOOT_MOSI = int(os.getenv("PIN_BOOT_MOSI", "2"))
PIN_BOOT_CS = int(os.getenv("PIN_BOOT_CS", "3"))
PIN_DFT_OUT = int(os.getenv("PIN_DFT_OUT", "4"))
PIN_BOOT_MISO = int(os.getenv("PIN_BOOT_MISO", "40"))
PIN_DEBUG_MODE = int(os.getenv("PIN_DEBUG_MODE", "41"))
PIN_DFT_IN = int(os.getenv("PIN_DFT_IN", "42"))

CRITICAL_OUTPUT_PINS = (
    (PIN_TRAP_LED, "PIN_TRAP_LED"),
    (PIN_DFT_OUT, "PIN_DFT_OUT"),
    (PIN_BOOT_SCLK, "PIN_BOOT_SCLK"),
    (PIN_BOOT_MOSI, "PIN_BOOT_MOSI"),
    (PIN_BOOT_CS, "PIN_BOOT_CS"),
)

# SPI flash parameters.
BOOT_SIZE_BYTES = int(os.getenv("BOOT_SIZE_BYTES", "512"))
BOOT_IMAGE = os.getenv("BOOT_IMAGE", "")
BOOT_CS_TIMEOUT_CYCLES = int(os.getenv("BOOT_CS_TIMEOUT_CYCLES", "100000"))
SPI_EDGE_TIMEOUT_CYCLES = int(os.getenv("SPI_EDGE_TIMEOUT_CYCLES", "100000"))
SPI_ACTIVITY_TIMEOUT_CYCLES = int(os.getenv("SPI_ACTIVITY_TIMEOUT_CYCLES", "200000"))


# -----------------------------------------------------------------------------
# External bidirectional pad drive helpers
# -----------------------------------------------------------------------------
#
# Important:
# The testbench must only drive true external input pads.
# For output pads, it must drive Z so the DUT can own the pad.
#
# The string representation of a vector is MSB-first, while the Verilog pad index
# is numeric from [0] upward. Therefore physical HDL pad i maps to string index:
#
#     width - 1 - i
#
# This is why all external drive/read helpers go through pad_string_index().
# -----------------------------------------------------------------------------

_external_drive_state = {}


def get_bidir_width(dut):
    return len(dut.bidir_PAD.value)


def pad_string_index(dut, pin):
    width = get_bidir_width(dut)
    assert 0 <= pin < width, f"Pad pin {pin} is outside bidir_PAD width {width}"
    return width - 1 - pin


def logic_char(value):
    if value is None:
        return "z"

    if isinstance(value, str):
        val = value.lower()
        if val in ("z", "x"):
            return val
        if val in ("0", "1"):
            return val
        raise ValueError(f"Unsupported logic value string: {value}")

    return "1" if int(value) else "0"


def reset_external_pad_drives(dut):
    width = get_bidir_width(dut)
    _external_drive_state[id(dut)] = ["z"] * width
    dut.bidir_PAD.value = "z" * width


def set_external_pad(dut, pin, value):
    width = get_bidir_width(dut)

    if id(dut) not in _external_drive_state:
        _external_drive_state[id(dut)] = ["z"] * width

    idx = pad_string_index(dut, pin)
    _external_drive_state[id(dut)][idx] = logic_char(value)
    dut.bidir_PAD.value = "".join(_external_drive_state[id(dut)])


def drive_bidir_inputs(dut, boot_miso="z", debug_mode=0, dft_in=0):
    """Drive only the external input pads, release all other bidir pads."""
    reset_external_pad_drives(dut)
    set_external_pad(dut, PIN_BOOT_MISO, boot_miso)
    set_external_pad(dut, PIN_DEBUG_MODE, debug_mode)
    set_external_pad(dut, PIN_DFT_IN, dft_in)


def drive_control_inputs(dut, debug_mode=None, dft_in=None):
    """Update debug/dft control inputs without disturbing flash MISO."""
    if debug_mode is not None:
        set_external_pad(dut, PIN_DEBUG_MODE, debug_mode)

    if dft_in is not None:
        set_external_pad(dut, PIN_DFT_IN, dft_in)


def drive_flash_miso(dut, value):
    """Drive only the external SPI flash MISO pad."""
    set_external_pad(dut, PIN_BOOT_MISO, value)


def release_flash_miso(dut):
    drive_flash_miso(dut, "z")


def read_bidir_pin(dut, pin):
    """Read a pad using the chip's physical HDL pad index."""
    idx = pad_string_index(dut, pin)
    return str(dut.bidir_PAD.value)[idx].lower()


def is_known_01(value):
    return value in ("0", "1")


def assert_pad_known(dut, pin, name):
    val = read_bidir_pin(dut, pin)
    assert is_known_01(val), f"{name} must be 0/1, got {val}"


def assert_pad_value(dut, pin, expected, name):
    actual = read_bidir_pin(dut, pin)
    expected = logic_char(expected)
    assert actual == expected, (
        f"{name} expected {expected}, got {actual}. "
        f"Full bidir_PAD={dut.bidir_PAD.value}"
    )


def check_pin_map(dut):
    width = get_bidir_width(dut)
    pins = {
        "PIN_TRAP_LED": PIN_TRAP_LED,
        "PIN_BOOT_SCLK": PIN_BOOT_SCLK,
        "PIN_BOOT_MOSI": PIN_BOOT_MOSI,
        "PIN_BOOT_CS": PIN_BOOT_CS,
        "PIN_DFT_OUT": PIN_DFT_OUT,
        "PIN_BOOT_MISO": PIN_BOOT_MISO,
        "PIN_DEBUG_MODE": PIN_DEBUG_MODE,
        "PIN_DFT_IN": PIN_DFT_IN,
    }

    for name, pin in pins.items():
        assert 0 <= pin < width, f"{name}={pin} outside bidir_PAD width {width}"

    cocotb.log.info(f"bidir_PAD width = {width}")
    cocotb.log.info(f"Pin map = {pins}")


# -----------------------------------------------------------------------------
# Boot image / SPI flash model
# -----------------------------------------------------------------------------

def load_boot_image():
    """Load external binary flash image, or fall back to RISC-V NOPs."""
    if BOOT_IMAGE:
        data = Path(BOOT_IMAGE).read_bytes()
    else:
        # RISC-V NOP = 0x00000013, little-endian byte order.
        data = bytes([0x13, 0x00, 0x00, 0x00]) * (BOOT_SIZE_BYTES // 4)

    if len(data) < BOOT_SIZE_BYTES:
        data += bytes([0x00] * (BOOT_SIZE_BYTES - len(data)))

    return data[:BOOT_SIZE_BYTES]


async def wait_for_condition(dut, condition, timeout_cycles, message):
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk_PAD)
        if condition():
            return
    assert False, message


async def wait_for_pad_value(dut, pin, target, timeout_cycles):
    target = logic_char(target)

    await wait_for_condition(
        dut,
        lambda: read_bidir_pin(dut, pin) == target,
        timeout_cycles,
        f"Timed out waiting for pad {pin} to become {target}",
    )


async def wait_for_spi_sclk_edge(
    dut,
    rising=True,
    timeout_cycles=SPI_EDGE_TIMEOUT_CYCLES,
):
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


async def count_pad_transitions(dut, pin, cycles):
    transitions = 0
    prev = read_bidir_pin(dut, pin)

    for _ in range(cycles):
        await RisingEdge(dut.clk_PAD)
        cur = read_bidir_pin(dut, pin)

        if prev in ("0", "1") and cur in ("0", "1") and prev != cur:
            transitions += 1

        prev = cur

    return transitions


class SpiFlashResponder:
    """
    Simple SPI flash responder for housekeeping boot.

    Expected transaction:
    - flash CS goes low
    - DUT sends 8-bit command + 24-bit address on MOSI
    - flash returns BOOT_SIZE_BYTES on MISO, MSB first
    """

    def __init__(self, dut):
        self.dut = dut
        self.flash_data = load_boot_image()

        self.cs_asserted = False
        self.command_addr = None
        self.command_bits_seen = 0
        self.bytes_driven = 0
        self.completed = False

    async def run(self):
        dut = self.dut

        await wait_for_pad_value(
            dut,
            PIN_BOOT_CS,
            "0",
            timeout_cycles=BOOT_CS_TIMEOUT_CYCLES,
        )

        self.cs_asserted = True
        drive_flash_miso(dut, 0)

        command_addr = 0

        for _ in range(32):
            if read_bidir_pin(dut, PIN_BOOT_CS) == "1":
                release_flash_miso(dut)
                self.completed = True
                return

            await wait_for_spi_sclk_edge(dut, rising=True)
            mosi = read_bidir_pin(dut, PIN_BOOT_MOSI)

            assert mosi in ("0", "1"), f"PIN_BOOT_MOSI became {mosi}"

            command_addr = (command_addr << 1) | (1 if mosi == "1" else 0)
            self.command_bits_seen += 1

        self.command_addr = command_addr
        dut._log.info(f"SPI flash command/address = 0x{command_addr:08x}")

        for byte_val in self.flash_data:
            if read_bidir_pin(dut, PIN_BOOT_CS) == "1":
                break

            for bit in range(7, -1, -1):
                if read_bidir_pin(dut, PIN_BOOT_CS) == "1":
                    break

                await wait_for_spi_sclk_edge(dut, rising=False)
                drive_flash_miso(dut, (byte_val >> bit) & 1)

            self.bytes_driven += 1

        # If the DUT keeps CS low after the provided image, keep MISO released
        # rather than driving stale data forever.
        release_flash_miso(dut)

        for _ in range(SPI_ACTIVITY_TIMEOUT_CYCLES):
            if read_bidir_pin(dut, PIN_BOOT_CS) == "1":
                self.completed = True
                dut._log.info("SPI flash transaction completed")
                return
            await RisingEdge(dut.clk_PAD)

        dut._log.info(
            "SPI flash responder served the image; CS remained low after timeout"
        )
        self.completed = True


# -----------------------------------------------------------------------------
# Startup/reset helpers
# -----------------------------------------------------------------------------

def has_handle(dut, name):
    try:
        getattr(dut, name)
        return True
    except AttributeError:
        return False


async def enable_power_if_present(dut):
    if has_handle(dut, "VDD"):
        dut.VDD.value = 1

    if has_handle(dut, "VSS"):
        dut.VSS.value = 0

    await Timer(1, "ns")


async def start_clock(clock):
    period_ns = 1000.0 / CLOCK_FREQ_MHZ
    cocotb.log.info(
        f"Starting chip clock at {CLOCK_FREQ_MHZ} MHz "
        f"({period_ns} ns period)"
    )

    c = Clock(clock, period_ns, "ns")
    cocotb.start_soon(c.start())


async def apply_reset(dut, reset_time_ns=RESET_TIME_NS):
    cocotb.log.info("Reset asserted")
    dut.rst_n_PAD.value = 0
    await Timer(reset_time_ns, "ns")

    cocotb.log.info("Reset deasserted")
    dut.rst_n_PAD.value = 1

    await ClockCycles(dut.clk_PAD, 5)


async def start_up(
    dut,
    debug_mode=0,
    dft_in=0,
    boot_miso="z",
    start_flash=False,
):
    check_pin_map(dut)

    await enable_power_if_present(dut)

    drive_bidir_inputs(
        dut,
        boot_miso=boot_miso,
        debug_mode=debug_mode,
        dft_in=dft_in,
    )

    await start_clock(dut.clk_PAD)

    flash = None
    if start_flash:
        flash = SpiFlashResponder(dut)
        cocotb.start_soon(flash.run())

    await apply_reset(dut)

    return flash


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------

@cocotb.test()
async def test_00_pin_map_and_basic_reset_smoke(dut):
    """
    Basic chip-top smoke test.

    Checks:
    - bidir pad width is large enough for the expected pin map
    - reset can be applied/released
    - trap LED is known and low after reset
    - DFT output is known after reset
    """
    await start_up(dut, debug_mode=1, dft_in=0)

    await ClockCycles(dut.clk_PAD, 10)

    assert_pad_value(dut, PIN_TRAP_LED, 0, "PIN_TRAP_LED")
    assert_pad_known(dut, PIN_DFT_OUT, "PIN_DFT_OUT")


@cocotb.test()
async def test_dft_passthrough_all_debug_modes(dut):
    """
    Check DFT input/output pad plumbing.

    The chip_core currently passes dft_in through to dft_out.
    This is checked in both normal mode and debug mode.
    """
    await start_up(dut, debug_mode=0, dft_in=0)

    for debug_mode in (0, 1):
        drive_control_inputs(dut, debug_mode=debug_mode)
        await ClockCycles(dut.clk_PAD, 3)

        for dft_in in (0, 1, 0, 1):
            drive_control_inputs(dut, dft_in=dft_in)
            await ClockCycles(dut.clk_PAD, 4)

            assert_pad_value(
                dut,
                PIN_DFT_OUT,
                dft_in,
                f"PIN_DFT_OUT with debug_mode={debug_mode}, dft_in={dft_in}",
            )


@cocotb.test()
async def test_dft_passthrough_after_repeated_resets(dut):
    """
    Check that reset does not break the DFT input/output path.
    """
    await start_up(dut, debug_mode=1, dft_in=0)

    for reset_iter in range(3):
        cocotb.log.info(f"Reset recovery iteration {reset_iter}")

        dut.rst_n_PAD.value = 0
        await ClockCycles(dut.clk_PAD, 20)

        dut.rst_n_PAD.value = 1
        await ClockCycles(dut.clk_PAD, 5)

        drive_control_inputs(dut, debug_mode=1, dft_in=1)
        await ClockCycles(dut.clk_PAD, 4)
        assert_pad_value(dut, PIN_DFT_OUT, 1, "PIN_DFT_OUT after reset")

        drive_control_inputs(dut, debug_mode=1, dft_in=0)
        await ClockCycles(dut.clk_PAD, 4)
        assert_pad_value(dut, PIN_DFT_OUT, 0, "PIN_DFT_OUT after reset")

        assert_pad_value(dut, PIN_TRAP_LED, 0, "PIN_TRAP_LED after reset")


@cocotb.test()
async def test_trap_led_stays_low_across_control_inputs(dut):
    """
    The current chip_top/chip_core tie-off keeps trap_led low.

    Sweep the externally visible control inputs and confirm trap does not assert.
    """
    await start_up(dut, debug_mode=0, dft_in=0)

    for debug_mode in (0, 1):
        for dft_in in (0, 1):
            for miso in (0, 1, "z"):
                drive_control_inputs(
                    dut,
                    debug_mode=debug_mode,
                    dft_in=dft_in,
                )
                drive_flash_miso(dut, miso)

                await ClockCycles(dut.clk_PAD, 5)

                assert_pad_value(
                    dut,
                    PIN_TRAP_LED,
                    0,
                    (
                        "PIN_TRAP_LED "
                        f"debug={debug_mode} dft={dft_in} miso={miso}"
                    ),
                )


@cocotb.test()
async def test_external_input_pads_accept_values_without_contention(dut):
    """
    Drive the external input pads through 0/1/Z patterns.

    If the DUT incorrectly drives one of these supposed input pads,
    the resolved pad value can become X, so this catches basic contention.
    """
    await start_up(dut, debug_mode=0, dft_in=0, boot_miso="z")

    patterns = [
        (0, 0, 0),
        (0, 1, 1),
        (1, 0, "z"),
        (1, 1, 0),
        (0, 0, 1),
    ]

    for debug_mode, dft_in, miso in patterns:
        drive_control_inputs(dut, debug_mode=debug_mode, dft_in=dft_in)
        drive_flash_miso(dut, miso)

        await ClockCycles(dut.clk_PAD, 3)

        assert_pad_value(dut, PIN_DEBUG_MODE, debug_mode, "PIN_DEBUG_MODE")
        assert_pad_value(dut, PIN_DFT_IN, dft_in, "PIN_DFT_IN")

        if miso != "z":
            assert_pad_value(dut, PIN_BOOT_MISO, miso, "PIN_BOOT_MISO")


@cocotb.test()
async def test_debug_mode_tristates_boot_spi_outputs(dut):
    """
    In debug mode, boot SPI output pads should not be actively driven.

    chip_core drives boot SCLK/MOSI/CS only when debug_mode is low.
    With debug_mode high, these pads should resolve to Z because the testbench
    also releases them.
    """
    await start_up(dut, debug_mode=1, dft_in=0, boot_miso="z")

    await ClockCycles(dut.clk_PAD, 20)

    for pin, name in (
        (PIN_BOOT_SCLK, "PIN_BOOT_SCLK"),
        (PIN_BOOT_MOSI, "PIN_BOOT_MOSI"),
        (PIN_BOOT_CS, "PIN_BOOT_CS"),
    ):
        val = read_bidir_pin(dut, pin)
        assert val == "z", f"{name} should be Z in debug mode, got {val}"


@cocotb.test(timeout_time=20, timeout_unit="ms")
async def test_boot_spi_pads_drive_in_normal_mode(dut):
    """
    In normal mode, housekeeping boot should drive the SPI flash pads.

    Checks:
    - CS eventually asserts low
    - SCLK/MOSI/CS are known 0/1, not X/Z, once boot starts
    - SCLK actually toggles after CS assertion
    """
    await start_up(dut, debug_mode=0, dft_in=0, boot_miso="z", start_flash=True)

    await wait_for_pad_value(
        dut,
        PIN_BOOT_CS,
        "0",
        timeout_cycles=BOOT_CS_TIMEOUT_CYCLES,
    )

    for pin, name in (
        (PIN_BOOT_SCLK, "PIN_BOOT_SCLK"),
        (PIN_BOOT_MOSI, "PIN_BOOT_MOSI"),
        (PIN_BOOT_CS, "PIN_BOOT_CS"),
    ):
        assert_pad_known(dut, pin, name)

    sclk_transitions = await count_pad_transitions(dut, PIN_BOOT_SCLK, 2000)
    assert sclk_transitions > 0, "PIN_BOOT_SCLK did not toggle after CS assertion"


@cocotb.test(timeout_time=20, timeout_unit="ms")
async def test_boot_spi_flash_command_is_captured(dut):
    """
    Run the SPI flash responder and confirm the DUT sends a 32-bit command/address.

    This does not enforce a specific opcode, because the boot FSM may change.
    It verifies that the top-level SPI wiring is alive enough to transmit
    a complete command/address phase.
    """
    flash = await start_up(
        dut,
        debug_mode=0,
        dft_in=0,
        boot_miso="z",
        start_flash=True,
    )

    await wait_for_condition(
        dut,
        lambda: flash.command_bits_seen >= 32,
        timeout_cycles=SPI_ACTIVITY_TIMEOUT_CYCLES,
        message="SPI flash command/address phase was not fully captured",
    )

    assert flash.command_addr is not None
    assert flash.command_bits_seen == 32

    opcode = (flash.command_addr >> 24) & 0xFF
    address = flash.command_addr & 0x00FF_FFFF

    dut._log.info(
        f"Captured SPI boot opcode=0x{opcode:02x}, address=0x{address:06x}"
    )

    await ClockCycles(dut.clk_PAD, 20)

    for pin, name in (
        (PIN_BOOT_SCLK, "PIN_BOOT_SCLK"),
        (PIN_BOOT_MOSI, "PIN_BOOT_MOSI"),
        (PIN_BOOT_CS, "PIN_BOOT_CS"),
    ):
        val = read_bidir_pin(dut, pin)
        assert val in ("0", "1"), f"{name} became {val} during boot"


@cocotb.test(timeout_time=20, timeout_unit="ms")
async def test_boot_spi_flash_receives_miso_data(dut):
    """
    Confirm that the flash responder drives data back to the DUT on MISO.

    The pass condition is not full firmware execution. The pass condition is:
    - DUT asserts CS
    - DUT sends a command/address
    - testbench flash drives at least a few response bytes
    - trap LED remains low during this smoke run
    """
    flash = await start_up(
        dut,
        debug_mode=0,
        dft_in=0,
        boot_miso="z",
        start_flash=True,
    )

    await wait_for_condition(
        dut,
        lambda: flash.bytes_driven >= 8,
        timeout_cycles=SPI_ACTIVITY_TIMEOUT_CYCLES,
        message="SPI flash responder did not drive at least 8 bytes",
    )

    assert flash.cs_asserted
    assert flash.command_bits_seen == 32
    assert flash.bytes_driven >= 8

    await ClockCycles(dut.clk_PAD, 50)

    assert_pad_value(dut, PIN_TRAP_LED, 0, "PIN_TRAP_LED during SPI boot")


@cocotb.test()
async def test_boot_spi_outputs_disable_when_debug_mode_is_asserted_late(dut):
    """
    Start in normal mode, then assert debug_mode and confirm boot outputs release.

    This checks that debug_mode dynamically controls the boot pad OEs.
    """
    await start_up(dut, debug_mode=0, dft_in=0, boot_miso="z")

    await ClockCycles(dut.clk_PAD, 20)

    drive_control_inputs(dut, debug_mode=1)
    await ClockCycles(dut.clk_PAD, 10)

    for pin, name in (
        (PIN_BOOT_SCLK, "PIN_BOOT_SCLK"),
        (PIN_BOOT_MOSI, "PIN_BOOT_MOSI"),
        (PIN_BOOT_CS, "PIN_BOOT_CS"),
    ):
        val = read_bidir_pin(dut, pin)
        assert val == "z", f"{name} should release after debug_mode=1, got {val}"


@cocotb.test()
async def test_boot_spi_outputs_reenable_after_debug_mode_is_cleared(dut):
    """
    Start in debug mode, clear debug_mode, and confirm boot outputs become driven.
    """
    await start_up(dut, debug_mode=1, dft_in=0, boot_miso="z")

    await ClockCycles(dut.clk_PAD, 20)

    drive_control_inputs(dut, debug_mode=0)
    await ClockCycles(dut.clk_PAD, 20)

    for pin, name in (
        (PIN_BOOT_SCLK, "PIN_BOOT_SCLK"),
        (PIN_BOOT_MOSI, "PIN_BOOT_MOSI"),
        (PIN_BOOT_CS, "PIN_BOOT_CS"),
    ):
        val = read_bidir_pin(dut, pin)
        assert val in ("0", "1"), f"{name} should be driven after debug_mode=0, got {val}"


@cocotb.test(timeout_time=20, timeout_unit="ms")
async def test_long_boot_smoke_no_trap_or_unknown_outputs(dut):
    """
    Longer chip-top smoke test.

    Runs with the flash responder active and checks that critical observable pads
    remain sane over time.
    """
    await start_up(dut, debug_mode=0, dft_in=0, boot_miso="z", start_flash=True)

    for sample in range(20):
        await ClockCycles(dut.clk_PAD, 250)

        assert_pad_value(dut, PIN_TRAP_LED, 0, "PIN_TRAP_LED long boot")

        # DFT output should remain known because dft_in is driven.
        assert_pad_known(dut, PIN_DFT_OUT, "PIN_DFT_OUT long boot")

        # In normal mode, boot SPI outputs should be driven, not X/Z.
        for pin, name in (
            (PIN_BOOT_SCLK, "PIN_BOOT_SCLK"),
            (PIN_BOOT_MOSI, "PIN_BOOT_MOSI"),
            (PIN_BOOT_CS, "PIN_BOOT_CS"),
        ):
            val = read_bidir_pin(dut, pin)
            assert val in ("0", "1"), (
                f"{name} became {val} during long boot sample {sample}"
            )


@cocotb.test()
async def test_control_input_stress_sequence(dut):
    """
    Deterministic stress sequence for debug_mode, dft_in, and boot_miso.

    This is not random so failures are reproducible.
    """
    await start_up(dut, debug_mode=1, dft_in=0, boot_miso="z")

    sequence = [
        {"debug": 1, "dft": 0, "miso": "z"},
        {"debug": 1, "dft": 1, "miso": 0},
        {"debug": 0, "dft": 1, "miso": 1},
        {"debug": 0, "dft": 0, "miso": 0},
        {"debug": 1, "dft": 0, "miso": "z"},
        {"debug": 0, "dft": 1, "miso": 1},
        {"debug": 1, "dft": 1, "miso": "z"},
    ]

    for idx, item in enumerate(sequence):
        drive_control_inputs(
            dut,
            debug_mode=item["debug"],
            dft_in=item["dft"],
        )
        drive_flash_miso(dut, item["miso"])

        await ClockCycles(dut.clk_PAD, 6)

        assert_pad_value(
            dut,
            PIN_DFT_OUT,
            item["dft"],
            f"PIN_DFT_OUT stress index {idx}",
        )

        assert_pad_value(
            dut,
            PIN_TRAP_LED,
            0,
            f"PIN_TRAP_LED stress index {idx}",
        )


# -----------------------------------------------------------------------------
# Runner
# -----------------------------------------------------------------------------

def chip_top_runner():
    proj_path = Path(__file__).resolve().parent

    sources = []
    defines = {f"SLOT_{slot.upper()}": True}
    includes = [proj_path / "../src/"]
    build_args = []

    scl_dir = pdk_root / pdk / "libs.ref" / scl / "verilog"
    io_dir = pdk_root / pdk / "libs.ref/gf180mcu_fd_io/verilog"
    sram_dir = pdk_root / pdk / "libs.ref/gf180mcu_fd_ip_sram/verilog"

    if gl:
        # Gate-level simulation (functional or SDF-annotated timing).
        defines = {
            f"SLOT_{slot.upper()}": True,
            "FUNCTIONAL": True,
            "USE_POWER_PINS": True,
        }

        sources += [
            # UDP primitives must be compiled before the SCL model.
            scl_dir / "primitives.v",
            scl_dir / f"{scl}.v",

            # Powered post-layout netlist.
            proj_path / f"../final/pnl/{hdl_toplevel}.pnl.v",
        ]

        if sdf:
            if not sdf_file:
                raise RuntimeError(
                    "SDF=1 requires SDF_FILE to be set. "
                    "Run: make sim-sdf SDF_CORNER=<corner>"
                )
            # Inject the SDF annotation shim so iverilog picks up the delays.
            sources += [proj_path / "sdf_annotate.v"]
            defines["SDF_FILE"] = f'"{sdf_file}"'

    else:
        # RTL simulation.
        sources += [
            proj_path / "../src/chip_top.sv",
            proj_path / "../src/chip_core.sv",

            proj_path / "../src/directory_controller/directory_controller.sv",

            proj_path / "../src/arb/wrr_arbiter.sv",

            proj_path / "../src/interposer_interface/directory_interface.sv",
            proj_path / "../src/interposer_interface/tserializer.sv",
            proj_path / "../src/interposer_interface/rserializer.sv",
            proj_path / "../src/interposer_interface/lossy_pipe_stage.sv",

            proj_path / "../src/mem_ctrl/mem2048x32.sv",
            proj_path / "../src/mem_ctrl/mem512x32.sv",
            proj_path / "../src/mem_ctrl/directory_mem.sv",
            proj_path / "../src/mem_ctrl/mem64x8.sv",

            proj_path / "../src/housekeeping/boot_fsm.sv",
            proj_path / "../src/housekeeping/housekeeping_top.sv",
            proj_path / "../src/housekeeping/spi_engine.sv",
        ]

    sources += [
        # IO pad models.
        io_dir / "gf180mcu_fd_io.v",
        io_dir / "gf180mcu_ws_io.v",

        # SRAM macro models.
        sram_dir / "gf180mcu_fd_ip_sram__sram512x8m8wm1.v",
        sram_dir / "gf180mcu_fd_ip_sram__sram64x8m8wm1.v",

        # Custom IP required by chip_top.
        proj_path / "../ip/gf180mcu_ws_ip__id/vh/gf180mcu_ws_ip__id.v",
        proj_path / "../ip/gf180mcu_ws_ip__logo/vh/gf180mcu_ws_ip__logo.v",
    ]

    if sim == "icarus":
        build_args = ["-g2012"]

    if sim == "verilator":
        build_args = [
            "--timing",
            "--trace",
            "--trace-fst",
            "--trace-structs",
        ]

    plusargs = []
    if sdf:
        plusargs += ["+sdf_verbose", "+maxdelays"]

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

    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module="chip_top_tb",
        plusargs=plusargs,
        waves=True,
    )


if __name__ == "__main__":
    chip_top_runner()
