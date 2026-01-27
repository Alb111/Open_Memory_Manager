import random
from dataclasses import dataclass
from typing import List, Optional, Union

@dataclass
class read_request:
    cpu_id: int
    address: int
    
@dataclass
class write_request:
    cpu_id: int
    address: int
    data: int

cpu_request = Union[read_request, write_request]

class CPU:
    def __init__(self, cpu_id: int):
        self.cpu_id = requester_id

    def read(self) -> cpu_request:
        address = random.randint(0, 0xFF)        
        return write_request(cpu_id, address) 

    def write(self) -> cpu_request:
        address = random.randint(0, 0xFF)        
        data = random.randint(0, 0xFF)        
        return write_request(cpu_id, address, data) 


# todo    
# class Arbiter:























