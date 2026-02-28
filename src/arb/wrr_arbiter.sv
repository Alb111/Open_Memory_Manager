/*
WRR Arbiter flow

Cycle   curr_ptr    credit_cnt  grant
1       0           1           0001
2       1           3           0010
3       1           2           0010
4       1           1           0010
5       0           1           0001
6       1           3           0010
*/


module wrr_arbiter #(
    parameter NUM_REQ = 2, // must always be a power of 2
    parameter WEIGHT_W = 3,
    parameter logic [NUM_REQ*WEIGHT_W-1:0] WEIGHTS = {3'd1, 3'd1}
)(
    input logic clk_i,
    input logic rst_i,                     // active high reset
    input logic [NUM_REQ-1:0] req_i,      // req[0], req[1]

    output logic [NUM_REQ-1:0] grant_o,     // one-hot grant
    output logic [NUM_REQ-1:0] req_o        // pass-through of who is requesting to whatever else may need it (kept in for Rishi)
);

    // ENUMS??? (maybe down the line for more readability)

    localparam PTR_MASK = NUM_REQ-1;

// Internal signals

    logic [$clog2(NUM_REQ)-1:0]  curr_ptr;
    logic [$clog2(NUM_REQ)-1:0]  next_ptr;

    logic [WEIGHT_W-1:0] weight_table [NUM_REQ-1:0]; // weights assigned
    logic [WEIGHT_W-1:0] credit_cnt;
    logic [WEIGHT_W-1:0] next_credit_cnt;

    logic [NUM_REQ-1:0]  next_grant; // next reciever



// Assign/Create weights
// creates a weight table for each requester (weight_table[0] and weight_table[0])

    genvar i;
    generate
        for (i = 0; i < NUM_REQ; i++) begin
            assign weight_table[i] = WEIGHTS[(i*WEIGHT_W+WEIGHT_W-1):(i*WEIGHT_W)]; 
        end
    endgenerate



// Next-state logic

    always_comb begin
        next_ptr = curr_ptr;
        next_credit_cnt = credit_cnt;
        next_grant = '0;

        if (req_i[curr_ptr]) begin
            next_grant[curr_ptr] = 1'b1;

            // If more credits remain, stay on same requester
            if (credit_cnt > 1) begin
                next_credit_cnt = credit_cnt - 1;
            end

            // Move to next requester
            else begin    
                next_ptr        = (curr_ptr + 1) & PTR_MASK; //bitwise wrap
                next_credit_cnt = weight_table[next_ptr];
            end

        // Current requester not requesting, rotate immediately
        end else begin
            next_ptr        = (curr_ptr + 1) & PTR_MASK; 
            next_credit_cnt = weight_table[next_ptr];
        end
    end



// Sequential logic

    always_ff @(posedge clk_i) begin
        if (rst_i) begin
            curr_ptr   <= '0;
            credit_cnt <= weight_table[0]; // set to first requester (if set to '0 it will skip first)
        end
        else begin
            curr_ptr   <= next_ptr;
            credit_cnt <= next_credit_cnt;
        end
    end

    assign grant_o = rst_i ? '0 : next_grant; // grant_o combination logic
    assign req_o = req_i; // pass-through


endmodule
