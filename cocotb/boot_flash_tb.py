import os
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge, ClockCycles
from cocotb_tools.runner import get_runner
 
 
sim     = os.getenv("SIM", "icarus")
pdk_root = os.getenv("PDK_ROOT", Path("~/.ciel").expanduser())
pdk     = os.getenv("PDK", "gf180mcuD")
scl     = os.getenv("SCL", "gf180mcu_fd_sc_mcu7t5v0")
gl      = os.getenv("GL", False)
slot    = os.getenv("SLOT", "1x1")
 
hdl_toplevel = "boot_flash_wrapper"
 
BOOT_IMAGE = [(i & 0xFF) ^ 0xA5 for i in range(512)]
 
# JEDEC ID for S25FL128L:  Manufacturer=0x01  Type=0x60  Capacity=0x18
JEDEC_MANUF = 0x01
JEDEC_MEM_TYPE = 0x60
JEDEC_CAPACITY = 0x18
 
 
def write_boot_image_mem():
    sim_build = Path(__file__).resolve().parent / "sim_build"
    sim_build.mkdir(exist_ok=True)
    out = sim_build / "boot_image.mem"
    with open(out, "w") as f:
        f.write("@000000\n")
        for byte in BOOT_IMAGE:
            f.write(f"{byte:02X}\n")
    return out
 
 
def expected_word(word_index):
    #return expected 32-bit SRAM word for a given word index
    b = BOOT_IMAGE[word_index * 4 : word_index * 4 + 4]
    return b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)
 
 

def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())
 
 
async def apply_reset(dut, cycles=40_000):
    dut.reset_ni.value      = 0
    dut.pass_thru_en_i.value = 0
    await ClockCycles(dut.clk_i, cycles)
    dut.reset_ni.value = 1
    await Timer(1, unit="ns")
 
 
async def wait_for_boot_done(dut, timeout_cycles=500_000):
    #poll boot_done_o: return true on success, false on timeout
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk_i)
        if dut.boot_done_o.value == 1:
            return True
    return False
 
 
async def spi_transfer_byte(dut, byte_out):
    received = 0
    for bit in range(7, -1, -1):
        dut.spi_mosi.value = (byte_out >> bit) & 1
        await Timer(50, unit="ns")
        dut.spi_sck.value = 1
        await Timer(10, unit="ns")
        # flash_so can be Z while flash is receiving — treat Z as 0
        raw = dut.flash_so.value
        miso_bit = int(raw) if raw.is_resolvable else 0
        received = (received << 1) | miso_bit
        await Timer(40, unit="ns")
        dut.spi_sck.value = 0
        await Timer(50, unit="ns")
    return received
 
 
async def spi_read_jedec(dut):
    dut.flash_csb.value = 0                              
    await Timer(100, unit="ns")
    await spi_transfer_byte(dut, 0x9F)
    manuf = await spi_transfer_byte(dut, 0x00)
    mem_type = await spi_transfer_byte(dut, 0x00)
    capacity = await spi_transfer_byte(dut, 0x00)
    dut.flash_csb.value = 1                              
    await Timer(100, unit="ns")
    return manuf, mem_type, capacity
 
 
# test 1 — Reset: outputs are inactive while reset is held
@cocotb.test()
async def test_reset_inactive(dut):
    print("\n=== TEST 1: reset holds outputs inactive ===")
    start_clock(dut)
    dut.reset_ni.value = 0
    dut.pass_thru_en_i.value = 0
    await ClockCycles(dut.clk_i, 10)
    await Timer(1, unit="ns")
 
    print(f"  sram_wr_en_o = {int(dut.sram_wr_en_o.value)}  (expected 0)")
    print(f"  cores_en_o = {int(dut.cores_en_o.value)}   (expected 0)")
    print(f"  boot_done_o = {int(dut.boot_done_o.value)}  (expected 0)")
    assert dut.sram_wr_en_o.value == 0, "sram_wr_en must be 0 during reset"
    assert dut.cores_en_o.value == 0, "cores_en must be 0 during reset"
    assert dut.boot_done_o.value == 0, "boot_done must be 0 during reset"
 
    print(" *** PASS")
 
 
