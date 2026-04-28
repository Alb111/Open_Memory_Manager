// this is genmi gen I just changed some small stuff
`default_nettype none

module reset_gen #(
    parameter integer COUNT_MAX = 255  
)(
    input  wire        clk_i,          // System clock
    input  wire        rst_ni,         // External "cold" reset (active low)
    input  wire        trigger_i,      // Signal to start the count (valid)
    
    output reg         reset_o,        // Active-high reset for internal logic
    output wire        done_o          // High when counting is finished
);

    // Calculate bit width needed for the counter based on parameter
    localparam integer WIDTH = $clog2(COUNT_MAX + 1);

    reg [WIDTH-1:0] count_q;
    reg             active_q;

    // Reset is active as long as we are in the 'active' counting state
    // or if the external hardware reset is held.
    always_comb begin
      reset_o = active_q || !rst_ni;
    end 

    assign done_o = (count_q == COUNT_MAX);

    always @(posedge clk_i) begin
        if (!rst_ni) begin
            count_q  <= 0;
            active_q <= 1'b0;
        end else begin
            if (trigger_i && !active_q && !done_o) begin
                // Start counting when triggered
                active_q <= 1'b1;
            end else if (active_q) begin
                if (count_q < COUNT_MAX) begin
                    count_q <= count_q + 1;
                end else begin
                    // Reach target, drop reset
                    active_q <= 1'b0;
                end
            end
        end
    end

endmodule

`default_nettype wire
