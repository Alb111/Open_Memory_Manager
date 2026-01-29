// uses axi slave interface
// input and outputs was based of the defenition provided in the following:
// https://www.realdigital.org/doc/a9fee931f7a172423e1ba73f66ca4081
// https://github.com/arhamhashmi01/Axi4-lite/blob/main/Axi4-lite-verilator/axi4_lite_slave.sv
 
`default_nettype none

module mem_ctrl #(
  parameter WIDTH_P = 32
)(

  `ifdef USE_POWER_PINS
    inout  wire VDD,
    inout  wire VSS,
  `endif

  input wire                           ACLK,
  input wire                           ARESETN,

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

endmodule

