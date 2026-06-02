import glob
import subprocess
import os
import shutil
from pathlib import Path
import json

def prepend_timescale(file_path, timescale="`timescale 1ns/1ps"):
    """Prepends a timescale directive to the top of a file."""
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Avoid double-adding if the script is run multiple times
    if not content.strip().startswith("`timescale"):
        with open(file_path, 'w') as f:
            f.write(f"{timescale}\n{content}")
        print(f"    Timescale added to {os.path.basename(file_path)}")

pdk_root = os.getenv("PDK_ROOT", Path("~/.ciel").expanduser())
pdk = os.getenv("PDK", "gf180mcuD")
slot = os.getenv("SLOT", "1x1")
project_root = Path(__file__).parent.parent.resolve()

# 1. Collect all SystemVerilog files
# Put packages or global defines first to satisfy SV requirements
all_files = glob.glob("**/*.sv", recursive=True)
all_files += [Path(pdk_root) / pdk / "libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram64x8m8wm1.v"]

# Remove duplicates while preserving order
all_files = list(dict.fromkeys(all_files))
all_files_abs = [os.path.abspath(os.path.join(project_root, f)) for f in all_files]

base_config = "librelane/config.yaml"
# Your list of top-level modules to generate netlists for
with open(Path(project_root) / 'scripts' / 'gen_netlists.json', 'r') as f:
    data = json.load(f)

# 2. Extract the list into a variable
target_modules = data["target_modules"]

# ignore certain files
file_to_remove = data["ignore_file"]
all_files_abs = [f for f in all_files_abs if os.path.basename(f) not in file_to_remove]


for design in target_modules:
    print(f"--- Synthesizing {design} with full file list ---")
    
    files_str = str(all_files_abs).replace("[", "").replace("]", "").replace("'", "").replace(" ", "")

    cmd = [
        "python3", "-m", "librelane", 
        f"librelane/slots/slot_{slot}.yaml", base_config,
        "--pdk-root", pdk_root,
        "--pdk", pdk, "--manual-pdk",
        "--override-config", f"DESIGN_NAME={design}",
        "--override-config", f"VERILOG_FILES={files_str}",
        "--to", "Yosys.Synthesis"
    ]
    
    Errors = []
    try:
        subprocess.run(cmd, check=True)
        print(f"\n    Finished {design} successfully.")
        
        dest_dir = project_root / "src" / "netlists"
        dest_dir.mkdir(parents=True, exist_ok=True)

        runs_dir = project_root / "librelane" / "runs"

        if runs_dir.exists():
            # Get all subdirectories in 'runs', sorted by creation time (newest first)
            all_runs = sorted(
                [d for d in runs_dir.iterdir() if d.is_dir()],
                key=lambda x: x.stat().st_mtime,
                reverse=True
            )

            if all_runs:
                current_run_dir = all_runs[0]
                result_path = current_run_dir / "final" / "nl" / f"{design}.nl.v"
                
                if result_path.exists():
                    dest_file = dest_dir / f"{design}.nl.v"
                    shutil.copy2(result_path, dest_file)
                    prepend_timescale(dest_file)
                    print(f"    Netlist captured from: {current_run_dir.name}")
                else:
                    print(f"    Warning: .nl.v file missing in {current_run_dir}")
            else:
                print(f"    Warning: No run directories found in {runs_dir}")
        else:
            print(f"    Warning: Runs directory does not exist for {design}")
    except subprocess.CalledProcessError as e:
        print(f"\n  Error: Synthesis failed for {design}.")
        Errors.append({design, str(e)})
        # The logs are saved in the run directory if it fails

    if Errors:
        print("\nErrors encountered during synthesis:")
        for error in Errors:
            print(error)