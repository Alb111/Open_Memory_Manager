# multi core 
from core import Core
from axi_request import axi_request
from testcase import test_case
from typing import Callable, List

class CPU: 
    def send_core_requests(self, request: axi_request, cpu_id: int, abritate: Callable[[list[int]], list[int]]) -> None:

        self.data_from_cores_valid[cpu_id] = True

        all_request_arrived: bool = False
        for valid in self.data_from_cores_valid:
            all_request_arrived = all_request_arrived & (valid == 1)

        

        

        

        

        



        

        # for data in self.d


        


        


            

         
        return

    def __init__(self, size_in: int, test_cases: List[test_case]) -> None:
        self.size: int = size_in 
        self.cores: List[Core] = []
        self.data_from_cores: List[axi_request | None] = [None] * size_in
        self.data_from_cores_valid: List[int] = [0] * size_in


        for i in range(size_in):
            self.cores.append(Core(i, self.send_core_requests, test_cases)




        
        
        

    # def recieve_core_requests(self):



    




    
            

        


    

    




        
