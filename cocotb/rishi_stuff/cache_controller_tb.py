import cocotb
from cocotb.triggers import RisingEdge
from cocotb.clock import Clock

# Import your model
from emulation.cache_v3 import CacheController
from emulation.axi_request_types import axi_request, axi_and_coherence_request


# ---------------------------
# Fake directory model (STUB)
# ---------------------------
async def fake_directory(req: axi_and_coherence_request):
    resp = axi_request(
        mem_valid=True,
        mem_ready=True,
        mem_instr=False,
        mem_addr=req.mem_addr,
        mem_wdata_or_msi_payload=0,
        mem_wstrb=0,
        mem_rdata=0xDEADBEEF  # dummy memory data
    )
    return resp


# ---------------------------
# Helper: DUT
# ---------------------------
async def drive_cpu_request(dut, req: axi_request):
    dut.mem_valid.value = req.mem_valid
    dut.mem_addr.value = req.mem_addr
    dut.mem_wdata.value = req.mem_wdata
    dut.mem_wstrb.value = req.mem_wstrb

    await RisingEdge(dut.clk)


# ---------------------------
# Helper: DUT response
# ---------------------------
def read_dut_response(dut):
    return {
        "mem_ready": int(dut.mem_ready.value),
        "mem_rdata": int(dut.mem_rdata.value)
    }


# ---------------------------
# Model TEST 
# ---------------------------
@cocotb.test()
async def test_cache_read_write(dut):

    # Start clock
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())

    # Create golden model
    model = CacheController(core_id=0, directory_axi_handler=fake_directory)

    # ---------------------------
    # TEST 1: READ MISS
    # ---------------------------
    req = axi_request(
        mem_valid=True,
        mem_ready=False,
        mem_instr=False,
        mem_addr=0x100,
        mem_wdata=0,
        mem_wstrb=0,
        mem_rdata=0
    )

    # Drive DUT
    await drive_cpu_request(dut, req)

    # Golden model expected output
    exp = await model.axi_handler_for_core(req)

    # Wait for DUT
    await RisingEdge(dut.clk)

    dut_out = read_dut_response(dut)

    assert dut_out["mem_ready"] == exp.mem_ready
    assert dut_out["mem_rdata"] == exp.mem_rdata


    # ---------------------------
    # TEST 2: WRITE HIT
    # ---------------------------
    req2 = axi_request(
        mem_valid=True,
        mem_ready=False,
        mem_instr=False,
        mem_addr=0x100,
        mem_wdata=0xAAAA5555,
        mem_wstrb=0xF,   # WRITE
        mem_rdata=0
    )

    await drive_cpu_request(dut, req2)

    exp2 = await model.axi_handler_for_core(req2)

    await RisingEdge(dut.clk)

    dut_out = read_dut_response(dut)

    assert dut_out["mem_ready"] == exp2.mem_ready
