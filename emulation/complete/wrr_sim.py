# multi core 
from core import Core
from typing import List

class CPU:

    
    def __init__(self, size_in: int = 2) -> None:
        self.size: int = size_in 
        self.cores: List[Core] = []

        for i in range(size_in):
            self.cores.append(Core(i,))

    
            

        


    

    




        