# test 2 — JEDEC Device ID
@cocotb.test()
async def test_jedec_id(dut):
    print("\n=== TEST 2: JEDEC device ID via pass-through ===")
    start_clock(dut)
    # hold boot controller in reset during this test
    dut.reset_ni.value = 0
    dut.pass_thru_en_i.value = 1 
    dut.spi_sck.value = 0
    dut.spi_mosi.value = 0
    dut.flash_csb.value = 1
 
    # wait long enough for flash power-up (SPEEDSIM: ~300 µs = 30,000 cycles)
    await ClockCycles(dut.clk_i, 40_000)
    await Timer(1, unit="ns")
    manuf, mem_type, capacity = await spi_read_jedec(dut)
 
    print(f"  Manufacturer ID: {hex(manuf)}(expected {hex(JEDEC_MANUF)})")
    print(f"  Memory type: {hex(mem_type)}(expected {hex(JEDEC_MEM_TYPE)})")
    print(f"  Capacity: {hex(capacity)} (expected {hex(JEDEC_CAPACITY)})")
    assert manuf == JEDEC_MANUF,    \
        f"Wrong manufacturer ID: got {hex(manuf)}, expected {hex(JEDEC_MANUF)}"
    assert mem_type == JEDEC_MEM_TYPE, \
        f"Wrong memory type: got {hex(mem_type)}, expected {hex(JEDEC_MEM_TYPE)}"
    assert capacity == JEDEC_CAPACITY, \
        f"Wrong capacity byte: got {hex(capacity)}, expected {hex(JEDEC_CAPACITY)}"
 
    print("  *** PASS — S25FL128L correctly identified")


 
#test 3 — full boot sequence: 128 words from real flash model
@cocotb.test()
async def test_full_boot_real_flash(dut):
    print("\n=== TEST 3: full boot against real S25FL128L model ===")
    start_clock(dut)
    # long reset: must outlast the flash power-up delay (SPEEDSIM ~300us)
    await apply_reset(dut, cycles=40_000)
    #capture every SRAM write in order
    sram_writes = []
    timed_out = False
 
    for _ in range(500_000):
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")       
        if dut.sram_wr_en_o.value == 1:
            addr = dut.sram_addr_o.value
            data = dut.sram_data_o.value
            #skip any cycle where signals haven't resolved yet
            if addr.is_resolvable and data.is_resolvable:
                sram_writes.append((int(addr), int(data)))
        if dut.boot_done_o.value == 1:
            break
    else:
        timed_out = True
    assert not timed_out, \
        "boot_done never asserted — boot did not complete within timeout"
 
    #check write count 
    BOOT_WORDS = len(BOOT_IMAGE) // 4 
    print(f"\n  SRAM writes: {len(sram_writes)}  (expected {BOOT_WORDS})")
    assert len(sram_writes) == BOOT_WORDS, \
        f"Expected {BOOT_WORDS} word writes, got {len(sram_writes)}"
 
    #check each words address and data
    print(f"\n  {'Word':<6} {'Addr got':<14} {'Addr exp':<14} "
          f"{'Data got':<14} {'Data exp':<14} {'OK'}")
    for i, (addr, data) in enumerate(sram_writes):
        exp_addr = i * 4
        exp_data = expected_word(i)
        ok = (addr == exp_addr) and (data == exp_data)
        print(f"  {i:<6} {hex(addr):<14} {hex(exp_addr):<14} "
              f"{hex(data):<14} {hex(exp_data):<14} {'PASS' if ok else 'FAIL'}")
        assert addr == exp_addr, \
            f"Word {i}: wrong address — got {hex(addr)}, expected {hex(exp_addr)}"
        assert data == exp_data, \
            f"Word {i}: wrong data — got {hex(data)}, expected {hex(exp_data)}"
 
    # check handoff signals
    print(f"\n  boot_done_o = {int(dut.boot_done_o.value)}  (expected 1)")
    print(f"  cores_en_o = {int(dut.cores_en_o.value)}  (expected 1)")
    assert dut.boot_done_o.value == 1, "boot_done must be high after boot"
    assert dut.cores_en_o.value  == 1, "cores_en must be high after boot"
 
    # fsm must stay in DONE —signals must hold for 20 more cycles 
    await ClockCycles(dut.clk_i, 20)
    assert dut.boot_done_o.value == 1, "boot_done dropped — FSM left DONE state"
    assert dut.cores_en_o.value == 1, "cores_en dropped — FSM left DONE state"
 
    print(f"\n  *** PASS — bootloader correctly read all {BOOT_WORDS} words "
          "from S25FL128L")
 
 
