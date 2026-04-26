import os
import shutil
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge, FallingEdge, ClockCycles
from cocotb_tools.runner import get_runner

sim = os.getenv("SIM", "icarus")
pdk_root = Path("../gf180mcu")
pdk = os.getenv("PDK", "gf180mcuD")

hdl_toplevel = "boot_mem_wrapper"

# boot image, has to match what is written to boot_image.mem
#same 512-byte xor pattern used in boot_flash_test.py
BOOT_IMAGE = [(i & 0xFF) ^ 0xA5 for i in range(512)]

def expected_word(word_index):
    b = BOOT_IMAGE[word_index * 4 : word_index * 4 + 4]
    return b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)

def write_boot_image_mem():
    sim_build = Path(__file__).resolve().parent / "sim_build"
    sim_build.mkdir(exist_ok=True)
    out = sim_build / "boot_image.mem"
    with open(out, "w") as f:
        f.write("@000000\n")
        for byte in BOOT_IMAGE:
            f.write(f"{byte:02X}\n")
    return out

#helpers
def start_clock(dut):
    # 10 ns period (100 MHz) same as boot_flash_test.py
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())

async def apply_reset(dut, cycles=40_000):
    dut.reset_ni.value = 0
    dut.pass_thru_en_i.value = 0
    dut.mem_valid_i.value = 0
    dut.mem_addr_i.value= 0
    dut.mem_wstrb_i.value= 0
    await ClockCycles(dut.clk_i, cycles)
    dut.reset_ni.value = 1
    await Timer(1, unit="ns")

# mem read helper, like axi_read() from mem_test.py
# drive wrapper read port directly (only valid after boot_done)
async def mem_read(dut, addr):
    dut.mem_addr_i.value = addr
    dut.mem_wstrb_i.value = 0
    dut.mem_valid_i.value = 1
    await FallingEdge(dut.clk_i)
    await FallingEdge(dut.clk_i)
    rdata = dut.mem_rdata_o.value
    dut.mem_valid_i.value = 0
    await RisingEdge(dut.clk_i)
    return int(rdata) if rdata.is_resolvable else None


#test 1 —flash -> bootloader -> memory controller -> SRAM
@cocotb.test()
async def test_boot_writes_reach_sram(dut):
    print("\n=== INTEGRATION TEST 1: full boot and sram readback ===")
    start_clock(dut)
    await apply_reset(dut)
    #wait for boot to complete
    timed_out = False
    for _ in range(500_000):
        await RisingEdge(dut.clk_i)
        if dut.boot_done_o.value == 1:
            break
    else:
        timed_out = True

    assert not timed_out, \
        "boot_done_o never asserted — boot did not complete within timeout"

    print(f"  boot_done_o asserted — boot complete")
    print(f"  cores_en_o  = {int(dut.cores_en_o.value)}  (expected 1)")
    assert dut.cores_en_o.value == 1, "cores_en must be high after boot"
    await ClockCycles(dut.clk_i, 5)

    #read back all 128 words and compare against boot image
    print(f"\n  Reading back all 128 words from SRAM...")
    print(f"  {'Word':<6} {'Addr':<12} {'Read data':<14} {'Expected':<14} {'OK'}")

    all_ok = True
    num_words = len(BOOT_IMAGE) // 4
    for i in range(num_words):
        addr = i * 4
        expected = expected_word(i)
        actual = await mem_read(dut, addr)
        if actual is None:
            print(f"  {i:<6} {hex(addr):<12} {'X/Z':14} {hex(expected):<14} FAIL")
            assert False, f"Word {i} at addr {hex(addr)} returned X/Z — SRAM not initialized"
        ok = (actual == expected)
        if not ok:
            all_ok = False
        # print every word
        print(f"  {i:<6} {hex(addr):<12} {hex(actual):<14} {hex(expected):<14} "
              f"{'PASS' if ok else 'FAIL'}")

        assert ok, \
            (f"SRAM readback mismatch at word {i} (addr {hex(addr)}): "
             f"got {hex(actual)}, expected {hex(expected)}. "
             f"Data did not propagate correctly through the boot chain.")

    print(f"\n  All {num_words} words read back correctly from physical SRAM.")
    print("\n  *** PASS — full chain verified: flash -> bootloader -> "
          "memory controller -> SRAM")
    

@cocotb.test()
async def test_wstrb_correct_during_boot(dut):
    print("\n=== INTEGRATION TEST 2: wstrb is 0xF for every boot write ===")
    start_clock(dut)
    await apply_reset(dut)
    bad_wstrb_count = 0
    timed_out = False
 
    for _ in range(500_000):
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")
        if dut.u_housekeeping.mem_valid_o.value == 1:
            wstrb = dut.u_housekeeping.mem_wstrb_o.value
            if wstrb.is_resolvable:
                wstrb_int = int(wstrb)
                if wstrb_int != 0xF:
                    bad_wstrb_count += 1
                    print(f"  BAD wstrb={hex(wstrb_int)} detected during boot write!")
        if dut.boot_done_o.value == 1:
            break
    else:
        timed_out = True
    assert not timed_out, "boot_done never asserted"
    assert bad_wstrb_count == 0, \
        (f"{bad_wstrb_count} writes had incorrect wstrb. "
         f"All boot writes must use wstrb=0xF to write all 4 byte lanes.")
    print(f"  All boot writes had wstrb=0xF")
    print("  *** PASS — byte lane enables are correct for all boot writes")


#runner
def boot_mem_runner():
    proj_path = Path(__file__).resolve().parent
    sim_build = proj_path / "sim_build"
    sim_build.mkdir(exist_ok=True)

    #write boot image before build so flash model loads it at time zero
    mem_path = write_boot_image_mem()
    print(f"[runner] wrote {mem_path}")

    secr_src = proj_path / "../src/housekeeping/cypress_model/s25fl128lSECR.mem"
    if secr_src.exists():
        shutil.copy(secr_src, sim_build / "s25fl128lSECR.mem")

    sram_macro = (Path(pdk_root) / pdk /
                  "libs.ref/gf180mcu_fd_ip_sram/verilog/"
                  "gf180mcu_fd_ip_sram__sram512x8m8wm1.v")

    sources = [
        # sram macro
        sram_macro,
        #mem ctrl
        proj_path / "../src/mem_ctrl/mem512x32.sv",
        proj_path / "../src/mem_ctrl/mem2048x32.sv",
        # boot controller
        proj_path / "../src/housekeeping/spi_engine.sv",
        proj_path / "../src/housekeeping/boot_fsm.sv",
        proj_path / "../src/housekeeping/housekeeping_top.sv",
        #flash model
        proj_path / "../src/housekeeping/cypress_model/s25fl128l.v",
        #integration wrapper
        proj_path / "../src/housekeeping/boot_mem_wrapper.sv",
    ]

    build_args = []
    if sim == "icarus":
        build_args = ["-g2012"]

    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel="boot_mem_wrapper",
        always=True,
        build_args=build_args,
        waves=True,
    )
    runner.test(
        hdl_toplevel="boot_mem_wrapper",
        test_module="boot_mem_test",
        waves=True,
    )

if __name__ == "__main__":
    boot_mem_runner()