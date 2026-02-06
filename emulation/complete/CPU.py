# multi core 
from core import Core
from axi_request import axi_request
from emulation.complete.memory import MemoryController
from emulation.complete.weighted_round_robin import WeightedRoundRobinArbiter
from testcase import test_case
from typing import List

class CPU: 
    def __init__(self, size: int, test_cases: List[test_case]) -> None:

        # setup memory 
        self.memory: MemoryController = MemoryController()

        # setup arbiter
        self.arbiter: WeightedRoundRobinArbiter(size, [1]*size, self.memory.axi_handler)

        # num cores
        self.num_cores: int = size

        # arr of those cores
        self.cores: List[Core] = []
        for i in range(size):
            self.cores.append(Core(i,))

        # build work load for each of those cores
        self.core_workloads: List[List[test_case]] = [[] for i in range(size)]
        for i in range(0, len(test_cases), size):
            for k in range(size):
                self.core_workloads[k].append(test_cases[i+k])
     

    def start(self):



    




    
            

        


    

    




        
