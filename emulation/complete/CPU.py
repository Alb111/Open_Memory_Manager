# external 
import copy

# hardware emulators
from core import Core
from memory import MemoryController
from weighted_round_robin import WeightedRoundRobinArbiter

# types
from axi_request import axi_request
from testcase import test_case
from typing import List, Optional


class CPU: 
    def __init__(self, size: int, test_cases: List[test_case]) -> None:

        # setup memory 
        self.memory: MemoryController = MemoryController()

        # setup arbiter
        self.arbiter: WeightedRoundRobinArbiter = WeightedRoundRobinArbiter(size, [1]*size, self.memory.axi_handler)

        # num cores
        self.num_cores: int = size

        # arr of those cores
        self.cores: List[Core] = []
        for i in range(size):
            self.cores.append(Core(i,self.arbiter.axi_handler_arbiter))

        # build work load for each of those cores
        self.core_workloads: List[List[test_case]] = [[] for i in range(size)]
        for i in range(0, len(test_cases), size):
            for k in range(size):
                self.core_workloads[k].append(test_cases[i+k])

     
    def start_sim(self):

        # to keep workloads intact for later use
        core_workloads_copy: List[List[test_case]] = copy.deepcopy(self.core_workloads)

        # loop until all worloads stack are empty
        while any(core_workloads_copy):
            print("while loop start")
            for index, coreworkload in enumerate(core_workloads_copy):
                print(f"curr corr is {index}")
                # if more tasks exist
                if coreworkload: 
                    test_case: test_case = coreworkload[-1] # top of list

                    # try to write data
                    result_axi: Optional[axi_request] = self.cores[index].write(test_case.data_addr, test_case.data, test_case.wstb)

                    if result_axi is None:
                        raise TypeError("results_axi is none")

                    # arbitrate gave core turn
                    if result_axi.mem_ready:
                        core_workloads_copy.pop()                        

                    # arbitrate didnt give core turn yet, so keep task in stack

        print("all wrtie tasks done")
                    



                    






        
