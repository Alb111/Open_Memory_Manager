from mmio import MMIO
from special_addresses import SP_ADDR
from axi_request import axi_request

class sp_addr_handler:

    def __init__(self, WhoAmI : int):
        self.mem_packet  : axi_request = None

        self.MMIO = MMIO()

        self.cc_packet_o : axi_request = None
        self.WAI_r       : int = WhoAmI
        
    def _yield_WAI(self):
        self.mem_packet.mem_rdata = self.WAI_r
    
    def handle_req(self, axi_packet : axi_request):
        self.cc_packet_o = None
        addr = axi_packet.mem_addr

        if addr in SP_ADDR.WHOAMI:
            self._yield_WAI()

        elif addr in SP_ADDR.MMIO_CSR or addr in SP_ADDR.MMIO_DATA:
            self.MMIO.handle_req(axi_packet)

        # normal address passthrough
        else:
            self.cc_packet_o = axi_packet
