class Memory:
    def __init__(self):
        self.memory = {}

    def byte_wr(self, addr: int, data: int):
        #data fits in 8 bits (0 to 255)
        if not(0<= data <= 0xFF):
            raise ValueError("Error: data must be 8 bits")
        self.memory[addr] = data

    def byte_rd(self, addr: int) -> int:
        return self.memory.get(addr, 0)