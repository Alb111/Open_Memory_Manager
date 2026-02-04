import random
from typing import Callable
from axi_request import axi_request

class Core:
    def __init__(self, cpu_id: int, send_fucnt: Callable[[axi_request], axi_request]):
        self.cpu_id: int = cpu_id
        self.axi_send: Callable[[axi_request], axi_request] = send_fucnt
        self.axi_recive: Callable[[axi_request], None] = self.axi_recieve

    ## SEND functions
    def read(self, addr: int) -> axi_request:
        read_request:axi_request = axi_request(
            mem_valid= True,
            mem_instr=False,
            mem_ready=False,
            mem_addr=addr,
            mem_wdata=0,
            mem_wstrb=0b0000,
            mem_rdata=0)
        return self.axi_send(read_request)
    
    
    def write(self, addr_in: int, data_in: int, wstb_in: int) -> axi_request:
        write_request: axi_request = axi_request(
            mem_valid= True,
            mem_instr=False,
            mem_ready=False,
            mem_addr=addr_in,
            mem_wdata=data_in,
            mem_wstrb=wstb_in,
            mem_rdata=0
        ) 
        
        return self.axi_send(write_request)

    ## Recieve functions ----------------------------------------------------------------------------
    def axi_recieve(self, axi_request: axi_request) -> None:
        print("CPU Recieved Packet Start ------------------------------------------------------------------------------------")
        print(axi_request)
        print("CPU Recieved Packet End --------------------------------------------------------------------------------------")



    test  
 
    # def read_rand(self) -> axi_request:
    #     # todo: fill in axi request randomly
    #     addr: int = random.randint(0, 0xFF)
    #     read_request:axi_request = axi_request(
    #         mem_valid= True,
    #         mem_instr=False,
    #         mem_ready=False,
    #         mem_addr=addr,
    #         mem_wdata=0,
    #         mem_wstrb=0b0000,
    #         mem_rdata=0)  
    #     return self.axi_send(read_request)

    
    # def write_rand(self) -> axi_request:
    #     # todo: fill in axi request randomly
    #     addr = random.randint(0, 0xFF)
    #     data = random.randint(0, 0xFFFFFFFF)
    #     wstrb_vals = [
    #         0b0000, 
    #         0b0001, 
    #         0b0010, 
    #         0b0011, 
    #         0b0100, 
    #         0b0101, 
    #         0b0110, 
    #         0b0111, 
    #         0b1000, 
    #         0b1001, 
    #         0b1010, 
    #         0b1011, 
    #         0b1100, 
    #         0b1101, 
    #         0b1110, 
    #         0b1111, 
    #     ]

    #     write_request: axi_request = axi_request(
    #         mem_valid= True,
    #         mem_instr=False,
    #         mem_ready=False,
    #         mem_addr=addr,
    #         mem_wdata=data,
    #         mem_wstrb=random.choice(wstrb_vals),
    #         mem_rdata=0
    #     ) 
        
    #     return self.axi_send(write_request)
