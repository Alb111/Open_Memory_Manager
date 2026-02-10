# external 
import copy
import asyncio

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
        self.arbiter: WeightedRoundRobinArbiter = WeightedRoundRobinArbiter(size, [1,1], self.memory.axi_handler)

        # num cores
        self.num_cores: int = size

        # state of those cores
        self.finsihed_cores: int = 0

        # arr of those cores
        self.cores: List[Core] = []
        for i in range(size):
            self.cores.append(Core(i,self.arbiter.axi_handler_arbiter))

        # build work load for each of those cores
        self.core_workloads: List[List[test_case]] = [[] for i in range(size)]
        for i in range(0, len(test_cases), size):
            for k in range(size):
                self.core_workloads[k].append(test_cases[i+k])


    async def core_worker_write(self, core_id: int, test_case_in: test_case, valid_testcase: bool) -> axi_request:  # try to write data
        if valid_testcase:
            return await self.cores[core_id].write(test_case_in.data_addr, test_case_in.data, test_case_in.wstb)
        else:
            return await self.cores[core_id].write_nothing()
              

    async def core_worker_read(self, core_id: int, test_case_in: test_case, valid_testcase: bool) -> axi_request:  # try to write data
        if valid_testcase:
            return await self.cores[core_id].read(test_case_in.data_addr)
        else:
            return await self.cores[core_id].read_nothing()
              
    
    
    async def start_sim(self):

        print("=" * 70)
        print("Starting CPU Simulation")
        print("=" * 70)
        

        print("=" * 70)
        print("Writing Stuff")
        print("=" * 70)
        

        # to keep workloads intact for later use
        core_workloads_copy: List[List[test_case]] = copy.deepcopy(self.core_workloads)
        
        while any(core_workloads_copy):
            tasks: List[asyncio.Task[axi_request]] = []        
            for core_id in range(self.num_cores):
                # check if test_case exists
                valid_testcase: bool = False
                core_testcase: test_case = test_case(-1, -1, -1)           
                if len(core_workloads_copy[core_id]) > 0:
                    core_testcase: test_case = core_workloads_copy[core_id][-1]           
                    valid_testcase = True
             
            
                tasks.append(
                    asyncio.create_task(
                        self.core_worker_write(core_id, core_testcase, valid_testcase),
                        name=f"Core-{core_id}"
                    )
                
                )

            # wait for all them and pop ones that are done
            cur_cycle_results: List[axi_request] = await asyncio.gather(*tasks)
            for index, result in enumerate(cur_cycle_results):
                if result.mem_ready:
                    core_workloads_copy[index].pop()                        

        
        print("=" * 70)
        print("Reading Stuff Out")
        print("=" * 70)
        

        # to keep workloads intact for later use
        core_workloads_copy: List[List[test_case]] = copy.deepcopy(self.core_workloads)
        
        while any(core_workloads_copy):
            tasks: List[asyncio.Task[axi_request]] = []        
            for core_id in range(self.num_cores):
                # check if test_case exists
                valid_testcase: bool = False
                core_testcase: test_case = test_case(-1, -1, -1)           
                if len(core_workloads_copy[core_id]) > 0:
                    core_testcase: test_case = core_workloads_copy[core_id][-1]           
                    valid_testcase = True
             
            
                tasks.append(
                    asyncio.create_task(
                        self.core_worker_read(core_id, core_testcase, valid_testcase),
                        name=f"Core-{core_id}"
                    )
                
                )

            # wait for all them and pop ones that are done
            cur_cycle_results: List[axi_request] = await asyncio.gather(*tasks)
            for index, result in enumerate(cur_cycle_results):
                if result.mem_ready:
                    print(f" data at {result.mem_addr} is {result.mem_rdata}")
                    core_workloads_copy[index].pop()                        

            

        print("=" * 70)
        print("We Did it")
        print("=" * 70)
        

        # loop until all worloads stack are empty
        # while any(core_workloads_copy):
        #     print("while loop start")
        #     for index, coreworkload in enumerate(core_workloads_copy):
        #         print(f"curr corr is {index}")
        #         # if more tasks exist
        #         if coreworkload: 
        #             test_case: test_case = coreworkload[-1] # top of list

        #             # try to write data
        #             result_axi: axi_request = await self.cores[index].write(test_case.data_addr, test_case.data, test_case.wstb)


        #             if result_axi is None:
        #                 raise TypeError("results_axi is none")

        #             # arbitrate gave core turn
        #             if result_axi.mem_ready:
        #                 core_workloads_copy.pop()                        

        #             # arbitrate didnt give core turn yet, so keep task in stack

        # print("all wrtie tasks done")
                    
                   





        


        # # atempt_num: int = 0

        # # idle_request: axi_request = axi_request(False, False, False, 0, 0, 0, 0)
        
        # while True:
        #     if workload:
        #         test_case: test_case = workload[-1] # top of list

        #         if result_axi is None:
        #             raise TypeError("results_axi is none")

        #         if result_axi.mem_ready:
        #             workload.pop()                        
        #         else:
        #             # print(f"  Core {core_id}: ✗ Denied, will retry, currently on Attempt {atempt_num} ")
        #             atempt_num += 1

                    
        #     else:
        #         # print(f"Core {core_id}: Finished all tasks")
        #         self.finsihed_cores += 1 

        #         # while self.finsihed_cores != self.num_cores:
        #             # result_axi = await self.arbiter.axi_handler_arbiter(idle_request, core_id)

        #         # print(f"  Core {core_id}: All cores done, exiting")
        #         break
                               
