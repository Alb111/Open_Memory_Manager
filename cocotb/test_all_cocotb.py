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
    """Run a cocotb runner script and return the completed process."""
    return subprocess.run(
        [sys.executable, script],
        cwd=COCOTB_DIR,
        env=ENV_VARS,
        capture_output=False,
        text=True,
    )

class TestMemCtrl:
    """Cocotb testbench: Memory (mem_test.py)"""

    def test_mem_ctrl(self):
        result = _run_testbench("mem_test.py")
        assert result.returncode == 0, (
            f"mem_test.py failed with exit code {result.returncode}"
        )


class TestMSI:
    """Cocotb testbench: MSI (msi_test.py)"""

    def test_msi(self):
        result = _run_testbench("msi_test.py")
        assert result.returncode == 0, (
            f"msi_test.py failed with exit code {result.returncode}"
        )


class TestWRRArbiter:
    """Cocotb testbench: WRR Arbiter (wrr_arbiter_test.py)"""

    def test_wrr_arbiter(self):
        result = _run_testbench("wrr_arbiter_test.py")
        assert result.returncode == 0, (
            f"wrr_arbiter_test.py failed with exit code {result.returncode}"
        )

class TestBoot:
    """Cocotb testbench: Boot Controller (housekeeping_tb.py)"""

    def test_boot_ctrl(self):
        result = _run_testbench("housekeeping_tb.py")
        assert result.returncode == 0, (
            f"housekeeping_tb.py failed with exit code {result.returncode}"
        )
