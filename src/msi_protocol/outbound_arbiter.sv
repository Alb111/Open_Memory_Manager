`default_nettype none
`timescale 1ns/1ps

module outbound_arbiter (
    input  logic        clk_i,
    input  logic        rst_ni,

    // ---------- Master port 0 ----------
    input  logic        m0_valid_i,
    input  logic [31:0] m0_addr_i,
    input  logic [31:0] m0_data_i,
    input  logic [8:0]  m0_cmd_i,
    output logic        m0_ready_o,   // grant feedback to master 0

    // ---------- Master port 1 ----------
    input  logic        m1_valid_i,
    input  logic [31:0] m1_addr_i,
    input  logic [31:0] m1_data_i,
    input  logic [8:0]  m1_cmd_i,
    output logic        m1_ready_o,   // grant feedback to master 1

    // ---------- Cache slave port ----------
    output logic        cache_valid_o,
    output logic [31:0] cache_addr_o,
    output logic [31:0] cache_data_o,
    output logic [8:0]  cache_cmd_o,
    input  logic        cache_ready_i
);

    typedef enum logic [1:0] {
        IDLE    = 2'b00,  // no active grant, waiting for a request
        GRANT_0 = 2'b01,  // master 0 owns the bus
        GRANT_1 = 2'b10   // master 1 owns the bus
    } arb_state_e;

    
    arb_state_e state_q, state_d;
    logic grant_q, grant_d;

    logic        cache_valid_q, cache_valid_d;
    logic [31:0] cache_addr_q, cache_addr_d;
    logic [31:0] cache_data_q, cache_data_d;
    logic [8:0]  cache_cmd_q, cache_cmd_d;

    // assign flops to output
    assign cache_valid_o  = cache_valid_q;
    assign cache_addr_o = cache_addr_q;
    assign cache_data_o = cache_data_q;
    assign cache_cmd_o = cache_cmd_q;

    always_ff @(posedge clk_i) begin

        if (!rst_ni) begin
            state_q <= IDLE;
            grant_q <= 0;
            cache_valid_q  <= '0;
            cache_addr_q <= '0;
            cache_data_q <= '0;
            cache_cmd_q <= '0;
        end
        else begin
            state_q <= state_d;
            grant_q <= grant_d;
            cache_valid_q  <= cache_valid_d;
            cache_addr_q <= cache_addr_d;
            cache_data_q <= cache_data_d;
            cache_cmd_q <= cache_cmd_d;
        end
    end



    always_comb begin

        state_d = state_q;
        grant_d = grant_q;
        cache_valid_d  = cache_valid_q;
        cache_addr_d = cache_addr_q;
        cache_data_d = cache_data_q;
        cache_cmd_d = cache_cmd_q;

        case (state_q)

            IDLE: begin

                // contention chose one based on grant 
                if (m0_valid_i && m1_valid_i) begin
                    if (grant_q == 0) begin
                        state_d = GRANT_0;
                        cache_valid_d  = m0_valid_i;
                        cache_addr_d = m0_addr_i;
                        cache_data_d = m0_data_i;
                        cache_cmd_d = m0_cmd_i;
                        grant_d = !grant_q;
                    end
                    else begin
                        state_d = GRANT_1;
                        cache_valid_d  = m1_valid_i;
                        cache_addr_d = m1_addr_i;
                        cache_data_d = m1_data_i;
                        cache_cmd_d = m1_cmd_i;
                        grant_d = !grant_q;
                    end
                end

                else if (m0_valid_i && !m1_valid_i) begin
                    state_d = GRANT_0;
                end

                else if (!m0_valid_i && m1_valid_i) begin
                    state_d = GRANT_1;
                end
                else begin
                    // do nothing
                end
            end    

            GRANT_0: begin
                if (cache_ready_i) begin
                    state_d = IDLE;
                end
            end 

            GRANT_1: begin
                if (cache_ready_i) begin
                    state_d = IDLE;
                end
            end
            
          default: state_d = IDLE;
        endcase
    end

endmodule
