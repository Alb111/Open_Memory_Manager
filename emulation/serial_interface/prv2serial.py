from serializer import serializer

class prv2serial:
   def __init__(self):
      # axi interface
      # inputs
      self.mem_valid = 0
      self.mem_instr = 0
      self.mem_addr = 0
      self.mem_wdata = 0
      self.mem_wstrb = 0

      # outputs
      self.mem_ready = 0
      self.mem_rdata = 0

      # serial interface
      self.serial_io = 0
      self.en_i = 0
      self.en_o = 0

      # serializer
      self.serializer = serializer(70, 32)

   def cycle_clock(self, mem_valid: bool, mem_instr: bool, mem_addr: int, mem_wdata: int, mem_wstrb: int, serial_i: bool, en_i: bool):
      assert 0 <= mem_addr <= 0xFFFFFFFF, "mem_addr must be 32 bits"
      assert 0 <= mem_wdata <= 0xFFFFFFFF, "mem_wdata must be 32 bits"
      assert 0 <= mem_wstrb <= 0xF, "mem_wstrb must be 4 bits"

      self.mem_valid = mem_valid
      self.mem_instr = mem_instr
      self.mem_addr = mem_addr
      self. mem_wdata = mem_wdata
      self.mem_wstrb = mem_wstrb
      self.serial_io = serial_i | self.serializer.serial_io
      self.en_i = en_i
      self.en_o = self.serializer.en_o

      read = (mem_wstrb == 0)
      msg_length = 0
      meta_data = 0
      if read:
         msg_length = 34
         meta_data = 0
      else: 
         msg_length = 70
         meta_data = 1
      data = self._bin2list([2, 32, 32, 4], [meta_data, mem_addr, mem_wdata, mem_wstrb])
      
      self.serializer.cycle_clock(en_i, serial_i, mem_valid, 1, data, msg_length)

      # outputs
      self.mem_ready = self.serializer.rvalid_o
      self.mem_rdata = self.serializer.rdata_o
      self.en_o = self.serializer.en_o

   # takes list of binstrings and lengths and appends them in an array of 1s ad 0s
   def _bin2list(self, widths: list, binstrings: list) -> list:
      output = []
      for bstr, w in zip(binstrings, widths):
         # extract bits from MSB to LSB for each integer
         bits = [(bstr >> i) & 1 for i in range(w - 1, -1, -1)]
         output.extend(bits)
      return output
   
   # constructs a bin string from a specific start and end in the bus array 
   def _constructbstr(self, bit_list: list, startid: int, end_id) -> int:
      output = 0
      for i in range(startid, end_id, 1):
         output = (output << 1) + bit_list[i]
      return output