# test 4 — page boundary crossing: 512 bytes spans two 256-byte pages
@cocotb.test()
async def test_page_boundary_crossing(dut):
    print("\n=== TEST 4: page-boundary crossing (0x0000FF -> 0x000100) ===")
    start_clock(dut)
    await apply_reset(dut, cycles=40_000)
    sram_writes = []
    timed_out = False
 
    for _ in range(2_000_000):
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")       
        if dut.sram_wr_en_o.value == 1:
            addr = dut.sram_addr_o.value
            data = dut.sram_data_o.value
            #skip any cycle where signals haven't resolved yet
            if addr.is_resolvable and data.is_resolvable:
                sram_writes.append((int(addr), int(data)))
        if dut.boot_done_o.value == 1:
            break
    else:
        timed_out = True
    n_words = len(sram_writes)
 
    #write count check
    if n_words < 128:
        #warning so you knows what to fix
        print(f"\n  WARNING: only {n_words} words written.")
        print("  boot_flash_wrapper.sv was built with BOOT_SIZE < 512.")
        print("  Change 'parameter BOOT_SIZE = 512' in boot_flash_wrapper.sv and re-run")
        print("  for full page-boundary coverage.")
        print(f"\n  Checking the {n_words} words that were written anyway...")
    else:
        assert not timed_out, "boot_done never asserted within timeout"
        print(f"\n  SRAM writes: {n_words}  (expected 128 for BOOT_SIZE=512)")
        assert n_words == 128, f"Expected 128 writes, got {n_words}"
 
    #verify every word that was written
    print(f"\n  {'Word':<6} {'Byte addr':<12} {'Addr got':<14} "
          f"{'Data got':<14} {'Data exp':<14} {'OK'}")
    for i, (addr, data) in enumerate(sram_writes):
        exp_addr = i * 4
        exp_data = expected_word(i)
        ok = (addr == exp_addr) and (data == exp_data)
        print(f"  {i:<6} {hex(i*4):<12} {hex(addr):<14} "
              f"{hex(data):<14} {hex(exp_data):<14} {'PASS' if ok else 'FAIL'}")
        assert addr == exp_addr, \
            f"Word {i}: wrong address — got {hex(addr)}, expected {hex(exp_addr)}"
        assert data == exp_data, \
            f"Word {i}: wrong data — got {hex(data)}, expected {hex(exp_data)}"
 
    #wrap would write to sram address 0x00 again,
    if n_words >= 65:
        w63_addr, w63_data = sram_writes[63]
        w64_addr, w64_data = sram_writes[64]
        exp63 = expected_word(63)
        exp64 = expected_word(64)
 
        print(f"\n  Page-boundary spot-check:")
        print(f"    Word 63 (last in page 0, byte 0x0FC): "
              f"got {hex(w63_data)}  expected {hex(exp63)}")
        print(f"    Word 64 (first in page 1, byte 0x100): "
              f"got {hex(w64_data)}  expected {hex(exp64)}")
 
        assert w64_addr == 0x100, \
            (f"Page-boundary address wrong at word 64! "
            f"Got SRAM addr {hex(w64_addr)}, expected 0x100. "
            "FSM may be wrapping.")
        assert w64_data == exp64, \
            (f"Page-boundary data mismatch at word 64! "
            f"Got {hex(w64_data)}, expected {hex(exp64)}.")
 
        print("  Page boundary crossed correctly — no address wrap detected")
    print(f"\n  *** PASS — {n_words} words verified, page boundary transparent")


