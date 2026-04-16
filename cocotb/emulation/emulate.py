# external
import asyncio

# types
from testcase import test_case
from typing import List

# hardware emulators
from CPU import CPU


async def write_after_read_test(): # invalid to shared to modified
    testcases = [

        test_case(0x10, 0x0000, 0b0000), # Core 1: Read (Must fetch C0's new data)
        test_case(0x10, 0xAAAA, 0b1111), # Core 0: Write (Forces C1 to Invalid)

        test_case(0x10, 0x0000, 0b0000), # Core 1: Read
        test_case(0x10, 0x0000, 0b0000), # Core 0: Read
    ]

    # create CPU
    to_the_moon: CPU = CPU(2, testcases)

    # await the async method
    x = await to_the_moon.start_sim()


# async def dirty_snooping(): # modified to shared
#     testcases = [
#         test_case(0x20, 0xDEAD, 0b1111), # Core 0: Write (Modified)
#         test_case(0x00, 0x0000, 0b0000), # Core 1: Idle

#         test_case(0x20, 0x0000, 0b0000)  # Core 1: Read (Forces C0: M -> S)
#     ]

#     # create CPU
#     to_the_moon: CPU = CPU(2, testcases)

#     # await the async method
#     x = await to_the_moon.start_sim()

async def contention(): # two core fight for same memory addr
    testcases = [

        test_case(30, 0x0000, 0b0000),  # Core 0: Read
        test_case(30, 0x0000, 0b0000),  # Core 1: Read

        test_case(30, 40, 0b1111), # Core 0: Write
        test_case(30, 30, 0b1111), # Core 1: Write

        test_case(30, 20, 0b1111), # Core 0: Write
        test_case(30, 10, 0b1111)  # Core 1: Write

    ]

    # create CPU
    to_the_moon: CPU = CPU(2, testcases)

    # await the async method
    x = await to_the_moon.start_sim()
    
    # print("hello are u here")
    # print(to_the_moon.dma(0x20))
    to_the_moon.dma(0x20)


async def simple(): # write and then read
    testcases: List[test_case] = []
    for i in range(10):
        testcases.append(test_case(i, i, 0b0000))
    for i in range(10):
        testcases.append(test_case(i, i, 0b1111))

    # create CPU
    to_the_moon: CPU = CPU(2, testcases)

    # await the async method
    x = await to_the_moon.start_sim()

async def main():
    await simple()
    # await contention()
    # await dirty_snooping()
    # await write_after_read_test()

# run the async main
asyncio.run(main())


