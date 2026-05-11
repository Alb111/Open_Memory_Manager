module cache_controller
(

  // Proccessor to Cache
  input  logic [0:0] mem_valid,
  input  logic [0:0] mem_instr,
  input  logic [31:0] mem_addr,
  input  logic [31:0] mem_wdata,
  input  logic [3:0]  mem_wstrb,
  output logic [0:0] mem_ready,
  output logic [31:0] mem_rdata, 

  // Cache to Directory
  output logic                cache_valid_o, // valid data out
  output logic [31:0]         cache_addr_o,  // addr of flush 
  output logic [31:0]         cache_data_o,  // data for flush
  output logic [8:0]          cache_cmd_o,   // cache cmd to dir
  input  logic                 cache_ready_i, // dir req accepted

  // Directory back to Cache
  input  logic                bus_valid_i,  // dir resp done    
  input  logic [31:0]         bus_data_i,   // found data
  input  logic [2:0]          bus_dircmd_i, // next state
  output logic                bus_ready_o,  // dir resp accepted

  // Snoop Req ports
  input  logic                 snoop_valid_i,  // directory wants snoop
  input  logic [31:0]          snoop_addr_i,   // snoop addr
  input  logic [2:0]           snoop_dircmd_i, // state to update
  output logic                snoop_ready_o,  // snoop done
)
