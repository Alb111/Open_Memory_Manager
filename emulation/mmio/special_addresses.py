from axi_request import axi_request
from enum import Enum

class SP_ADDR(Enum):

    WHOAMI    = {0x8000_0000}
    MMIO_CSR  = {0x8000_0018}
    MMIO_DATA = {0x8000_0010, 
                 0x8000_0011, 
                 0x8000_0012, 
                 0x8000_0013, 
                 0x8000_0014, 
                 0x8000_0015, 
                 0x8000_0016, 
                 0x8000_0017}



