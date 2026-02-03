# von nuemann memory
class MemoryPool:
# default 64 bytes of memory with starting addr of 0x1000
    def __init__(self, size: int = 64, base_addr: int = 0x1000):
        if size <= 0:
            print("cannot have negative memory")
            return

        self.BASE_ADDR = base_addr
        self.SIZE = size
        self.mem = {}        

    def write(self, addr: int, data: bytes):
        for i, b in enumerate(data):
            a = addr + i
            if not self._valid(a):
                raise ValueError("Out of bounds: Write error")
            self.mem[a] = b

    def read(self, addr: int, size: int) -> bytes:
        data = []
        for i in range(size):
            a = addr + i
            if not self._valid(a):
                raise ValueError("Out of bounds: Read error")
            data.append(self.mem.get(a,0))
        return bytes(data)

    def _valid(self, addr: int) -> bool:
        return self.BASE_ADDR <= addr < self.BASE_ADDR + self.SIZE
#checks scope of memory default 0x1000 -> 0x103F
