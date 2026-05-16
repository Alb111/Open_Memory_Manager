import subprocess
import sys
import os
import pytest
from pathlib import Path

ENV_VARS = {
    "PDK_ROOT": os.getenv("PDK_ROOT", str(Path("~/.ciel").expanduser())),
    "PDK":      os.getenv("PDK",      "gf180mcuD"),
    "SLOT":     os.getenv("SLOT",     "1x1"),
    "SIM":      os.getenv("SIM",      "icarus"),
    **os.environ,
}

COCOTB_DIR = Path(__file__).resolve().parent


def _run_testbench(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, script],
        cwd=COCOTB_DIR,
        env=ENV_VARS,
        capture_output=False,
        text=True,
    )


class TestMemCtrl:
    """Cocotb testbench: Memory (mem_tb.py)"""

    def test_mem_ctrl(self):
        result = _run_testbench("mem_tb.py")
        assert result.returncode == 0, (
            f"mem_tb.py failed with exit code {result.returncode}"
        )


class TestCacheMem:
    """Cocotb testbench: Cache Memory (cache_mem_tb.py)"""

    def test_cache_mem(self):
        result = _run_testbench("cache_mem_tb.py")
        assert result.returncode == 0, (
            f"cache_mem_tb.py failed with exit code {result.returncode}"
        )


class TestTwoPortCacheMem:
    """Cocotb testbench: Two-Port Cache Memory (two_port_cache_mem_tb.py)"""

    def test_two_port_cache_mem(self):
        result = _run_testbench("two_port_cache_mem_tb.py")
        assert result.returncode == 0, (
            f"two_port_cache_mem_tb.py failed with exit code {result.returncode}"
        )


class TestMemCtrl128x4:
    """Cocotb testbench: Memory Controller 128x4 (mem_ctrl_128x4_tb.py)"""

    def test_mem_ctrl_128x4(self):
        result = _run_testbench("mem_ctrl_128x4_tb.py")
        assert result.returncode == 0, (
            f"mem_ctrl_128x4_tb.py failed with exit code {result.returncode}"
        )


class TestMemCtrl128x32:
    """Cocotb testbench: Memory Controller 128x32 (mem_ctrl_128x32_tb.py)"""

    def test_mem_ctrl_128x32(self):
        result = _run_testbench("mem_ctrl_128x32_tb.py")
        assert result.returncode == 0, (
            f"mem_ctrl_128x32_tb.py failed with exit code {result.returncode}"
        )


class TestCacheController:
    """Cocotb testbench: Cache Controller (cache_controller_tb.py)"""

    def test_cache_controller(self):
        result = _run_testbench("cache_controller_tb.py")
        assert result.returncode == 0, (
            f"cache_controller_tb.py failed with exit code {result.returncode}"
        )


class TestMSI:
    """Cocotb testbench: MSI (rishi_stuff/msi_tb.py)"""

    def test_msi(self):
        result = _run_testbench("rishi_stuff/msi_tb.py")
        assert result.returncode == 0, (
            f"msi_tb.py failed with exit code {result.returncode}"
        )


class TestMSIProtocol:
    """Cocotb testbench: MSI Protocol (rishi_stuff/msi_protocol_tb.py)"""

    def test_msi_protocol(self):
        result = _run_testbench("rishi_stuff/msi_protocol_tb.py")
        assert result.returncode == 0, (
            f"msi_protocol_tb.py failed with exit code {result.returncode}"
        )


class TestCacheControllerModel:
    """Cocotb testbench: Cache Controller Model (rishi_stuff/cache_controller_model_tb.py)"""

    def test_cache_controller_model(self):
        result = _run_testbench("rishi_stuff/cache_controller_model_tb.py")
        assert result.returncode == 0, (
            f"cache_controller_model_tb.py failed with exit code {result.returncode}"
        )


class TestWRRArbiter:
    """Cocotb testbench: WRR Arbiter (wrr_arbiter_tb.py)"""

    def test_wrr_arbiter(self):
        result = _run_testbench("wrr_arbiter_tb.py")
        assert result.returncode == 0, (
            f"wrr_arbiter_tb.py failed with exit code {result.returncode}"
        )


