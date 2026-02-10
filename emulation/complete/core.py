from typing import Callable, Optional, Awaitable
from axi_request import axi_request

class Core:
    def __init__(self, cpu_id: int, axi_handler: Callable[[axi_request, int], Awaitable[axi_request]]):

        # cpe inentifier
        self.cpu_id: int = cpu_id

        # functions pointers to send and recive axi packets
        self.axi_send_and_recieve: Callable[[axi_request, int], Awaitable[axi_request]] = axi_handler

    ## SEND functions
    async def read(self, addr: int) -> axi_request:
        read_request:axi_request = axi_request(
            mem_valid= True,
            mem_instr=False,
            mem_ready=False,
            mem_addr=addr,
            mem_wdata=0,
            mem_wstrb=0b0000,
            mem_rdata=0)

        return await self.axi_send_and_recieve(read_request, self.cpu_id)


    async def read_nothing(self) -> axi_request:
        read_request:axi_request = axi_request(
            mem_valid= False,
            mem_instr=False,
            mem_ready=False,
            mem_addr=0,
            mem_wdata=0,
            mem_wstrb=0b0000,
            mem_rdata=0)

        return await self.axi_send_and_recieve(read_request, self.cpu_id)
    
    
    async def write(self, addr_in: int, data_in: int, wstb_in: int) -> axi_request:
        write_request: axi_request = axi_request(
            mem_valid= True,
            mem_instr=False,
            mem_ready=False,
            mem_addr=addr_in,
            mem_wdata=data_in,
            mem_wstrb=wstb_in,
            mem_rdata=0
        ) 

        # print("got to write request in core.py")
        
        return await self.axi_send_and_recieve(write_request, self.cpu_id)


    
    async def write_nothing(self) -> axi_request:
        write_request: axi_request = axi_request(
            mem_valid= False,
            mem_instr=False,
            mem_ready=False,
            mem_addr=0,
            mem_wdata=0,
            mem_wstrb=0,
            mem_rdata=0
        ) 

        # print("got to write request in core.py")
        
        return await self.axi_send_and_recieve(write_request, self.cpu_id)
           
    
    ## Testing
    # def test_send(self) -> None:
    #     # write all that data
    #     for test_case in self.test_cases:
    #         self.write(test_case.data_addr, test_case.data, test_case.wstb)

    #     # read all that data
    #     for test_case in self.test_cases:
    #         self.write(test_case.data_addr, test_case.data, test_case.wstb)

    # def test_recieve(self, recived: int) -> bool:
    #     if recived == self.test_cases[self.recived_axi_packts]:
    #         return True
    #     return False
            

        

    
         
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
     
    # ## Recieve functions
    # def axi_recieve_handler(self, axi_request: axi_request) -> axi_request:

    #     # ready valid handshake valid
    #     if axi_request.mem_ready == 1:
    #         if axi_request.mem_wstrb == 0:
    #             # read
    #             print(f"sucessfull read, address = {axi_request.mem_addr}, value = {axi_request.mem_rdata}")
    #         else:
    #             # write 
    #             print(f"sucessfull write, address = {axi_request.mem_addr}, value = {axi_request.mem_wdata}, strobe ")

    #         return axi_request

    #     # ready valid handshake not valid, try again
    #     else:
    #         return self.axi_send(axi_request, self.cpu_id)
