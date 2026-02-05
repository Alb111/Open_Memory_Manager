class axi2serial:
    def __init__(self):
        self.mem_ready = 0
        self.mem_rdata = 0
        self.data_o = 0

        self.state="idle"
        self.tmsg_reg = None
        self.tmsg_cnt = 0
        # self.driving = False
    
    def update(self, mem_valid, mem_instr, mem_addr, mem_wdata, mem_wstrb, data_i, en_i):
        if (self.state == "idle") & (mem_valid == 1):
            self.state = "sending"
            self.tmsg_reg = self._msg_gen(mem_addr, mem_wdata, mem_wstrb)
            self.tmsg_cnt = self._msg_length(self._get_metadata(mem_wstrb))

        elif self.state == "sending":
            self.data_o = int(next(self.tmsg_reg))
            self.tmsg_cnt -= 1
            if self.tmsg_cnt == 0:
                self.state = "waiting"

        elif self.state == "waiting":
            if en_i == 1: self.state = "receiveing"

        # if self.state == "receiving":

    
    def print_state(self):
        print(str(self) + " State:")
        print("mem_ready: " + str(bin(self.mem_ready)))
        print("mem_rdata: " + str(bin(self.mem_rdata)))
        print("data_o: " + str(bin(self.data_o)))
        print()
        print("State: " + self.state)
        print("tmsg_cnt: " + str(self.tmsg_cnt))

    def _msg_gen(self, mem_addr, mem_wdata, mem_wstrb):
        metadata = self._get_metadata(mem_wstrb)
        msg_length = self._msg_length(metadata)
        if metadata == 0b00:
            return self._serial_gen(msg_length, self._append_bits([2, 32], [metadata, mem_addr]))
        
        if metadata == 0b01:
            return self._serial_gen(msg_length, self._append_bits([2, 32, 32, 4], [metadata, mem_addr, mem_wdata, mem_wstrb]))
    
        else: raise ValueError("Message metadata not in range")

    def _serial_gen(self, length: int, data: str):
        for i in range(length):
            yield int(data[i],2)
        
    def _get_metadata(self, mem_wstrb):
        if mem_wstrb == 0:
            return 0b00
        else:
            return 0b01

    def _msg_length(self, metadata):
        if metadata == 0b00:
            return 34
        
        if metadata == 0b01:
            return 70
        
    def _append_bits(self, len_arr, bstr_arr):
        bstr_o = ""

        for bstr, length in zip(bstr_arr, len_arr):
            bstr_o += f"{bstr:0{length}b}"
        
        return bstr_o

###############
# simple test #
############### 

# meta = get_metadata(None, 0b1010)
# msg = append_bits(None, [2, 32, 32, 4], [meta, 0b10000000000000000000000000000001, 0b10000000000000000000000000000001, 0b1100])
# length = msg_length(None, meta)
# gen = serial_gen(None, length, msg)
# for i in range(length):
#     print("bit[" + str(i) + "]: " + str(next(gen)))

axi2serial = axi2serial()
mem_valid = 1
mem_instr = 0
mem_addr = 0b11000000000000000000000000000001
mem_wdata = 0b10000000000000000000000000000011
mem_wstrb = 0b0000
data_i = 0
en_i = 0
axi2serial.update(mem_valid, mem_instr, mem_addr, mem_wdata, mem_wstrb, data_i, en_i)
axi2serial.print_state()
counter = 1
while axi2serial.tmsg_cnt != 0:
    axi2serial.update(mem_valid, mem_instr, mem_addr, mem_wdata, mem_wstrb, data_i, en_i)
    print(f"[{counter}]: {axi2serial.data_o}")
    counter += 1
axi2serial.print_state()