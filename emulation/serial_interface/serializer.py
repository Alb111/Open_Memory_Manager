from collections import deque

class serializer:

    def __init__(self, num_pins: int, init_priority : bool, tdata_size: int, rdata_size: int):
        
        # serial interface
        self.serial_io : list = [0] * num_pins
        self.req_o     : bool = 0
        self.req_i     : bool = 0

        # data interface
        # recieving
        self.rready_i : bool = 0
        self.rvalid_o : bool = 0
        self.rdata_o  : deque = deque([], maxlen=rdata_size)
        # transmitting
        self.tvalid_i : bool = 0
        self.tready_o : bool = 1
        self.tdata_i  : deque = None
        

        # internal state
        self.num_pins = num_pins
        self.tdata_size = tdata_size
        self.rdata_size = rdata_size
        self.tdata_r  : deque = deque([], maxlen=tdata_size)
        self.state    : str  = "idle"
        self.priority : bool = init_priority
        self.driving  : bool = 0
        # idle, send, receive

    def print_config(self):
        print("Serializer Config:")
        print(f"  serial_pins : {self.num_pins}")
        print(f"  tdata_size  : {self.tdata_size}")
        print(f"  rdata_size  : {self.rdata_size}")

    def print_state(self):

        print(f"\n--- Serializer State: {self.state.upper()} ---")
        
        print("Serial Interface:")
        print(f"  req_o={self.req_o}, req_i={self.req_i}, serial_io={self.serial_io}")

        print("Data Interface:")
        print(f"  Receiving    : rready_i={self.rready_i}, rvalid_o={self.rvalid_o}")
        print(f"                 rdata_o={list(self.rdata_o)}")
        print(f"  Transmitting : tready_o={self.tready_o}, tvalid_i={self.tvalid_i}")
        print(f"                 tdata_i={self.tdata_i}")

        print("Internal Registers:")
        print(f"  tdata_r     : {list(self.tdata_r)}")
        print(f"  priority    : {self.priority}")
        print(f"  driving     : {self.driving}")
        print("-" * 30)

    def _send_serial_packet(self):
        output = []
        for i in range(self.num_pins):
            if self.tdata_r:
                output.append(self.tdata_r.pop())
            else:
                output.append(0)

        assert len(self.serial_io) == len(output), "Serializer: serial packet length doesn't match serial pin count"

        self.serial_io = output

    def _receive_serial_packet(self):
        self.rdata_o.extendleft(self.serial_io)
        assert len(self.rdata_o) <= self.rdata_size, "Serializer: rdata overflow"


    def cycle_clock(self, req_i: bool, serial_i: bool, rready_i : bool, tvalid_i: bool, tdata_i: deque):
       
        assert tdata_i.maxlen == self.tdata_size, "Serializer: tdata_i size and tdata_size do not match"
        assert len(serial_i) == self.num_pins

        # set state (before clock edge)
        self.req_i = req_i
        self.serial_io = serial_i
        self.rready_i = rready_i
        self.tvalid_i = tvalid_i
        self.tdata_i = tdata_i

        # if data already taken invalidate handshake
        if rready_i:
            self.rvalid_o = 0

        if self.state == "idle":
            
            # before clock edge
            self.req_o = tvalid_i
            self.tdata_r = tdata_i.copy()
            self.driving = 0

            ## on clock edge ##
            # move to send
            if tvalid_i & ((not req_i) | self.priority):
                self.priority = 0
                self.driving = 1
                self.tready_o = 0
                self.state = "send"
                self._send_serial_packet()

            # move to receive
            if req_i & ((not tvalid_i) | (not self.priority)):
                self.rdata_r = deque([], maxlen=self.rdata_size)
                self.priority = 1
                self.tready_o = 0
                self.state = "receive"

        elif self.state == "send":
            if self.tdata_r:
                self._send_serial_packet()
            else:
                # done sending
                self.state = "idle"
                self.driving = 0
                self.tready_o = 1
                self.req_o = 0

        elif self.state == "receive":
            if req_i:
                self._receive_serial_packet()
            else:
                # done receiving
                self.state = "idle"
                self.rvalid_o = 1
                self.tready_o = 1