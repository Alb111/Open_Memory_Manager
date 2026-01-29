// uses axi slave interface
// input and outputs was based of the defenition provided in the following:
// https://www.realdigital.org/doc/a9fee931f7a172423e1ba73f66ca4081
// https://github.com/arhamhashmi01/Axi4-lite/blob/main/Axi4-lite-verilator/axi4_lite_slave.sv
//
// TODO: caputure addr in flip flop 
// TODO: use states to drive control singals for the sram, do no work on states where bit mask is 0 
// TODO: write testbench

`default_nettype none

module mem_ctrl #(
  parameter int WIDTH_P = 32,
  parameter int ADDR_WIDTH = 9
)(

  `ifdef USE_POWER_PINS
    inout  wire VDD,
    inout  wire VSS,
  `endif

  input wire                 ACLK,
  input wire                 ARESETN,

  ////Read Address Channel wire
  input wire [WIDTH_P-1:0]   S_ARADDR,
  input wire                 S_ARVALID,

  //Read Data Channel wire
  input wire                 S_RREADY,

  //Write Address Channel wire
  input wire [WIDTH_P-1:0]   S_AWADDR,
  input wire                 S_AWVALID,

  //Write Data  Channel wire
  input wire [WIDTH_P-1:0]   S_WDATA,
  input wire [3:0]           S_WSTRB,
  input wire                 S_WVALID,

  //Write Response Channel  wireS
  input wire                 S_BREADY,

  //Read Address Channel OUTPUTS
  output                     S_ARREADY,

  //Read Data Channel OUTPUTS
  output     [WIDTH_P-1:0]   S_RDATA,
  output     [1:0]           S_RRESP,
  output                     S_RVALID,

  //Write Address Channel OUTPUTS
  output                     S_AWREADY,
  output                     S_WREADY,

  //Write Response Channel OUTPUTS
  output          [1:0]      S_BRESP,
  output                     S_BVALID

);

  localparam int ExtraBits = ADDR_WIDTH - 9;
  localparam int SramCount = 1 << ExtraBits;


  logic [7:0] sram_data_in;
  logic [7:0] sram_data_out;
  logic [ExtraBits + 8:0] sram_addr;
  logic write_en;

  generate
    for (i = 0; i < SramCount; i = i + 1) begin: gen_srams
      gf180mcu_fd_ip_sram__sram512x8m8wm1 sram_0 (

          `ifdef USE_POWER_PINS
            .VDD  (VDD),
            .VSS  (VSS),
          `endif

          .CLK  (ACLK), // clock
          .CEN  (sram_addr[9 + ExtraBits:9] != i[ExtraBits:0]), // mem enable (active low)
          .GWEN (write_en), // write enable: 0 == write, 1 == read (active low)
          .WEN  (8'b0), // write bitbask (active low)
          .A    (sram_addr[8:0]),   // address
          .D    (sram_data_in),   // data input bus
          .Q    (sram_data_out) // data output bus
      );
    end
  endgenerate


  typedef enum logic [2 : 0] {IDLE,
                              WRITE_CHANNEL_1, WRITE_CHANNEL_2, WRITE_CHANNEL_3, WRITE_CHANNEL_4, 
                              WRESP__CHANNEL,
                              RADDR_CHANNEL1, RADDR_CHANNEL2, RADDR_CHANNEL3, RADDR_CHANNEL4,
                              RDATA__CHANNEL} state_type;

  state_type state_q , state_d;

  always_ff @(posedge ACLK) begin
      if (!ARESETN) begin
          state_q <= IDLE;
      end
      else begin
          state_q <= state_d;
      end
  end

  // read address handshake
  assign S_ARREADY = (state_q == RADDR_CHANNEL) ? 1 : 0; // master init rd address, so slave says its ready  

  // read data handshake
  assign S_RVALID = (state_q == RDATA__CHANNEL_4) ? 1 : 0; // read valid
  assign S_RDATA  = (state_q == RDATA__CHANNEL_4) ? register[addr] : 0; // read data
  assign S_RRESP  = (state_q == RDATA__CHANNEL_4) ? 2'b00:0; // read err code

  // write address handshake
  assign S_AWREADY = (state_q == WRITE_CHANNEL_1) ? 1 : 0; // master init wr address, so slave says its ready  

  // write data handsake
  assign S_WREADY = (state_q == WRITE_CHANNEL_4) ? 1 : 0; 
  // assign write_addr = S_AWVALID && S_AWREADY;
  // assign write_data = S_WREADY &&S_WVALID;

  // tell master if write was sucessfull
  assign S_BVALID = (state_q == WRESP__CHANNEL) ? 1 : 0;
  assign S_BRESP  = (state_q == WRESP__CHANNEL )? 0:0;


  always_comb begin
    case (state)
          IDLE : begin
              if (S_AWVALID) begin
                  next_state = WRITE_CHANNEL_1;
              end 
              else if (S_ARVALID) begin
                  next_state = RADDR_CHANNEL;
              end 
              else begin
                  next_state = IDLE;
              end
          end
          RADDR_CHANNEL   : if (S_ARVALID && S_ARREADY ) next_state = RDATA__CHANNEL;
          RDATA__CHANNEL  : if (S_RVALID  && S_RREADY  ) next_state = IDLE;
          WRITE_CHANNEL_1 : if (S_WVALID) next_state = WRITE_CHANNEL_2; // TODO: make sure to capture address in flipflop here 
          WRITE_CHANNEL_2 : if (S_WVALID) next_state = WRITE_CHANNEL_3;
          WRITE_CHANNEL_3 : if (S_WVALID) next_state = WRITE_CHANNEL_4;
          WRITE_CHANNEL_4 : next_state = WRESP__CHANNEL;
          WRESP__CHANNEL  : if (S_BVALID  && S_BREADY  ) next_state = IDLE;
          default : next_state = IDLE;
      endcase
  end


  

endmodule

