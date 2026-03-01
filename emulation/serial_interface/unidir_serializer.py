from collections import deque

class tserializer:
    def __init__(self, num_pins : int, data_size : int):
        self.num_pins  : int = num_pins
        self.data_size : int = data_size

        # serial interface
        self.en_o     : bool = 0
        self.serial_o : list = [0] * num_pins

        # data interface
        self.data_i  : deque = deque([], maxlen=data_size)
        self.valid_i : bool = 0
        self.ready_o : bool = 1

        # internal 
        self.state  : str = "idle"
        self.data_r : deque = None

    def _send_packet(self):
        output = []
        # fill unpopulated bits of the message with zeros (sent first)
        for _ in range(len(self.data_r) % self.num_pins):
            self.data_r.append(0)
        # build packet
        for _ in range(self.num_pins):
                output.append(self.data_r.pop())

        assert len(self.serial_o) == len(output), "Serializer: serial packet length doesn't match serial pin count"

        # put current packet on the serial interface
        self.serial_o = output

    def print_config(self):
        print("T Serializer Config:")
        print(f"  serial_pins : {self.num_pins}")
        print(f"  data_size  : {self.data_size}")

    def print_state(self):

        print(f"\n--- T Serializer State: {self.state.upper()} ---")
        
        print("T Serial Interface:")
        print(f"  en_o={self.en_o}, serial_o={self.serial_o}")

        print("T Data Interface:")
        print(f"  ready_o={self.ready_o}, valid_i={self.valid_i}")
        print(f"  data_i={self.data_i}")

        print("Internal Registers:")
        print(f"  tdata_r     : {list(self.data_r)}")
        print("-" * 30)

    def cycle_clock(self, data_i : int, valid_i : bool):
        assert len(data_i) <= self.data_size, "tserializer: data input length exceeds max data size"

        self.data_i = data_i
        self.valid_i = valid_i

        if self.state == "idle":
            self.ready_o = 1
            self.data_r = self.data_i.copy()
            self.en_o = self.valid_i
            if valid_i:
                self.state = "send"
                self._send_packet()
                self.ready_o = 0
        elif self.state == "send":
            if self.data_r:
                  self._send_packet()
            else:
                self.state = "idle"
                self.en_o = 0
                self.ready_o = 1



class rserializer:
    def __init__(self, num_pins : int, data_size : int):
        self.num_pins  : int = num_pins
        self.data_size : int = data_size

        # serial interface
        self.en_i     : bool = 0
        self.serial_i : list = [0] * num_pins

        # data interface
        self.data_o  : deque =  deque([], maxlen=data_size)
        self.valid_o : bool = 0
        self.ready_i : bool = 0

        # internal reg
        self.state = "idle"

    def _receive_packet(self):
        self.data_o.extendleft(self.serial_i)
        assert len(self.data_o) <= self.data_size, "rserializer: rdata overflow"

    def print_config(self):
        print("R Serializer Config:")
        print(f"  serial_pins : {self.num_pins}")
        print(f"  data_size  : {self.data_size}")

    def print_state(self):

        print(f"\n--- R Serializer State: {self.state.upper()} ---")
        
        print("R Serial Interface:")
        print(f"  en_i={self.en_i}, serial_i={self.serial_i}")

        print("R Data Interface:")
        print(f"  ready_i={self.ready_i}, valid_o={self.valid_o}")
        print(f"  data_o={self.data_o}")
        print("-" * 30)
    
    def cycle_clock(self, en_i : bool, serial_i : list, ready_i : bool):
        self.en_i = en_i
        self.serial_i = serial_i
        self.ready_i = ready_i

        # if valid data is ready to be received transition to invalid
        if ready_i == 1 and self.valid_o == 1:
            self.valid_o = 0

        if self.state == "idle":
            if self.en_i == 1:
                self.state = "receive"
                self.valid_o = 0
                self._receive_packet()
        if self.state == "receive":
            if self.en_i == 1:
                self._receive_packet()
            else:
                self.state = "idle"
                self.valid_o = 1
