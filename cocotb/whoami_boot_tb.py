import os
import shutil
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge, ClockCycles
from cocotb_tools.runner import get_runner

sim      = os.getenv("SIM", "icarus")
pdk_root = Path("../gf180mcu")
pdk      = os.getenv("PDK", "gf180mcuD")

hdl_toplevel = "whoami_wrapper"

SER_PINS    = 9
MAX_MSG_LEN = 36

WHOAMI_OPCODE = 0xE
CPU_ID_0      = 0x00
CPU_ID_1      = 0x01

def write_boot_image_mem():
    sim_build = Path(__file__).resolve().parent / "sim_build"
    sim_build.mkdir(exist_ok=True)
    out = sim_build / "boot_image.mem"
    # using 32 bytes (8 words) so the test runs faster
    boot_data = [(i & 0xFF) ^ 0xA5 for i in range(32)]
    with open(out, "w") as f:
        f.write("@000000\n")
        for byte in boot_data:
            f.write(f"{byte:02X}\n")
    return out


def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())


async def apply_reset(dut, cycles=40_000):
    dut.rst_ni.value         = 0
    dut.pass_thru_en_i.value = 0
    await ClockCycles(dut.clk_i, cycles)
    dut.rst_ni.value = 1
    await Timer(1, unit="ns")


async def receive_serial_packet(req_signal, serial_signal, clk, timeout=10_000):
    # wait for req to go high
    for _ in range(timeout):
        await RisingEdge(clk)
        await Timer(1, unit="ns")
        if req_signal.value.is_resolvable and int(req_signal.value) == 1:
            break
    else:
        return None
    # shift in serial words while req is high
    shift_chunks = []
    for _ in range(timeout):
        await RisingEdge(clk)
        await Timer(1, unit="ns")
        if serial_signal.value.is_resolvable:
            shift_chunks.append(int(serial_signal.value))
        if not req_signal.value.is_resolvable or int(req_signal.value) == 0:
            break
    return shift_chunks


def decode_whoami_packet(shift_chunks, num_pins=SER_PINS):
    if len(shift_chunks) < 1:
        return None, None
    # use the last received chunk which is shift_arr[0] (the lowest bits)
    raw = shift_chunks[-1] & 0x1FF   # 9 bits
    opcode = raw & 0xF          # bits [3:0]
    cpu_id = (raw >> 4) & 0x1F  # bits [8:4] — 5 bits sufficient for cpu_id 0 and 1
    return opcode, cpu_id


#test 1 — WhoAmI packet is transmitted on dir_interface_0 serial output
@cocotb.test()
async def test_whoami_transmitted_cpu0(dut):
    print("\n=== TEST 1: WhoAmI packet transmitted on directory_interface_0 ===")
    start_clock(dut)
    await apply_reset(dut, cycles=40_000)
    # start receiving in parallel with boot
    packet_task = cocotb.start_soon(
        receive_serial_packet(
            dut.req_o_0, dut.serial_o_0, dut.clk_i, timeout=500_000
        )
    )
    # wait for boot_done or packet received
    boot_done_cycle = None
    cycle = 0
    for _ in range(500_000):
        await RisingEdge(dut.clk_i)
        cycle += 1
        if dut.boot_done_o.value == 1:
            boot_done_cycle = cycle
            break

    shift_chunks = await packet_task
    assert shift_chunks is not None, \
        ("No serial transmission detected on directory_interface_0. "
         "req_o_0 never went high — whoami_pulse may not be reaching "
         "send_WhoAmI_i on i_directory_interface_0.")

    opcode, cpu_id = decode_whoami_packet(shift_chunks)

    print(f"  Received {len(shift_chunks)} serial chunks: {[hex(c) for c in shift_chunks]}")
    print(f"  Decoded opcode : {hex(opcode) if opcode is not None else 'None'}  (expected {hex(WHOAMI_OPCODE)})")
    print(f"  Decoded cpu_id : {hex(cpu_id) if cpu_id is not None else 'None'}  (expected {hex(CPU_ID_0)})")

    assert opcode == WHOAMI_OPCODE, \
        (f"Wrong opcode in WhoAmI packet from interface_0: "
         f"got {hex(opcode)}, expected {hex(WHOAMI_OPCODE)}")
    assert cpu_id == CPU_ID_0, \
        (f"Wrong cpu_id in WhoAmI packet from interface_0: "
         f"got {hex(cpu_id)}, expected {hex(CPU_ID_0)}")

    print(f"\n  WhoAmI correctly transmitted well before boot_done (cycle {boot_done_cycle})")
    print("  *** PASS — directory_interface_0 transmitted correct WhoAmI packet")


