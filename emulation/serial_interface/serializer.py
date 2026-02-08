class serializer:

    def __init__(self, tdata_size: int, rdata_size: int):
        
        # serial interface
        # io pin
        self.serial_io = 0
        # output
        self.en_o = 0
        # inputs
        self.en_i = 0

        # data interface
        # recieving
        self.rvalid_o = 0
        self.rready_i = 0
        self.rdata_o = [0] * rdata_size
        # transmitting
        self.tvalid_i = 0
        self.tready_o = 0
        self.tdata_i = None
        self.tmsg_len = 0
        

        # internal state
        self.tdata_r = [0] * tdata_size
        self.rdata_r = 0
        self.tmsg_cnt = 0
        self.rmsg_cnt = 0
    
        self.state = "idle"
        # idle, send, receive

    def print_state(self):
        # helper to convert list of [1,0,1] to "101"
        tdata_str = "".join(map(str, self.tdata_r))
        rdata_str = "".join(map(str, self.rdata_o)) 
        tdata_i_str = "".join(map(str, self.tdata_i))

        print(f"\n--- Model State: {self.state.upper()} ---")
        
        print("Serial Interface:")
        print(f"  IO Pin : serial_io={self.serial_io}")
        print(f"  Outputs: en_o={self.en_o}")
        print(f"  Inputs : en_i={self.en_i}")

        print("Data Interface:")
        print(f"  Receiving    : rready_i={self.rready_i}, rvalid_o={self.rvalid_o}")
        print(f"                 rdata_o={rdata_str}")
        print(f"  Transmitting : tready_o={self.tready_o}, tvalid_i={self.tvalid_i}")
        print(f"                 tdata_i={tdata_i_str}")
        print(f"  Config Input : tmsg_len={self.tmsg_len}")

        print("Internal Registers:")
        print(f"  tmsg_cnt: {self.tmsg_cnt:3d} | rmsg_cnt: {self.rmsg_cnt:3d}")
        print(f"  tdata_r : [{tdata_str}]")
        print(f"  rdata_r : {bin(self.rdata_r)}")
        print("-" * 30)

    def cycle_clock(self, en_i: bool, serial_i: bool, tvalid_i: bool, rready_i: bool, tdata_i: list, tmsg_len: int):

        assert len(tdata_i) == len(self.tdata_r), "Transmission data does not match shift register length"

        # set inputs
        self.en_i = en_i
        self.serial_io |= serial_i
        self.tvalid_i = tvalid_i
        self.rready_i = rready_i
        self.tdata_i = tdata_i
        self.tmsg_len = tmsg_len

        if self.state == "idle":
            self.tdata_r = self.tdata_i
            self.en_o = 0
            self.tmsg_cnt = tmsg_len
            self.serial_io = 0
            self.rdata_r = 0
            self.tready_o = 1

            if self.rready_i == 1:
                self.rvalid_o = 0

            if (self.tvalid_i == 1) and (self.en_i == 0):
                self.state = "send"
                self.en_o = 1
                self.tready_o = 0
            elif (en_i == 1):
                self.state = "receive"
                self.tready_o = 0

        elif self.state == "send":
            if self.tmsg_cnt == 0:
                self.state = "idle"
                self.en_o = 0
            else:
                self.serial_io = self.tdata_r[self.tmsg_cnt-1]
                self.tmsg_cnt -= 1

        elif self.state == "receive":
            if en_i == 0:
                self.rmsg_cnt = 0
                self.rvalid_o = 1
                while self.rdata_r != 0:
                    self.rdata_o[self.rmsg_cnt] = self.rdata_r & 1
                    self.rdata_r >>= 1
                    self.rmsg_cnt += 1
                self.state = "idle"
                    
            self.serial_io = serial_i
            self.rdata_r = (self.rdata_r << 1) | self.serial_io
            

