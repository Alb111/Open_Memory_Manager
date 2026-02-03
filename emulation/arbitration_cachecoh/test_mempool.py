from memorypool import MemoryPool

# memory1 = MemoryPool(4096)
# 
# memory1.write(0x1000, b"test")
# print(memory1.read(0x1000, 4))
# 
# memory1.write(0x1200, b"hello world!")
# print(memory1.read(0x1200, 12))
# 
# memory1.write(0x1FFF, b"A")
# print(memory1.read(0x1FFF, 1))
# 
# memory1.write(0x2000, b"A")
# print(memory1.read(0x2000, 1))
# 
# memory1.write(0x0FFF, b"A")
# print(memory1.read(0x0FFF, 1))
# 
# 
# memory2 = MemoryPool(8192)
# memory2.write(0x1000, b"test")
# print(memory2.read(0x1000, 4))
# 
# memory2.write(0x2FFF, b"A")
# print(memory2.read(0x2FFF, 1))



mem = MemoryPool(64)
mem.write(0x1000, b"this is an sram")
print(mem.read(0x1000, 15))

mem.write(0x1020, b"    testing this later.")
print(str(mem.read(0x1000, 64), 'utf-8'))
# 0x1000 -> 0x103F (this would be one sram block for gf180)