#test 2 — WhoAmI packet is transmitted on dir_interface_1 serial output
@cocotb.test()
async def test_whoami_transmitted_cpu1(dut):
    print("\n=== TEST 2: WhoAmI packet transmitted on directory_interface_1 ===")
    start_clock(dut)
    await apply_reset(dut, cycles=40_000)

    packet_task = cocotb.start_soon(
        receive_serial_packet(
            dut.req_o_1, dut.serial_o_1, dut.clk_i, timeout=500_000
        )
    )
    for _ in range(500_000):
        await RisingEdge(dut.clk_i)
        if dut.boot_done_o.value == 1:
            break

    shift_chunks = await packet_task
    assert shift_chunks is not None, \
        ("No serial transmission detected on directory_interface_1. "
         "req_o_1 never went high.")

    opcode, cpu_id = decode_whoami_packet(shift_chunks)

    print(f"  Received {len(shift_chunks)} serial chunks: {[hex(c) for c in shift_chunks]}")
    print(f"  Decoded opcode : {hex(opcode) if opcode is not None else 'None'}  (expected {hex(WHOAMI_OPCODE)})")
    print(f"  Decoded cpu_id : {hex(cpu_id) if cpu_id is not None else 'None'}  (expected {hex(CPU_ID_1)})")

    assert opcode == WHOAMI_OPCODE, \
        (f"Wrong opcode in WhoAmI packet from interface_1: "
         f"got {hex(opcode)}, expected {hex(WHOAMI_OPCODE)}")
    assert cpu_id == CPU_ID_1, \
        (f"Wrong cpu_id in WhoAmI packet from interface_1: "
         f"got {hex(cpu_id)}, expected {hex(CPU_ID_1)}")

    print("  *** PASS — directory_interface_1 transmitted correct WhoAmI packet")


#test 3 — whoami_pulse deasserts after handshake completes
@cocotb.test()
async def test_whoami_pulse_deasserts(dut):
    print("\n=== TEST 3: whoami_pulse deasserts after handshake ===")
    start_clock(dut)
    await apply_reset(dut, cycles=40_000)
    pulse_went_high  = False
    pulse_went_low   = False
    pulse_high_start = None
    pulse_low_cycle  = None
    timed_out        = False
    cycle            = 0

    for _ in range(500_000):
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")
        cycle += 1
        whoami = dut.whoami_pulse_o.value
        if not whoami.is_resolvable:
            continue
        curr = int(whoami)
        if curr == 1 and not pulse_went_high:
            pulse_went_high  = True
            pulse_high_start = cycle
            print(f"  whoami_pulse went high at cycle {cycle}")

        if pulse_went_high and curr == 0 and not pulse_went_low:
            pulse_went_low  = True
            pulse_low_cycle = cycle
            print(f"  whoami_pulse went low at cycle {cycle} "
                  f"(held high for {cycle - pulse_high_start} cycles)")

        if dut.boot_done_o.value == 1:
            break
    else:
        timed_out = True

    assert not timed_out,      "boot_done never asserted"
    assert pulse_went_high,    "whoami_pulse never went high"
    assert pulse_went_low,     \
        ("whoami_pulse never went low — handshake never completed. "
         "Check whoami_ready_i path and c0/c1_tser_ready wiring.")

    # verify it stays low — no re-transmission
    extra_pulses = 0
    for _ in range(1000):
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")
        whoami = dut.whoami_pulse_o.value
        if whoami.is_resolvable and int(whoami) == 1:
            extra_pulses += 1

    assert extra_pulses == 0, \
        (f"whoami_pulse went high again {extra_pulses} time(s) after handshake. "
         f"whoami_sent latch may not be working correctly.")

    print(f"  whoami_pulse stayed low after handshake — no re-transmission")
    print("  *** PASS — whoami_pulse correctly deasserts after handshake")


