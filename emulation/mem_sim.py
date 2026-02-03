import random

from dataclasses import dataclass
from typing import Callable


@dataclass
class axi_request:
    mem_valid: bool
    mem_instr: bool
    mem_ready: bool

    mem_addr: int
    mem_wdata: int 
    mem_wstrb: int
    mem_rdata: int

class CPU:
    def __init__(self, cpu_id: int, seralizer: Callable[[axi_request], axi_request]):
        self.cpu_id: int = cpu_id
        self.send: Callable[[axi_request], axi_request] = seralizer

    def read_rand(self) -> axi_request:
        # todo: fill in axi request randomly
        addr: int = random.randint(0, 0xFF)
        read_request:axi_request = axi_request(
            mem_valid= True,
            mem_instr=False,
            mem_ready=False,
            mem_addr=addr,
            mem_wdata=0,
            mem_wstrb=0b0000,
            mem_rdata=0)  
        return self.send(read_request)
    
    def read(self, addr: int) -> axi_request:
        read_request:axi_request = axi_request(
            mem_valid= True,
            mem_instr=False,
            mem_ready=False,
            mem_addr=addr,
            mem_wdata=0,
            mem_wstrb=0b0000,
            mem_rdata=0)
        return self.send(read_request)
  


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
        
        return self.send(write_request)
 
        

    def write_rand(self) -> axi_request:
        # todo: fill in axi request randomly
        addr = random.randint(0, 0xFF)
        data = random.randint(0, 0xFFFFFFFF)
        wstrb_vals = [
            0b0000, 
            0b0001, 
            0b0010, 
            0b0011, 
            0b0100, 
            0b0101, 
            0b0110, 
            0b0111, 
            0b1000, 
            0b1001, 
            0b1010, 
            0b1011, 
            0b1100, 
            0b1101, 
            0b1110, 
            0b1111, 
        ]

        write_request: axi_request = axi_request(
            mem_valid= True,
            mem_instr=False,
            mem_ready=False,
            mem_addr=addr,
            mem_wdata=data,
            mem_wstrb=random.choice(wstrb_vals),
            mem_rdata=0
        ) 
        
        return self.send(write_request)
 
 
class MemoryController:
    def __init__(self):
        self.sram: dict[int, int] = {}
    
    def read(self, address: int) -> int:
        if address in self.sram:
            return self.sram[address]
        else:
            return 0

    def write(self, address: int, data: int, write_strobe: int) -> None:

        # break write data into bytes
        byte0: int = data & 0x000F
        byte1: int = data & 0x00F0
        byte2: int = data & 0x0F00
        byte3: int = data & 0xF000

        # break the write strobe down into binary flags
        # and use it to build data to write
        data_to_write: int = 0
        temp: int = write_strobe
        
        # byte 3
        if temp % 2 == 1:
            data_to_write = data_to_write | byte3
        temp = temp // 2
        
        # byte 2     
        if temp % 2 == 1:
            data_to_write = data_to_write | byte2
        temp = temp // 2

        # byte 1
        if temp % 2 == 1:
            data_to_write = data_to_write | byte1
        temp = temp // 2

        # byte 0
        if temp % 2 == 1:
            data_to_write = data_to_write | byte0
        temp = temp // 2

        self.sram[address] = data_to_write
        return
    
    def axi_handler(self, request: axi_request) -> axi_request:
        # we get a valid mem request and handshake
        if request.mem_valid is True:
        
            # read
            if request.mem_wstrb == 0:
                request.mem_rdata = self.read(request.mem_addr)
                request.mem_ready = True        

            # write 
            else:
                self.write(request.mem_addr, request.mem_wdata, request.mem_wstrb)
                request.mem_ready = True        
             
        return request 



# testing
x: MemoryController = MemoryController()
y: CPU = CPU(0, x.axi_handler)

for i in range(100):
    y.write(i,i,0b1111)

for i in range(100):
    print(y.read(i))