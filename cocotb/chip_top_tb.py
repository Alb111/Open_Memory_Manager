# SPDX-FileCopyrightText: © 2025 Project Template Contributors
# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, ClockCycles, RisingEdge, FallingEdge
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

# The actual chip target is 35 MHz = 28.571 ns period.
CLOCK_FREQ_MHZ = float(os.getenv("CLOCK_FREQ_MHZ", "35"))
BOOT_PASS_WAIT_NS = 25
RESET_TIME_NS = int(os.getenv("RESET_TIME_NS", "1000"))

# Pin configurations mapping back to the chip top pad frame.
SER_PINS = int(os.getenv("SER_PINS", "9"))

PIN_DEBUG_MODE = int(os.getenv("DEBUG_MODE_ID", "0"))
PIN_BOOT_PASS_EN = int(os.getenv("BOOT_PASS_EN_ID", "1"))
PIN_BOOT_CS = int(os.getenv("FLASH_CSB_ID", "2"))
PIN_BOOT_MISO = int(os.getenv("SPI_MISO_ID", "3"))
PIN_BOOT_MOSI = int(os.getenv("SPI_MOSI_ID", "4"))
PIN_BOOT_SCLK = int(os.getenv("SPI_SCLK_ID", "5"))

PIN_C0_REQ_I = int(os.getenv("C0_REQ_I_ID", "6"))
PIN_C0_SERIAL_I_START = int(os.getenv("C0_SERIAL_I_START_ID", "7"))
PIN_C0_REQ_O = int(os.getenv("C0_REQ_O_ID", "16"))
PIN_C0_SERIAL_O_START = int(os.getenv("C0_SERIAL_O_START_ID", "17"))
PIN_C0_BOOT_DONE = int(os.getenv("C0_BOOT_DONE", "26"))
PIN_C0_DEBUG_MODE = int(os.getenv("C0_DEBUG_MODE_ID", "27"))
PIN_C0_RST_N = int(os.getenv("C0_RST_N_ID", "28"))
PIN_C0_CLK = int(os.getenv("C0_CLK_ID", "29"))
PIN_C0_TRAP_I = int(os.getenv("C0_TRAP_I_ID", "65"))
PIN_C0_TRAP_O = int(os.getenv("C0_TRAP_O_ID", "64"))

PIN_DFT_START = int(os.getenv("DFT_START_ID", "32"))
DFT_PINS = int(os.getenv("DFT_PINS", "8"))

PIN_C1_REQ_I = int(os.getenv("C1_REQ_I_ID", "40"))
PIN_C1_SERIAL_I_START = int(os.getenv("C1_SERIAL_I_START_ID", "41"))
PIN_C1_REQ_O = int(os.getenv("C1_REQ_O_ID", "50"))
PIN_C1_SERIAL_O_START = int(os.getenv("C1_SERIAL_O_START_ID", "51"))
PIN_C1_BOOT_DONE = int(os.getenv("C1_BOOT_DONE", "60"))
PIN_C1_DEBUG_MODE = int(os.getenv("C1_DEBUG_MODE_ID", "61"))
PIN_C1_RST_N = int(os.getenv("C1_RST_N_ID", "62"))
PIN_C1_CLK = int(os.getenv("C1_CLK_ID", "63"))
PIN_C1_TRAP_I = int(os.getenv("C1_TRAP_I_ID", "31"))
PIN_C1_TRAP_O = int(os.getenv("C1_TRAP_O_ID", "30"))

