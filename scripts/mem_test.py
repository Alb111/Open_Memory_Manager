from mem_ctrl import MemCtrl

mc = MemCtrl()

mc.write_full(0x00, 0xDEADBEEF)
mc.write_full(0x01, 0xC0FFEEFF)
mc.write_full(0x03, 0xCAFECAFE)
mc.write_full(0x06, 0xABCDEFEF)
mc.write_full(0x08, 0xACDCABBA)

print(hex(mc.read_full(0x00)))
print(hex(mc.read_full(0x01)))
print(hex(mc.read_full(0x02)))
print(hex(mc.read_full(0x03)))
print(hex(mc.read_full(0x04)))
print(hex(mc.read_full(0x05)))
print(hex(mc.read_full(0x06)))
print(hex(mc.read_full(0x07)))
print(hex(mc.read_full(0x08)))
print(hex(mc.read_full(0x09)))
print(hex(mc.read_full(0x0A)))
print(hex(mc.read_full(0x0B)))



# 00 EF
# 01 FF
# 02 EE
# 03 FE
# 04 CA
# 05 FE
# 06 EF
# 07 EF
# 08 BA
# 09 AB
# 0A DC
# 0B AC