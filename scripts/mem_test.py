from mem_ctrl import MemCtrl

mc = MemCtrl()

mc.write_inst(0x00, 0xDEADBEEF)
mc.write_inst(0x01, 0xC0FFEEFF)
mc.write_inst(0x03, 0xCAFECAFE)
mc.write_inst(0x06, 0xABCDEFEF)
mc.write_inst(0x08, 0xACDCABBA)

print(hex(mc.read_inst(0x00)))
print(hex(mc.read_inst(0x01)))
print(hex(mc.read_inst(0x02)))
print(hex(mc.read_inst(0x03)))
print(hex(mc.read_inst(0x04)))
print(hex(mc.read_inst(0x05)))
print(hex(mc.read_inst(0x06)))
print(hex(mc.read_inst(0x07)))
print(hex(mc.read_inst(0x08)))
