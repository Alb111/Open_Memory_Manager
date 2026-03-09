`timescale 1ns/1ps

module wrr_arbiter #(
    parameter NUM_REQ  = 2,   // fixed to 2
    parameter WEIGHT_W = 3
)(
    input  logic clk_i,
    input  logic rst_ni,

    input  logic [NUM_REQ-1:0] req_i,      // req[1:0]
    input  logic [2*WEIGHT_W-1:0] weights_i,

    output logic [NUM_REQ-1:0] grant_o,
    output logic [NUM_REQ-1:0] req_o
);

localparam PTR_MASK = NUM_REQ-1;

logic [WEIGHT_W-1:0] weight0;
logic [WEIGHT_W-1:0] weight1;

assign weight0 = weights_i[WEIGHT_W-1:0];
assign weight1 = weights_i[2*WEIGHT_W-1:WEIGHT_W];

logic [$clog2(NUM_REQ)-1:0] curr_ptr;
logic [$clog2(NUM_REQ)-1:0] next_ptr;

logic [WEIGHT_W-1:0] credit_cnt;
logic [WEIGHT_W-1:0] next_credit_cnt;

logic [NUM_REQ-1:0] next_grant;


always_comb begin

    next_ptr        = curr_ptr;
    next_credit_cnt = credit_cnt;
    next_grant      = '0;

    if (req_i[curr_ptr]) begin

        next_grant[curr_ptr] = 1'b1;

        if (credit_cnt > 1) begin
            next_credit_cnt = credit_cnt - 1;
        end
        else begin
            next_ptr = (curr_ptr + 1) & PTR_MASK;

            if (next_ptr == 0)
                next_credit_cnt = weight0;
            else
                next_credit_cnt = weight1;
        end

    end
    else begin
        next_ptr = (curr_ptr + 1) & PTR_MASK;

        if (next_ptr == 0)
            next_credit_cnt = weight0;
        else
            next_credit_cnt = weight1;
    end

end

always_ff @(posedge clk_i) begin

    if (!rst_ni) begin
        curr_ptr   <= 0;
        credit_cnt <= weight0;
    end
    else begin
        curr_ptr   <= next_ptr;
        credit_cnt <= next_credit_cnt;
    end

end

assign grant_o = !rst_ni ? '0 : next_grant;
assign req_o   = req_i;

endmodule
