from core import CPU
from memory import MemoryController

# testing
x: MemoryController = MemoryController()
y: CPU = CPU(0, x.axi_handler)

for i in range(100):
    y.write(i,i,0b1111)

for i in range(100):
    print(y.read(i))

            
        
        
        
        

            

    



























