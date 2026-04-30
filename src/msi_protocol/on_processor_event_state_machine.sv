`timescale 1ns/1ps
`default_nettype none

module on_processor_event_state_machine
(
  // input interface
  input  logic [1:0]   current_state_i,
  input  logic [3:0]   wstrb_i,

  // output interface     
  output logic [1:0] next_state_o,
  output logic [2:0] issue_cmd_o,
  output logic [0:0] issue_cmd_valid_o
);

  // types
  typedef enum logic [1:0] {
    INVALID  = 2'b00, 
    SHARED   = 2'b01,  
    MODIFIED = 2'b10
  } msi_state;

  typedef enum logic [0:0] {
    WRITE = 1'b0, 
    READ  = 1'b1  
  } processor_event;

  typedef enum logic [2:0] {
    BUS_RD      = 3'd1,        
    BUS_RDX     = 3'd2,       
    BUS_UPGR    = 3'd3,      
    EVICT_CLEAN = 3'd4,   
    EVICT_DIRTY = 3'd5,   
    NONE        = 3'd6   
  } bus_transaction;

  
  // state handling
  msi_state state_q, state_d;
  assign state_q = msi_state'(current_state_i);
  // assign state_q = current_state_i;
  assign next_state_o = state_d;

  // event handling
  processor_event proc_event;
  assign proc_event = processor_event'(wstrb_i == 4'd0);
  // assign proc_event = (wstrb_i == 4'd0) ? READ : WRITE;

  // bus_transactions handling
  bus_transaction cmd_to_directory;
  assign issue_cmd_o = cmd_to_directory; 
  logic valid_cmd;
  assign issue_cmd_valid_o = valid_cmd; 

  always_comb begin
    state_d = state_q;
    valid_cmd = 1'b0;
    cmd_to_directory = NONE;
  
    case(state_q)
      INVALID: begin
        // if(event == processor_event::READ) begin
        if(proc_event == READ) begin
          state_d = SHARED;
          valid_cmd = 1'b1;
          cmd_to_directory = BUS_RD;
        end 
        else begin
          state_d = MODIFIED;
          valid_cmd = 1'b1;
          cmd_to_directory = BUS_RDX;
        end
      end
      SHARED: begin
        // if(event == processor_event::READ) begin
        if(proc_event == READ) begin
          state_d = SHARED;
          valid_cmd = 1'b0;
          cmd_to_directory = NONE;
        end 
        else begin
          state_d = MODIFIED;
          valid_cmd = 1'b1;
          cmd_to_directory = BUS_UPGR;
        end
      end
      MODIFIED: begin
        state_d = MODIFIED;
        valid_cmd = 1'b0;
        cmd_to_directory = NONE;
      end
      default: begin
        state_d = INVALID;
        valid_cmd = 1'b0;
        cmd_to_directory = NONE;
      end
    endcase
  end

endmodule
