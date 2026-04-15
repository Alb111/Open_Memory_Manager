# external libs
import logging

# types
from axi_request_types import axi_request

BYTE_MASKS = [0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000]

class MemoryController:

    def __init__(self, num_srams: int) -> None:
        self.sram: dict[int, int] = {}
        self.log = logging.getLogger(__name__)
        self.max_address: int = (1 << num_srams) - 1

    # read address, if not in address spcae return 0        
    async def read(self, address: int) -> int:

        if address > self.max_address:
            self.log.error("read err: address out of range, cant read")
            return 0

        found_val: int = self.sram.get(address, 0)
        self.log.debug(f"read addr={address:#010x} got={found_val:#010x}")
        return found_val

    async def write(self, address: int, data: int, write_strobe: int) -> None:

        self.log.debug(f"write addr={address:#010x} with {data:#010x}")
        # address not in physical address spcae
        if address > self.max_address:
            self.log.error("write err: address out of range, wrote nothing")
            return

        # assemble word to write based on bit mask
        data_to_write: int = 0
        for index, bit_mask in enumerate(BYTE_MASKS):
            byte: int = data & bit_mask
            if (write_strobe >> index) & 1: # shift and isolate last bit
                data_to_write |= byte        

        self.sram[address] = data_to_write
        return
    
    async def axi_handler(self, request: axi_request) -> axi_request:

        
        print("=== Directory to Memory ===")
        print(request)

        self.log.debug(f"memory axi handler started")        
        # we get a valid mem request and handshake
        if request.mem_valid:
        
            # read
            if request.mem_wstrb == 0:
                request.mem_rdata = await self.read(request.mem_addr)

            # write 
            else:
                print("did we even write")
                await self.write(request.mem_addr, request.mem_wdata, request.mem_wstrb)

            # mark request as done
            request.mem_ready = True        
             
        self.log.debug(f"memory axi handler ended")        
        print("=== Memory to Directory ===")
        print(request)
        return request 
