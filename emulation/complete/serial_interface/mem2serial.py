from serializer import serializer

class mem2serial:
   def __init__(self):
      # axi interface
      # outputs
      self.mem_valid = 0
      self.mem_instr = 0
      self.mem_addr = 0
      self.mem_wdata = 0
      self.mem_wstrb = 0

      # inputs
      self.mem_ready = 0
      self.mem_rdata = 0

      # serial interface
      self.serial_io = 0
      self.en_i = 0
      self.en_o = 0

      # serializer
      self.serializer = serializer(32, 70)

   def cycle_clock(self, mem_ready: bool, mem_rdata: int, serial_i: bool, en_i: bool):
      assert 0 <= mem_rdata <= 0xFFFFFFFF, "mem_rdata must be 32 bits"

      self.mem_valid = self.serializer.rvalid_o
      self.mem_addr = self._constructbstr(self.serializer.rdata_o, 2, 34)
      self. mem_wdata = self._constructbstr(self.serializer.rdata_o, 34, 66)
      self.mem_wstrb = self._constructbstr(self.serializer.rdata_o, 66, 70)
      self.serial_io = serial_i | self.serializer.serial_io
      self.en_i = en_i
      self.en_o = self.serializer.en_o

      read = (self.mem_wstrb == 0)
      msg_length = 0
      meta_data = 0
      if read:
         msg_length = 32
      else: 
         msg_length = 1
      data = self._bin2list([32], [mem_rdata])
      
      self.serializer.cycle_clock(en_i, serial_i, mem_ready, 1, data, msg_length)

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