SPI_OUTPUT_PINS = (
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


def set_external_bus(dut, start_pin, width, value):
    value = int(value)
    for bit in range(width):
        set_external_pad(dut, start_pin + bit, (value >> bit) & 1)


def drive_dft_inputs(dut, value=0):
    set_external_bus(dut, PIN_DFT_START, DFT_PINS, value)


def drive_bidir_inputs(
    dut,
    boot_miso="z",
    debug_mode=0,
    boot_pass_en=0,
    c0_req_i=0,
    c0_serial_i=0,
    c0_trap_i=0,
    c1_req_i=0,
    c1_serial_i=0,
    c1_trap_i=0,
):
    """Drive only the external input pads, release all other bidir pads."""
    reset_external_pad_drives(dut)
    set_external_pad(dut, PIN_BOOT_MISO, boot_miso)
    set_external_pad(dut, PIN_DEBUG_MODE, debug_mode)
    set_external_pad(dut, PIN_BOOT_PASS_EN, boot_pass_en)
    set_external_pad(dut, PIN_C0_REQ_I, c0_req_i)
    set_external_bus(dut, PIN_C0_SERIAL_I_START, SER_PINS, c0_serial_i)
    set_external_pad(dut, PIN_C0_TRAP_I, c0_trap_i)
    set_external_pad(dut, PIN_C1_REQ_I, c1_req_i)
    set_external_bus(dut, PIN_C1_SERIAL_I_START, SER_PINS, c1_serial_i)
    set_external_pad(dut, PIN_C1_TRAP_I, c1_trap_i)
    drive_dft_inputs(dut)


def drive_control_inputs(
    dut,
    debug_mode=None,
    boot_pass_en=None,
    c0_req_i=None,
    c0_serial_i=None,
    c0_trap_i=None,
    c1_req_i=None,
    c1_serial_i=None,
    c1_trap_i=None,
):
    """Update externally driven control inputs without disturbing flash MISO."""
    if debug_mode is not None:
        set_external_pad(dut, PIN_DEBUG_MODE, debug_mode)

    if boot_pass_en is not None:
        set_external_pad(dut, PIN_BOOT_PASS_EN, boot_pass_en)

    if c0_req_i is not None:
        set_external_pad(dut, PIN_C0_REQ_I, c0_req_i)

    if c0_serial_i is not None:
        set_external_bus(dut, PIN_C0_SERIAL_I_START, SER_PINS, c0_serial_i)

    if c0_trap_i is not None:
        set_external_pad(dut, PIN_C0_TRAP_I, c0_trap_i)

    if c1_req_i is not None:
        set_external_pad(dut, PIN_C1_REQ_I, c1_req_i)

    if c1_serial_i is not None:
        set_external_bus(dut, PIN_C1_SERIAL_I_START, SER_PINS, c1_serial_i)

    if c1_trap_i is not None:
        set_external_pad(dut, PIN_C1_TRAP_I, c1_trap_i)


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
        "PIN_DEBUG_MODE": PIN_DEBUG_MODE,
        "PIN_BOOT_PASS_EN": PIN_BOOT_PASS_EN,
        "PIN_BOOT_CS": PIN_BOOT_CS,
        "PIN_BOOT_MISO": PIN_BOOT_MISO,
        "PIN_BOOT_MOSI": PIN_BOOT_MOSI,
        "PIN_BOOT_SCLK": PIN_BOOT_SCLK,
        "PIN_C0_REQ_O": PIN_C0_REQ_O,
        "PIN_C0_REQ_I": PIN_C0_REQ_I,
        "PIN_C0_BOOT_DONE": PIN_C0_BOOT_DONE,
        "PIN_C0_DEBUG_MODE": PIN_C0_DEBUG_MODE,
        "PIN_C0_RST_N": PIN_C0_RST_N,
        "PIN_C0_CLK": PIN_C0_CLK,
        "PIN_C0_TRAP_I": PIN_C0_TRAP_I,
        "PIN_C0_TRAP_O": PIN_C0_TRAP_O,
        "PIN_DFT_START": PIN_DFT_START,
        "PIN_C1_REQ_O": PIN_C1_REQ_O,
        "PIN_C1_REQ_I": PIN_C1_REQ_I,
        "PIN_C1_BOOT_DONE": PIN_C1_BOOT_DONE,
        "PIN_C1_DEBUG_MODE": PIN_C1_DEBUG_MODE,
        "PIN_C1_RST_N": PIN_C1_RST_N,
        "PIN_C1_CLK": PIN_C1_CLK,
        "PIN_C1_TRAP_I": PIN_C1_TRAP_I,
        "PIN_C1_TRAP_O": PIN_C1_TRAP_O,
    }

    for name, pin in pins.items():
        assert 0 <= pin < width, f"{name}={pin} outside bidir_PAD width {width}"

    ranges = {
        "PIN_C0_SERIAL_O": (PIN_C0_SERIAL_O_START, SER_PINS),
        "PIN_C0_SERIAL_I": (PIN_C0_SERIAL_I_START, SER_PINS),
        "PIN_DFT": (PIN_DFT_START, DFT_PINS),
        "PIN_C1_SERIAL_O": (PIN_C1_SERIAL_O_START, SER_PINS),
        "PIN_C1_SERIAL_I": (PIN_C1_SERIAL_I_START, SER_PINS),
    }

    for name, (start, count) in ranges.items():
        assert 0 <= start < width, f"{name} start {start} outside width {width}"
        end = start + count - 1
        assert end < width, f"{name} end {end} outside bidir_PAD width {width}"

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
    # Cocotb requires a period that is exactly representable at the simulator's
    # 1 ps precision. Round to the nearest picosecond so frequencies such as
    # 35 MHz do not produce an unrepresentable fractional-nanosecond period.
    # Use an even number of picoseconds so Cocotb can generate a 50% duty
    # cycle without introducing a sub-picosecond half-period.
    period_ps = 2 * round(500_000 / CLOCK_FREQ_MHZ)
    period_ns = period_ps / 1000
    cocotb.log.info(
        f"Starting chip clock at {CLOCK_FREQ_MHZ} MHz "
        f"({period_ns} ns period)"
    )

    c = Clock(clock, period_ps, unit="ps")
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
    boot_pass_en=0,
    boot_miso="z",
    start_flash=False,
):
    check_pin_map(dut)

    await enable_power_if_present(dut)

    drive_bidir_inputs(
        dut,
        boot_miso=boot_miso,
        debug_mode=debug_mode,
        boot_pass_en=boot_pass_en,
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

def read_bidir_bus(dut, start_pin, width):
    value = 0
    for bit in range(width):
        pin_val = read_bidir_pin(dut, start_pin + bit)
        assert pin_val in ("0", "1"), (
            f"Pad {start_pin + bit} expected 0/1 while reading bus, got {pin_val}"
        )
        value |= (1 if pin_val == "1" else 0) << bit
    return value


def assert_bidir_bus_value(dut, start_pin, width, expected, name):
    actual = read_bidir_bus(dut, start_pin, width)
    mask = (1 << width) - 1
    assert actual == (expected & mask), (
        f"{name} expected 0x{expected & mask:x}, got 0x{actual:x}. "
        f"Full bidir_PAD={dut.bidir_PAD.value}"
    )


async def assert_pad_toggles(dut, pin, name, samples=12, sample_step_ns=10):
    seen = set()
    for _ in range(samples):
        await Timer(sample_step_ns, "ns")
        val = read_bidir_pin(dut, pin)
        if val in ("0", "1"):
            seen.add(val)

    assert seen == {"0", "1"}, (
        f"{name} should toggle through 0 and 1, saw {sorted(seen)}. "
        f"Full bidir_PAD={dut.bidir_PAD.value}"
    )


@cocotb.test()
async def test_00_pin_map_and_basic_reset_smoke(dut):
    """
    Basic chip-top smoke test.

    Checks:
    - bidir pad width is large enough for the expected pin map
    - reset can be applied/released
    - top-chip debug/reset/clock outputs are driven
    """
    await start_up(dut, debug_mode=1, boot_pass_en=0)

    await ClockCycles(dut.clk_PAD, 10)

    assert_pad_value(dut, PIN_C0_DEBUG_MODE, 1, "PIN_C0_DEBUG_MODE")
    assert_pad_value(dut, PIN_C1_DEBUG_MODE, 1, "PIN_C1_DEBUG_MODE")
    assert_pad_value(dut, PIN_C0_RST_N, 1, "PIN_C0_RST_N")
    assert_pad_value(dut, PIN_C1_RST_N, 1, "PIN_C1_RST_N")
    assert_pad_known(dut, PIN_C0_CLK, "PIN_C0_CLK")
    assert_pad_known(dut, PIN_C1_CLK, "PIN_C1_CLK")


@cocotb.test()
async def test_reset_deassertion_is_synchronized(dut):
    """Raw reset asserts immediately and releases after two clock edges."""
    await enable_power_if_present(dut)
    drive_bidir_inputs(dut, debug_mode=1, boot_pass_en=0)
    dut.clk_PAD.value = 0
    dut.rst_n_PAD.value = 0
    await start_clock(dut.clk_PAD)

    await ClockCycles(dut.clk_PAD, 2)
    assert int(dut.rst_n_sync.value) == 0

    # Move deassertion away from the active edge. The first edge fills the
    # synchronizer; the second releases every downstream reset consumer.
    await Timer(2, "ns")
    dut.rst_n_PAD.value = 1

    for _ in range(4):
        await RisingEdge(dut.clk_PAD)
        await Timer(1, "ps")
        if int(dut.reset_sync_ff.value) & 1:
            break
    else:
        raise AssertionError("reset synchronizer first stage never released")

    assert int(dut.rst_n_sync.value) == 0

    await RisingEdge(dut.clk_PAD)
    await Timer(1, "ps")
    assert int(dut.rst_n_sync.value) == 1


@cocotb.test()
async def test_debug_mode_propagates_to_top_chip_pads(dut):
    """
    The bottom debug mode pad should be forwarded to both top-chip debug pads.
    """
    await start_up(dut, debug_mode=0, boot_pass_en=0)

    for debug_mode in (0, 1, 0, 1):
        drive_control_inputs(dut, debug_mode=debug_mode)
        await ClockCycles(dut.clk_PAD, 4)

        assert_pad_value(dut, PIN_C0_DEBUG_MODE, debug_mode, "PIN_C0_DEBUG_MODE")
        assert_pad_value(dut, PIN_C1_DEBUG_MODE, debug_mode, "PIN_C1_DEBUG_MODE")


@cocotb.test()
async def test_req_i_buffer_trees_are_independent(dut):
    """Each request pad must drive all five branches of only its own tree."""
    await start_up(dut, debug_mode=0, boot_pass_en=0)

    if gl:
        # Post-layout optimization may rename or flatten the internal branch
        # buses; gate-level pad behavior is covered by the link tests.
        return

    for c0_req, c1_req in ((0, 0), (1, 0), (0, 1), (1, 1), (0, 0)):
        drive_control_inputs(dut, c0_req_i=c0_req, c1_req_i=c1_req)
        await Timer(2, unit="ns")

        assert int(dut.c0_req_i_branches.value) == (0x1F if c0_req else 0)
        assert int(dut.c1_req_i_branches.value) == (0x1F if c1_req else 0)


@cocotb.test()
async def test_top_chip_reset_and_clock_outputs(dut):
    """
    Top-chip reset outputs follow the gated core reset, and clock pads follow
    the incoming chip clock.
    """
    await start_up(dut, debug_mode=1, boot_pass_en=0)

    assert_pad_value(dut, PIN_C0_RST_N, 1, "PIN_C0_RST_N after startup")
    assert_pad_value(dut, PIN_C1_RST_N, 1, "PIN_C1_RST_N after startup")

    dut.rst_n_PAD.value = 0
    await ClockCycles(dut.clk_PAD, 2)
    assert_pad_value(dut, PIN_C0_RST_N, 0, "PIN_C0_RST_N during reset")
    assert_pad_value(dut, PIN_C1_RST_N, 0, "PIN_C1_RST_N during reset")

    dut.rst_n_PAD.value = 1
    await ClockCycles(dut.clk_PAD, 4)
    assert_pad_value(dut, PIN_C0_RST_N, 1, "PIN_C0_RST_N after reset")
    assert_pad_value(dut, PIN_C1_RST_N, 1, "PIN_C1_RST_N after reset")

    await assert_pad_toggles(dut, PIN_C0_CLK, "PIN_C0_CLK")
    await assert_pad_toggles(dut, PIN_C1_CLK, "PIN_C1_CLK")


@cocotb.test()
async def test_forwarded_clocks_bypass_core_output_bus(dut):
    """Dedicated top-level buffers, rather than chip_core, drive clock pads."""
    if gl:
        return

    await start_up(dut, debug_mode=1, boot_pass_en=0)
    core = dut.i_chip_core

    assert str(core.bidir_out.value[PIN_C0_CLK]) == "0"
    assert str(core.bidir_out.value[PIN_C1_CLK]) == "0"
    assert str(core.bidir_oe.value[PIN_C0_CLK]) == "0"
    assert str(core.bidir_oe.value[PIN_C1_CLK]) == "0"
    assert str(dut.bidir_PAD_OE.value[PIN_C0_CLK]) == "1"
    assert str(dut.bidir_PAD_OE.value[PIN_C1_CLK]) == "1"
    assert str(dut.bidir_PAD_IE.value[PIN_C0_CLK]) == "0"
    assert str(dut.bidir_PAD_IE.value[PIN_C1_CLK]) == "0"

    for edge, expected in ((RisingEdge, 1), (FallingEdge, 0)):
        await edge(dut.clk_PAD)
        # Allow the foundry input/output pad functional models to settle.
        await Timer(10, unit="ns")
        assert int(dut.c0_clk_to_pad.value) == expected
        assert int(dut.c1_clk_to_pad.value) == expected
        assert read_bidir_pin(dut, PIN_C0_CLK) == str(expected)
        assert read_bidir_pin(dut, PIN_C1_CLK) == str(expected)


@cocotb.test()
async def test_top_trap_inputs_drive_bottom_trap_output_pins(dut):
    """
    Top-chip trap inputs should be forwarded to the bottom trap output pins.
    """
    await start_up(dut, debug_mode=1, boot_pass_en=0)

    for c0_trap, c1_trap in ((0, 0), (1, 0), (0, 1), (1, 1), (0, 0)):
        drive_control_inputs(dut, c0_trap_i=c0_trap, c1_trap_i=c1_trap)
        await ClockCycles(dut.clk_PAD, 2)

        assert_pad_value(dut, PIN_C0_TRAP_I, c0_trap, "PIN_C0_TRAP_I")
        assert_pad_value(dut, PIN_C0_TRAP_O, c0_trap, "PIN_C0_TRAP_O")
        assert_pad_value(dut, PIN_C1_TRAP_I, c1_trap, "PIN_C1_TRAP_I")
        assert_pad_value(dut, PIN_C1_TRAP_O, c1_trap, "PIN_C1_TRAP_O")


@cocotb.test()
async def test_external_input_pads_accept_values_without_contention(dut):
    """
    Drive the external input pads through 0/1/Z patterns.

    If the DUT incorrectly drives one of these supposed input pads,
    the resolved pad value can become X, so this catches basic contention.
    """
    await start_up(dut, debug_mode=0, boot_pass_en=0, boot_miso="z")

    patterns = [
        {"debug": 0, "boot_pass": 0, "miso": 0, "c0_req": 0, "c0_ser": 0x000, "c0_trap": 0, "c1_req": 0, "c1_ser": 0x000, "c1_trap": 0},
        {"debug": 1, "boot_pass": 0, "miso": 1, "c0_req": 1, "c0_ser": 0x155, "c0_trap": 1, "c1_req": 0, "c1_ser": 0x0aa, "c1_trap": 0},
        {"debug": 0, "boot_pass": 1, "miso": "z", "c0_req": 0, "c0_ser": 0x0f0, "c0_trap": 0, "c1_req": 1, "c1_ser": 0x10f, "c1_trap": 1},
        {"debug": 1, "boot_pass": 1, "miso": 0, "c0_req": 1, "c0_ser": 0x1ff, "c0_trap": 1, "c1_req": 1, "c1_ser": 0x001, "c1_trap": 1},
    ]

    for item in patterns:
        drive_control_inputs(
            dut,
            debug_mode=item["debug"],
            boot_pass_en=item["boot_pass"],
            c0_req_i=item["c0_req"],
            c0_serial_i=item["c0_ser"],
            c0_trap_i=item["c0_trap"],
            c1_req_i=item["c1_req"],
            c1_serial_i=item["c1_ser"],
            c1_trap_i=item["c1_trap"],
        )
        drive_flash_miso(dut, item["miso"])

        await ClockCycles(dut.clk_PAD, 3)

        assert_pad_value(dut, PIN_DEBUG_MODE, item["debug"], "PIN_DEBUG_MODE")
        assert_pad_value(dut, PIN_BOOT_PASS_EN, item["boot_pass"], "PIN_BOOT_PASS_EN")
        assert_pad_value(dut, PIN_C0_REQ_I, item["c0_req"], "PIN_C0_REQ_I")
        assert_bidir_bus_value(
            dut, PIN_C0_SERIAL_I_START, SER_PINS, item["c0_ser"], "PIN_C0_SERIAL_I"
        )
        assert_pad_value(dut, PIN_C0_TRAP_I, item["c0_trap"], "PIN_C0_TRAP_I")
        assert_pad_value(dut, PIN_C1_REQ_I, item["c1_req"], "PIN_C1_REQ_I")
        assert_bidir_bus_value(
            dut, PIN_C1_SERIAL_I_START, SER_PINS, item["c1_ser"], "PIN_C1_SERIAL_I"
        )
        assert_pad_value(dut, PIN_C1_TRAP_I, item["c1_trap"], "PIN_C1_TRAP_I")

        if item["miso"] != "z":
            assert_pad_value(dut, PIN_BOOT_MISO, item["miso"], "PIN_BOOT_MISO")


@cocotb.test()
async def test_boot_pass_en_tristates_boot_spi_outputs(dut):
    """
    In boot pass-through mode, boot SPI output pads should not be driven.

    chip_core drives boot SCLK/MOSI/CS only when boot_pass_en is low.
    With boot_pass_en high, these pads should resolve to Z because the testbench
    also releases them.
    """
    await start_up(dut, debug_mode=0, boot_pass_en=1, boot_miso="z")

    await ClockCycles(dut.clk_PAD, 20)

    for pin, name in SPI_OUTPUT_PINS:
        val = read_bidir_pin(dut, pin)
        assert val == "z", f"{name} should be Z in boot pass-through mode, got {val}"


@cocotb.test(timeout_time=20, timeout_unit="ms")
async def test_boot_spi_pads_drive_in_normal_mode(dut):
    """
    In normal mode, housekeeping boot should drive the SPI flash pads.

    Checks:
    - CS eventually asserts low
    - SCLK/MOSI/CS are known 0/1, not X/Z, once boot starts
    - SCLK actually toggles after CS assertion
    """
    await start_up(
        dut,
        debug_mode=0,
        boot_pass_en=0,
        boot_miso="z",
        start_flash=True,
    )

    await wait_for_pad_value(
        dut,
        PIN_BOOT_CS,
        "0",
        timeout_cycles=BOOT_CS_TIMEOUT_CYCLES,
    )

    for pin, name in SPI_OUTPUT_PINS:
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
        boot_pass_en=0,
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

    for pin, name in SPI_OUTPUT_PINS:
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
    """
    flash = await start_up(
        dut,
        debug_mode=0,
        boot_pass_en=0,
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

    for pin, name in SPI_OUTPUT_PINS:
        assert_pad_known(dut, pin, f"{name} during SPI boot")


@cocotb.test()
async def test_boot_spi_outputs_disable_when_boot_pass_en_is_asserted_late(dut):
    """
    Start in normal mode, then assert boot_pass_en and confirm boot outputs release.

    This checks that boot_pass_en dynamically controls the boot pad OEs.
    """
    await start_up(dut, debug_mode=0, boot_pass_en=0, boot_miso="z")

    await ClockCycles(dut.clk_PAD, 20)

    drive_control_inputs(dut, boot_pass_en=1)
    await Timer(BOOT_PASS_WAIT_NS, unit="ns")

    for pin, name in SPI_OUTPUT_PINS:
        val = read_bidir_pin(dut, pin)
        assert val == "z", f"{name} should release after boot_pass_en=1, got {val}"


@cocotb.test()
async def test_boot_spi_outputs_reenable_after_boot_pass_en_is_cleared(dut):
    """
    Start in boot pass-through mode, clear boot_pass_en, and confirm boot outputs
    become driven.
    """
    await start_up(dut, debug_mode=0, boot_pass_en=1, boot_miso="z")

    await ClockCycles(dut.clk_PAD, 20)

    drive_control_inputs(dut, boot_pass_en=0)
    await Timer(BOOT_PASS_WAIT_NS, unit="ns")

    for pin, name in SPI_OUTPUT_PINS:
        val = read_bidir_pin(dut, pin)
        assert val in ("0", "1"), (
            f"{name} should be driven after boot_pass_en=0, got {val}"
        )


@cocotb.test(timeout_time=20, timeout_unit="ms")
async def test_long_boot_smoke_no_trap_or_unknown_outputs(dut):
    """
    Longer chip-top smoke test.

    Runs with the flash responder active and checks that critical observable pads
    remain sane over time.
    """
    await start_up(
        dut,
        debug_mode=0,
        boot_pass_en=0,
        boot_miso="z",
        start_flash=True,
    )

    for sample in range(20):
        await ClockCycles(dut.clk_PAD, 250)

        assert_pad_known(dut, PIN_C0_CLK, "PIN_C0_CLK long boot")
        assert_pad_known(dut, PIN_C1_CLK, "PIN_C1_CLK long boot")
        assert_pad_value(dut, PIN_C0_DEBUG_MODE, 0, "PIN_C0_DEBUG_MODE long boot")
        assert_pad_value(dut, PIN_C1_DEBUG_MODE, 0, "PIN_C1_DEBUG_MODE long boot")

        # In normal mode, boot SPI outputs should be driven, not X/Z.
        for pin, name in SPI_OUTPUT_PINS:
            val = read_bidir_pin(dut, pin)
            assert val in ("0", "1"), (
                f"{name} became {val} during long boot sample {sample}"
            )


@cocotb.test()
async def test_control_input_stress_sequence(dut):
    """
    Deterministic stress sequence for debug_mode, boot_pass_en, traps, and MISO.

    This is not random so failures are reproducible.
    """
    await start_up(dut, debug_mode=1, boot_pass_en=1, boot_miso="z")

    sequence = [
        {"debug": 1, "boot_pass": 1, "miso": "z", "c0_trap": 0, "c1_trap": 0},
        {"debug": 1, "boot_pass": 0, "miso": 0, "c0_trap": 1, "c1_trap": 0},
        {"debug": 0, "boot_pass": 0, "miso": 1, "c0_trap": 1, "c1_trap": 1},
        {"debug": 0, "boot_pass": 1, "miso": 0, "c0_trap": 0, "c1_trap": 1},
        {"debug": 1, "boot_pass": 1, "miso": "z", "c0_trap": 0, "c1_trap": 0},
    ]

    for idx, item in enumerate(sequence):
        drive_control_inputs(
            dut,
            debug_mode=item["debug"],
            boot_pass_en=item["boot_pass"],
            c0_trap_i=item["c0_trap"],
            c1_trap_i=item["c1_trap"],
        )
        drive_flash_miso(dut, item["miso"])

        await ClockCycles(dut.clk_PAD, 6)

        assert_pad_value(dut, PIN_C0_DEBUG_MODE, item["debug"], f"C0 debug {idx}")
        assert_pad_value(dut, PIN_C1_DEBUG_MODE, item["debug"], f"C1 debug {idx}")
        assert_pad_value(dut, PIN_C0_TRAP_O, item["c0_trap"], f"C0 trap {idx}")
        assert_pad_value(dut, PIN_C1_TRAP_O, item["c1_trap"], f"C1 trap {idx}")

        for pin, name in SPI_OUTPUT_PINS:
            val = read_bidir_pin(dut, pin)
            if item["boot_pass"]:
                assert val == "z", f"{name} should be Z at stress index {idx}, got {val}"
            else:
                assert val in ("0", "1"), (
                    f"{name} should be driven at stress index {idx}, got {val}"
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
            scl_dir / "primitives.v",
            scl_dir / f"{scl}.v",
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

        # SRAM macro models.
        sram_dir / "gf180mcu_fd_ip_sram__sram512x8m8wm1.v",
        sram_dir / "gf180mcu_fd_ip_sram__sram64x8m8wm1.v",

        # Custom IP required by chip_top.
        proj_path / "../ip/gf180mcu_ws_ip__id/vh/gf180mcu_ws_ip__id.v",
        proj_path / "../ip/gf180mcu_ws_ip__qrcode_id/vh/gf180mcu_ws_ip__qrcode_id.v",
        proj_path / "../ip/gf180mcu_ws_ip__shuttle_id/vh/gf180mcu_ws_ip__shuttle_id.v",
        proj_path / "../ip/gf180mcu_ws_ip__project_id/vh/gf180mcu_ws_ip__project_id.v",
        proj_path / "../ip/gf180mcu_ws_ip__marker/vh/gf180mcu_ws_ip__marker.v",
        proj_path / "../ip/gf180mcu_ws_ip__logo/vh/gf180mcu_ws_ip__logo.v",
    ]

    ws_io_model = io_dir / "gf180mcu_ws_io.v"
    if ws_io_model.exists():
        sources.append(ws_io_model)

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