class TestTSerializer:
    """Cocotb testbench: Transmit Serializer (tserializer_tb.py)"""

    def test_tserializer(self):
        result = _run_testbench("tserializer_tb.py")
        assert result.returncode == 0, (
            f"tserializer_tb.py failed with exit code {result.returncode}"
        )


class TestRSerializer:
    """Cocotb testbench: Receive Serializer (rserializer_tb.py)"""

    def test_rserializer(self):
        result = _run_testbench("rserializer_tb.py")
        assert result.returncode == 0, (
            f"rserializer_tb.py failed with exit code {result.returncode}"
        )


class TestCacheInterface:
    """Cocotb testbench: Cache Interface (cache_interface_tb.py)"""

    def test_cache_interface(self):
        result = _run_testbench("cache_interface_tb.py")
        assert result.returncode == 0, (
            f"cache_interface_tb.py failed with exit code {result.returncode}"
        )


class TestDirectoryInterface:
    """Cocotb testbench: Directory Interface (directory_interface_tb.py)"""

    def test_directory_interface(self):
        result = _run_testbench("directory_interface_tb.py")
        assert result.returncode == 0, (
            f"directory_interface_tb.py failed with exit code {result.returncode}"
        )


class TestOnProcessorEventSM:
    """Cocotb testbench: On-Processor Event State Machine (on_processor_event_state_machine_tb.py)"""

    def test_on_processor_event_sm(self):
        result = _run_testbench("on_processor_event_state_machine_tb.py")
        assert result.returncode == 0, (
            f"on_processor_event_state_machine_tb.py failed with exit code {result.returncode}"
        )


class TestOnSnoopEventSM:
    """Cocotb testbench: On-Snoop Event State Machine (on_snoop_event_state_machine_tb.py)"""

    def test_on_snoop_event_sm(self):
        result = _run_testbench("on_snoop_event_state_machine_tb.py")
        assert result.returncode == 0, (
            f"on_snoop_event_state_machine_tb.py failed with exit code {result.returncode}"
        )


class TestSpAddrHandler:
    """Cocotb testbench: SP Address Handler (sp_handler_tb.py)"""

    def test_sp_addr_handler(self):
        result = _run_testbench("sp_handler_tb.py")
        assert result.returncode == 0, (
            f"sp_handler_tb.py failed with exit code {result.returncode}"
        )


class TestBoot:
    """Cocotb testbench: Boot Controller (housekeeping_tb.py)"""

    def test_boot_ctrl(self):
        result = _run_testbench("housekeeping_tb.py")
        assert result.returncode == 0, (
            f"housekeeping_tb.py failed with exit code {result.returncode}"
        )


class TestBootFlash:
    """Cocotb testbench: Boot Flash (boot_flash_tb.py)"""

    def test_boot_flash(self):
        result = _run_testbench("boot_flash_tb.py")
        assert result.returncode == 0, (
            f"boot_flash_tb.py failed with exit code {result.returncode}"
        )


class TestCacheControllerRishi:
    """Cocotb testbench: Cache Controller Rishi (rishi_stuff/cache_controller_tb.py)"""

    def test_cache_controller_rishi(self):
        result = _run_testbench("rishi_stuff/cache_controller_tb.py")
        assert result.returncode == 0, (
            f"cache_controller_tb.py failed with exit code {result.returncode}"
        )


class TestBootMem:
    """Cocotb testbench: Boot Memory (boot_mem_tb.py)"""

    def test_boot_mem(self):
        result = _run_testbench("boot_mem_tb.py")
        assert result.returncode == 0, (
            f"boot_mem_tb.py failed with exit code {result.returncode}"
        )


class TestChipTop:
    """Cocotb testbench: Chip Top (chip_top_tb.py)"""

    def test_chip_top(self):
        result = _run_testbench("chip_top_tb.py")
        assert result.returncode == 0, (
            f"chip_top_tb.py failed with exit code {result.returncode}"
        )
