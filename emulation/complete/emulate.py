# external
import asyncio

# types
from testcase import test_case
from typing import List

# hardware emulators
from CPU import CPU

async def main():
    # prepare test cases
    testcases: List[test_case] = []
    for i in range(10):
        testcases.append(test_case(i, i, 0b1111))

    # create CPU
    to_the_moon: CPU = CPU(2, testcases)

    # await the async method
    x = await to_the_moon.start_sim()
    print(x)

# run the async main
asyncio.run(main())



            
        
        
        
        

            

    



