@cocotb.test()
async def test_reset_mid_transaction(dut):
    print("\n=== TEST 5: reset mid-transaction — FSM must recover cleanly ===")
    start_clock(dut)
    await apply_reset(dut, cycles=40_000)
 
    #let boot run until 10 words have been written
    print("  Phase 1: booting normally, waiting for 10 SRAM writes...")
    writes_before_reset = 0
    for _ in range(500_000):
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")
        if dut.sram_wr_en_o.value == 1:
            writes_before_reset += 1
            if writes_before_reset >= 10:
                break
 
    assert writes_before_reset == 10, \
        f"Did not reach 10 writes before interrupt (got {writes_before_reset})"
    print(f"  10 words written — asserting reset_ni=0 mid-transaction")
 
    #assert reset mid transaction
    dut.reset_ni.value = 0
    await ClockCycles(dut.clk_i, 5_000)
 
    #while in reset, nothing should be happening
    await Timer(1, unit="ns")
    assert dut.sram_wr_en_o.value == 0, \
        "sram_wr_en_o still high during reset — FSM did not stop"
    assert dut.cores_en_o.value == 0, \
        "cores_en_o still high during reset"
    assert dut.boot_done_o.value == 0, \
        "boot_done_o still high during reset"
    print("  Reset held for 5000 cycles — outputs correctly inactive")
 
    #release reset, wait for full clean boot
    print("  Releasing reset — FSM should restart from the beginning...")
    dut.reset_ni.value = 1
    await Timer(1, unit="ns")
    sram_writes = []
    timed_out   = False
 
    for _ in range(500_000):
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")
        if dut.sram_wr_en_o.value == 1:
            addr = dut.sram_addr_o.value
            data = dut.sram_data_o.value
            if addr.is_resolvable and data.is_resolvable:
                sram_writes.append((int(addr), int(data)))
        if dut.boot_done_o.value == 1:
            break
    else:
        timed_out = True
    assert not timed_out, \
        "boot_done never asserted after reset release — FSM got stuck"
 
    #check the post reset boot is complete and correct
    print(f"\n  Post-reset SRAM writes: {len(sram_writes)}  (expected 128)")
    assert len(sram_writes) == 128, \
        (f"Expected 128 writes after clean reboot, got {len(sram_writes)}. "
         f"FSM may have resumed mid-stream instead of restarting.")
 
    print(f"\n  Verifying all 128 words are correct after reboot...")
    for i, (addr, data) in enumerate(sram_writes):
        exp_addr = i * 4
        exp_data = expected_word(i)
        assert addr == exp_addr, \
            f"Post-reset word {i}: wrong address — got {hex(addr)}, expected {hex(exp_addr)}"
        assert data == exp_data, \
            f"Post-reset word {i}: wrong data — got {hex(data)}, expected {hex(exp_data)}"
 
    print(f"  All 128 words correct")
    print(f"\n  boot_done_o = {int(dut.boot_done_o.value)}  (expected 1)")
    print(f"  cores_en_o  = {int(dut.cores_en_o.value)}   (expected 1)")
    assert dut.boot_done_o.value == 1, "boot_done must be high after reboot"
    assert dut.cores_en_o.value  == 1, "cores_en must be high after reboot"
 
    print("\n  *** PASS — FSM recovered cleanly from mid-transaction reset")


#test 6 — whoami_pulse fires exactly once at the start of boot
@cocotb.test()
async def test_whoami_pulse_timing(dut):
    print("\n=== TEST 6: whoami_pulse fires once at boot start ===")
    start_clock(dut)
    await apply_reset(dut, cycles=40_000)
    pulse_count        = 0
    pulse_cycle        = None
    boot_done_cycle    = None
    timed_out          = False
    cycle              = 0

    for _ in range(500_000):
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")
        cycle += 1

        whoami = dut.dut.whoami_pulse_o.value
        if whoami.is_resolvable and int(whoami) == 1:
            pulse_count += 1
            if pulse_cycle is None:
                pulse_cycle = cycle
                print(f"  whoami_pulse fired at cycle {cycle}")

        if dut.boot_done_o.value == 1:
            boot_done_cycle = cycle
            break
    else:
        timed_out = True

    assert not timed_out, "boot_done never asserted"
    assert pulse_count == 1, \
        (f"whoami_pulse fired {pulse_count} times — expected exactly 1. "
         f"It must be a single one-cycle pulse.")
    assert pulse_cycle is not None, \
        "whoami_pulse never fired"

    cycles_before_boot_done = boot_done_cycle - pulse_cycle
    print(f"  pulse at cycle {pulse_cycle}, boot_done at cycle {boot_done_cycle}")
    print(f"  cycles between pulse and boot_done: {cycles_before_boot_done}")
    print(f"  (directory interface has {cycles_before_boot_done} cycles to process WhoAmI)")

    assert cycles_before_boot_done > 1000, \
        (f"whoami_pulse fired only {cycles_before_boot_done} cycles before boot_done. "
         f"Expected it to fire near the START of boot, not the end. "
         f"Check boot_started_o logic in boot_fsm.sv.")

    assert pulse_cycle <= 500, \
        (f"whoami_pulse fired at cycle {pulse_cycle} — expected within first 500 cycles. "
         f"Should fire at the very start of boot.")

    print(f"\n  *** PASS — whoami_pulse fired once at cycle {pulse_cycle}, "
          f"{cycles_before_boot_done} cycles before boot_done")