#test 4 — both interfaces transmit before boot_done
@cocotb.test()
async def test_whoami_before_boot_done(dut):
    print("\n=== TEST 4: both WhoAmI packets transmitted before boot_done ===")
    start_clock(dut)
    await apply_reset(dut, cycles=40_000)
    c0_req_went_high = False
    c0_req_done      = False
    c1_req_went_high = False
    c1_req_done      = False
    boot_done_cycle  = None
    c0_done_cycle    = None
    c1_done_cycle    = None
    cycle            = 0

    for _ in range(500_000):
        await RisingEdge(dut.clk_i)
        await Timer(1, unit="ns")
        cycle += 1
        c0_req = int(dut.req_o_0.value) if dut.req_o_0.value.is_resolvable else 0
        c1_req = int(dut.req_o_1.value) if dut.req_o_1.value.is_resolvable else 0
        if c0_req == 1:
            c0_req_went_high = True
        if c0_req_went_high and c0_req == 0 and not c0_req_done:
            c0_req_done   = True
            c0_done_cycle = cycle

        if c1_req == 1:
            c1_req_went_high = True
        if c1_req_went_high and c1_req == 0 and not c1_req_done:
            c1_req_done   = True
            c1_done_cycle = cycle

        if dut.boot_done_o.value == 1:
            boot_done_cycle = cycle
            break

    assert boot_done_cycle is not None, "boot_done never asserted"
    assert c0_req_done, \
        "directory_interface_0 never completed a serial transmission"
    assert c1_req_done, \
        "directory_interface_1 never completed a serial transmission"

    print(f"  interface_0 transmission complete at cycle {c0_done_cycle}")
    print(f"  interface_1 transmission complete at cycle {c1_done_cycle}")
    print(f"  boot_done asserted at cycle {boot_done_cycle}")

    assert c0_done_cycle < boot_done_cycle, \
        (f"interface_0 WhoAmI finished at cycle {c0_done_cycle} which is "
         f"AFTER boot_done at cycle {boot_done_cycle}!")
    assert c1_done_cycle < boot_done_cycle, \
        (f"interface_1 WhoAmI finished at cycle {c1_done_cycle} which is "
         f"AFTER boot_done at cycle {boot_done_cycle}!")

    margin_0 = boot_done_cycle - c0_done_cycle
    margin_1 = boot_done_cycle - c1_done_cycle
    print(f"\n  Margin before boot_done: interface_0={margin_0} cycles, "
          f"interface_1={margin_1} cycles")
    print("  *** PASS — both WhoAmI packets complete before CPU cores are released")


# Runner
def whoami_runner():
    proj_path = Path(__file__).resolve().parent
    sim_build  = proj_path / "sim_build"
    sim_build.mkdir(exist_ok=True)

    mem_path = write_boot_image_mem()
    print(f"[runner] wrote {mem_path}")

    secr_src = proj_path / "../src/housekeeping/cypress_model/s25fl128lSECR.mem"
    if secr_src.exists():
        shutil.copy(secr_src, sim_build / "s25fl128lSECR.mem")

    sram_macro = (Path(pdk_root) / pdk /
                  "libs.ref/gf180mcu_fd_ip_sram/verilog/"
                  "gf180mcu_fd_ip_sram__sram512x8m8wm1.v")

    sources = [
        sram_macro,
        proj_path / "../src/mem_ctrl/mem512x32.sv",
        proj_path / "../src/mem_ctrl/mem2048x32.sv",
        proj_path / "../src/housekeeping/spi_engine.sv",
        proj_path / "../src/housekeeping/boot_fsm.sv",
        proj_path / "../src/housekeeping/housekeeping_top.sv",
        proj_path / "../src/housekeeping/cypress_model/s25fl128l.v",
        proj_path / "../src/interposer_interface/tserializer.sv",
        proj_path / "../src/interposer_interface/rserializer.sv",
        proj_path / "../src/interposer_interface/lossy_pipe_stage.sv",
        proj_path / "../src/interposer_interface/directory_interface.sv",
        proj_path / "../src/housekeeping/whoami_wrapper.sv",
    ]

    runner = get_runner(sim)
    runner.build(
        sources=sources,
        hdl_toplevel="whoami_wrapper",
        always=True,
        build_args=[],
        waves=True,
    )
    runner.test(
        hdl_toplevel="whoami_wrapper",
        test_module="whoami_boot_tb",
        waves=True,
    )

if __name__ == "__main__":
    whoami_runner()