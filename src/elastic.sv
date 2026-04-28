module elastic
  #(parameter [31:0] width_p = 8,
    parameter [0:0] datapath_gate_p = 0,
    parameter [0:0] datapath_reset_p = 0
  )
  (
   input [0:0] clk_i
  ,input [0:0] reset_i

  ,input [width_p - 1:0] data_i
  ,input [0:0] valid_i
  ,output [0:0] ready_o 

  ,output [0:0] valid_o 
  ,output logic [width_p - 1:0] data_o 
  ,input [0:0] ready_i
  );

  logic full_l;
  //ready if not full or if ready
  assign ready_o = ~full_l | ready_i;
  //valid data if full
  assign valid_o = full_l;

  always_ff@(posedge clk_i) begin
    if (reset_i) begin
      full_l <= 1'b0;
    end else begin
      case ({(valid_i & ready_o), (valid_o & ready_i)})
        2'b10:full_l <=1'b1;
        2'b01: full_l <=1'b0;
        default: full_l <= full_l;
      endcase
    end
  end


  always_ff@(posedge clk_i) begin
    if(datapath_reset_p & reset_i) begin
      data_o <='0;
    end else begin
     if (datapath_gate_p) begin
        if(valid_i & ready_o) begin
          data_o <=data_i;
        end
     end else begin
        if (ready_o) begin
          data_o <= data_i;
        end
      end
    end
  end

endmodule