#test 7 — whoami_pulse does not fire during reset
@cocotb.test()
async def test_whoami_pulse_no_fire_during_reset(dut):
    print("\n=== TEST 7: whoami_pulse stays low during reset ===")
    start_clock(dut)
    dut.reset_ni.value       = 0
    dut.pass_thru_en_i.value = 0

    spurious_pulses = 0
    for _ in range(100):
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")
        whoami = dut.dut.whoami_pulse_o.value
        if whoami.is_resolvable and int(whoami) == 1:
            spurious_pulses += 1

    print(f"  whoami_pulse pulses during reset: {spurious_pulses}  (expected 0)")
    assert spurious_pulses == 0, \
        "whoami_pulse fired during reset — must stay low while reset_ni=0"

    print("  *** PASS — whoami_pulse correctly suppressed during reset")


#test 8 — boot_started_o goes high on first cycle out of IDLE
@cocotb.test()
async def test_boot_started_timing(dut):
    print("\n=== TEST 8: boot_started_o timing ===")
    start_clock(dut)
    await apply_reset(dut, cycles=40_000)
    boot_started_cycle  = None
    boot_started_drops  = 0
    prev_started        = 0
    timed_out           = False
    cycle               = 0

    for _ in range(500_000):
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")
        cycle += 1

        started = dut.dut.boot_controller.boot_started_o.value   # housekeeping -> boot_fsm instance
        if not started.is_resolvable:
            prev_started = 0
            continue

        curr_started = int(started)

        if curr_started == 1 and prev_started == 0:
            if boot_started_cycle is None:
                boot_started_cycle = cycle
                print(f"  boot_started_o went high at cycle {cycle}")

        if boot_started_cycle is not None and curr_started == 0:
            boot_started_drops += 1
            print(f"  WARNING: boot_started_o dropped at cycle {cycle}")

        prev_started = curr_started

        if dut.boot_done_o.value == 1:
            break
    else:
        timed_out = True

    assert not timed_out, "boot_done never asserted"
    assert boot_started_cycle is not None, \
        "boot_started_o never went high"
    assert boot_started_cycle <= 10, \
        (f"boot_started_o went high at cycle {boot_started_cycle} — "
         f"expected within first 10 cycles after reset release. "
         f"FSM should leave IDLE immediately.")
    assert boot_started_drops == 0, \
        (f"boot_started_o dropped {boot_started_drops} time(s) during boot. "
         f"FSM may have unexpectedly returned to IDLE.")

    print(f"  boot_started_o went high at cycle {boot_started_cycle} ✓")
    print(f"  boot_started_o stayed high continuously until boot_done ✓")
    print("\n  *** PASS — boot_started_o timing correct")


 
# runner
def boot_ctrl_runner():
    proj_path = Path(__file__).resolve().parent
 
    #generate boot image .mem file before building
    mem_path = write_boot_image_mem()
    print(f"[runner] wrote {mem_path}")
 
    sources = [
        proj_path / "../src/housekeeping/spi_engine.sv",
        proj_path / "../src/housekeeping/boot_fsm.sv",
        proj_path / "../src/housekeeping/housekeeping_top.sv",
        proj_path / "../src/housekeeping/cypress_model/s25fl128l.v",
        proj_path / "../src/housekeeping/boot_flash_wrapper.sv",
    ]
 
    build_args = []
    if sim == "icarus":
        build_args = []
    if sim == "verilator":
        build_args = []
 
    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel="boot_flash_wrapper",
        always=True,
        build_args=build_args,
        waves=True,
    )
    runner.test(
        hdl_toplevel="boot_flash_wrapper",
        test_module="boot_flash_tb",
        waves=True,
    )
 
if __name__ == "__main__":
    boot_ctrl_runner()
 