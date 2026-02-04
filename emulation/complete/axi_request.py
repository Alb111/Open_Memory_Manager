from dataclasses import dataclass

@dataclass
class axi_request:
    mem_valid: bool
    mem_instr: bool
    mem_ready: bool

    mem_addr: int
    mem_wdata: int 
    mem_wstrb: int
    mem_rdata: int
