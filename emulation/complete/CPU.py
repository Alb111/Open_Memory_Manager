# multi core 
from core import Core
from axi_request import axi_request
from typing import List, Tuple

class CPU: 
    def __init__(self, size_in: int = 2) -> None:
        self.size: int = size_in 
        self.cores: List[Core] = []
        self.data_from_cores: List[axi_request | None] = [None] * size_in
        self.data_from_cores_valid: List[bool] = []

        for i in range(size_in):
            self.cores.append(Core())

    def send_core_requests(self):
        

    def recieve_core_requests(self):



    




    
            

        


    

    




        
