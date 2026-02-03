from mem_ctrl import MemCtrl

mc = MemCtrl()

mc.write_full(0x1000, 0xDEADBEEF)
mc.write_full(0x1004, 0xC0FFEEFF)
mc.write_full(0x1008, 0xCAFECAFE)
mc.write_full(0x100C, 0xABCDEFEF)
mc.write_half(0x1010, 0xABCD)
mc.write_half(0x1012, 0xABBA)
mc.write_half(0x1014, 0xACDC)

print(hex(mc.read_full(0x1000)))
print(hex(mc.read_full(0x1004)))
print(hex(mc.read_full(0x1008)))
print(hex(mc.read_full(0x100C)))
print(hex(mc.read_half(0x1010)))
print(hex(mc.read_half(0x1012)))
print(hex(mc.read_half(0x1014)))

# 0xdeadbeef
# 0xc0ffeeff
# 0xcafecafe
# 0xabcdefef
# 0xabcd
# 0xabba
# 0xacdc
