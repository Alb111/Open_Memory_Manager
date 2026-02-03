from memorypool import MemoryPool

class MemCtrl:
    def __init__(self):
        self.mem = MemoryPool()

    def write_full(self, addr: int, data: int, byte_enable: int = 0b1111):
        if not (0 <= data <= 0xFFFFFFFF):
            raise ValueError("Error: data must be 32 bits")

        for i in range(4):
            # check if byte lane enabled
            if (byte_enable >> i) & 1:
                # little endian byte extraction
                byte = (data >> (8 * i)) & 0xFF
                self.mem.write(addr + i, bytes([byte]))

    def read_full(self, addr: int) -> int:
        value = 0
        for i in range(4):
            byte = self.mem.read(addr + i, 1)[0]
            value |= byte << (8 * i)
        return value

    def write_half(self, addr: int, data: int):
        if not (0 <= data <= 0xFFFF):
            raise ValueError("Error: data must be 16 bits")

        for i in range(2):
            byte = (data >> (8 * i)) & 0xFF
            self.mem.write(addr + i, bytes([byte]))

    def read_half(self, addr: int) -> int:
        value = 0
        for i in range(2):
            byte = self.mem.read(addr + i, 1)[0]
            value |= byte << (8 * i)
        return value
