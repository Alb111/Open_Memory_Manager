module directory_mem
(
  input  wire        clk_i,
  input  wire        rst_ni,

  // input interface
  input  wire         valid_i,
  output wire         ready_o,
  input  wire [31:0]  addr_i,
  input  wire [3:0]   wstrb_i, // if 1111 write if 0 read

  // wstrb
  input  wire [31:0]  w_data_i,        // data to write to addr

  input  wire [1:0]   w_state_i,       // state to write
  input  wire [1:0]   w_sharers_i,     // tag to write
  input  wire [0:0]   w_owner_i,       // tag to write
  input  wire [0:0]   w_valid_data_i,  // tag to write

  // output interface
  output  wire [31:0]  r_data_o,   // data from this addr

  output  wire [31:0]  r_state_o,  // state to write
  output  wire [1:0]   r_tag_o,    // tag to write
  output  wire [1:0]   r_owner_o,  // tag to write
  output  wire [1:0]   r_valid_data_o,  // tag to write
  input  wire          ready_i
);
