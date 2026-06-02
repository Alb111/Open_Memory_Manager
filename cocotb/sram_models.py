import os
from pathlib import Path


COCOTB_DIR = Path(__file__).resolve().parent
REPO_ROOT = COCOTB_DIR.parent


def find_sram_model(depth: int) -> Path:
    """Return a GF180 SRAM model path, falling back to local cocotb models."""
    pdk = os.getenv("PDK", "gf180mcuD")
    model_name = f"gf180mcu_fd_ip_sram__sram{depth}x8m8wm1.v"
    rel_model = Path(pdk) / "libs.ref/gf180mcu_fd_ip_sram/verilog" / model_name

    candidates = []
    if os.getenv("PDK_ROOT"):
        candidates.append(Path(os.environ["PDK_ROOT"]) / rel_model)

    candidates.extend(
        [
            REPO_ROOT / "gf180mcu" / rel_model,
            REPO_ROOT.parent / "gf180mcu" / rel_model,
            Path.home() / ".ciel" / rel_model,
        ]
    )

    for candidate in candidates:
        if candidate.exists():
            return candidate

    fallback = COCOTB_DIR / "models" / f"gf180_sram{depth}x8_model.sv"
    if fallback.exists():
        return fallback

    checked = "\n".join(str(path) for path in candidates)
    raise FileNotFoundError(
        f"Could not find {model_name}. Checked:\n{checked}\n"
        f"Fallback model is missing: {fallback}"
    )
