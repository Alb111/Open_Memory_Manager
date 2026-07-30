import subprocess
import sys
import os
import pytest
from pathlib import Path

COCOTB_DIR = Path(__file__).resolve().parent
REPO_ROOT = COCOTB_DIR.parent

ENV_VARS = {
    "PDK_ROOT": os.getenv("PDK_ROOT", str(REPO_ROOT / "gf180mcu")),
    "PDK":      os.getenv("PDK",      "gf180mcuD"),
    "SLOT":     os.getenv("SLOT",     "1x1"),
    "SIM":      os.getenv("SIM",      "icarus"),
    **os.environ,
}

BOOT_FLASH_MODEL = Path(
    os.getenv(
        "CYPRESS_S25FL128L_MODEL",
        REPO_ROOT / "src" / "housekeeping" / "cypress_model" / "s25fl128l.v",
    )
)

# mem64x8_tb / directory_mem_tb were dropped: their modules (mem64x8,
# directory_mem) are superseded by the mem2048x3 + directory_controller_full
# rewrite and are no longer instantiated in chip_core.
TESTBENCHES = [
    ("mem_tb.py", None),
    ("mem2048x3_tb.py", None),
    ("wrr_arbiter_tb.py", None),
    ("tserializer_tb.py", None),
    ("rserializer_tb.py", None),
    ("directory_interface_tb.py", None),
    ("directory_controller_tb.py", None),
    ("memory_reset_generator_tb.py", None),
    ("housekeeping_tb.py", None),
    ("boot_flash_tb.py", BOOT_FLASH_MODEL),
    ("boot_mem_tb.py", BOOT_FLASH_MODEL),
    ("whoami_boot_tb.py", BOOT_FLASH_MODEL),
    ("chip_core_boot_tb.py", BOOT_FLASH_MODEL),
    ("chip_top_tb.py", None),
]


def _run_testbench(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, script],
        cwd=COCOTB_DIR,
        env=ENV_VARS,
        capture_output=False,
        text=True,
    )


@pytest.mark.parametrize(
    ("script", "required_file"),
    TESTBENCHES,
    ids=[script.removesuffix(".py") for script, _ in TESTBENCHES],
)
def test_cocotb_testbench(script, required_file):
    if required_file is not None and not required_file.exists():
        pytest.skip(f"{script} requires missing external file: {required_file}")

    result = _run_testbench(script)
    assert result.returncode == 0, (
        f"{script} failed with exit code {result.returncode}"
    )
