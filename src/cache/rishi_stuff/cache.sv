`timescale 1ns/1ps
`default_nettype none

module cache #(
    parameter int NUM_SETS = 64,
    parameter int WORDS_PER_LINE = 4,
    parameter bit USE_BEHAVIORAL = 1'b1
) (
    input  logic        clk_i,
    input  logic        rst_ni,
    input  logic        rd_en_i,
    input  logic [5:0]  rd_set_i,
    input  logic [1:0]  rd_word_i,
    output logic [31:0] rd_data_o,
    input  logic        wr_en_i,
    input  logic [5:0]  wr_set_i,
    input  logic [1:0]  wr_word_i,
    input  logic [31:0] wr_data_i,
    input  logic [3:0]  wr_strb_i
);
    localparam int DEPTH_WORDS = NUM_SETS * WORDS_PER_LINE;

    function automatic int unsigned idx(input logic [5:0] set_i, input logic [1:0] word_i);
        idx = (set_i * WORDS_PER_LINE) + word_i;
    endfunction

    generate
        if (USE_BEHAVIORAL) begin : g_beh
            logic [31:0] mem [0:DEPTH_WORDS-1];
            integer k;
            always_ff @(posedge clk_i or negedge rst_ni) begin
                if (!rst_ni) begin
                    for (k = 0; k < DEPTH_WORDS; k++) mem[k] <= '0;
                end else if (wr_en_i) begin
                    if (wr_strb_i[0]) mem[idx(wr_set_i, wr_word_i)][7:0]   <= wr_data_i[7:0];
                    if (wr_strb_i[1]) mem[idx(wr_set_i, wr_word_i)][15:8]  <= wr_data_i[15:8];
                    if (wr_strb_i[2]) mem[idx(wr_set_i, wr_word_i)][23:16] <= wr_data_i[23:16];
                    if (wr_strb_i[3]) mem[idx(wr_set_i, wr_word_i)][31:24] <= wr_data_i[31:24];
                end
            end
            always_comb begin
                rd_data_o = 32'h0;
                if (rd_en_i) rd_data_o = mem[idx(rd_set_i, rd_word_i)];
            end
        end else begin : g_macro
            logic [31:0] mem_rdata;
            logic        mem_ready;
            logic [31:0] byte_addr_r;
            logic        mem_valid_r;
            logic [31:0] mem_wdata_r;
            logic [3:0]  mem_wstrb_r;

            always_ff @(posedge clk_i or negedge rst_ni) begin
                if (!rst_ni) begin
                    byte_addr_r <= '0;
                    mem_valid_r <= 1'b0;
                    mem_wdata_r <= '0;
                    mem_wstrb_r <= '0;
                end else begin
                    mem_valid_r <= rd_en_i | wr_en_i;
                    byte_addr_r <= ({23'd0, (wr_en_i ? wr_set_i : rd_set_i), (wr_en_i ? wr_word_i : rd_word_i), 2'b00});
                    mem_wdata_r <= wr_data_i;
                    mem_wstrb_r <= wr_en_i ? wr_strb_i : 4'h0;
                end
            end

            mem_ctrl_512x32 u_mem (
                .clk_i(clk_i),
                .rst_ni(rst_ni),
                .mem_valid_i(mem_valid_r),
                .mem_instr_i(1'b0),
                .mem_addr_i(byte_addr_r),
                .mem_wdata_i(mem_wdata_r),
                .mem_wstrb_i(mem_wstrb_r),
                .mem_rdata_o(mem_rdata),
                .mem_ready_o(mem_ready)
            );
            always_comb rd_data_o = mem_rdata;
        end
    endgenerate
endmodule

`default_nettype wire

