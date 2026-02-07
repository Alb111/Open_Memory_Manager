# types
from testcase import test_case
from typing import List

# hardware emulators
from CPU import CPU


# testing
testcases: List[test_case] = []
for i in range(10):
    testcases.append(test_case(i,i, 0b1111))

to_the_moon: CPU = CPU(2, testcases)

to_the_moon.start_sim()


            
        
        
        
        

            

    



























