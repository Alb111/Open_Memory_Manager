# types
from axi_request import axi_request

class MemoryController:
    def __init__(self):
        self.sram: dict[int, int] = {}

    async def read(self, address: int) -> int:
        if address in self.sram:
            return self.sram[address]
        else:
            return 0

    async def write(self, address: int, data: int, write_strobe: int) -> None:

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
    
    async def axi_handler(self, request: axi_request) -> axi_request:
        # we get a valid mem request and handshake
        if request.mem_valid is True:
        
            # read
            if request.mem_wstrb == 0:
                request.mem_rdata = await self.read(request.mem_addr)
                request.mem_ready = True        

            # write 
            else:
                await self.write(request.mem_addr, request.mem_wdata, request.mem_wstrb)
                request.mem_ready = True        
             
        return request 
