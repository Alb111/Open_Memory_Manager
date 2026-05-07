`timescale 1ns/1ps
`default_nettype none

module cache_controller #(
    parameter int NUM_SETS = 64,
    parameter int WORDS_PER_LINE = 4,
    parameter bit USE_BEHAVIORAL_WAYS = 1'b1,
    parameter logic [7:0] CPU_ID = 8'h01
) (
    input  logic        clk_i,
    input  logic        rst_ni,

    input  logic        mem_valid_i,
    input  logic        mem_instr_i,
    input  logic [31:0] mem_addr_i,
    input  logic [31:0] mem_wdata_i,
    input  logic [3:0]  mem_wstrb_i,
    output logic        mem_ready_o,
    output logic [31:0] mem_rdata_o,

    input  logic        snoop_valid_i,
    input  logic [3:0]  snoop_meta_i,
    input  logic [31:0] snoop_addr_i,
    input  logic [31:0] snoop_wdata_i,

    output logic        out_valid_o,
    output logic [3:0]  out_meta_o,
    output logic [31:0] out_addr_o,
    output logic [31:0] out_wdata_o,
    input  logic        out_ready_i,
    output logic [7:0]  cpu_id_o
);
    localparam int WAYS = 2;
    localparam int TAG_BITS = 24;

    localparam [1:0] MSI_I = 2'b00;
    localparam [1:0] MSI_S = 2'b01;
    localparam [1:0] MSI_M = 2'b10;

    localparam [3:0] META_NULL        = 4'b0000;
    localparam [3:0] META_BUS_RD      = 4'b0001;
    localparam [3:0] META_BUS_RDX     = 4'b0010;
    localparam [3:0] META_BUS_UPGR    = 4'b0011;
    localparam [3:0] META_EVICT_CLEAN = 4'b0100;
    localparam [3:0] META_EVICT_DIRTY = 4'b1000;
    localparam [3:0] META_SNOOP_RD    = 4'b1001;
    localparam [3:0] META_SNOOP_RDX   = 4'b1010;
    localparam [3:0] META_SNOOP_UPGR  = 4'b1011;
    localparam [3:0] META_WHOAMI      = 4'b1110;
    localparam [3:0] META_RESETDONE   = 4'b1111;

    typedef enum logic [3:0] {
        ST_IDLE,
        ST_WB,
        ST_FILL,
        ST_CPU_RESP,
        ST_SNOOP_WB,
        ST_SNOOP_SEND,
        ST_SEND_META
    } state_t;

    state_t state_q, state_d;

    logic [TAG_BITS-1:0] tag_q [0:WAYS-1][0:NUM_SETS-1];
    logic                valid_q [0:WAYS-1][0:NUM_SETS-1];
    logic [1:0]          msi_q [0:WAYS-1][0:NUM_SETS-1];
    logic                lru_q [0:NUM_SETS-1];

    logic [5:0] set_idx;
    logic [1:0] word_off;
    logic [TAG_BITS-1:0] tag_in;
    assign set_idx  = mem_addr_i[9:4];
    assign word_off = mem_addr_i[3:2];
    assign tag_in   = mem_addr_i[31:8];

    logic hit0, hit1;
    logic [31:0] way_rdata [0:1];
    logic rd_en_way [0:1];
    logic wr_en_way [0:1];
    logic [5:0]  wr_set_way [0:1];
    logic [1:0]  wr_word_way [0:1];
    logic [31:0] wr_data_way [0:1];
    logic [3:0]  wr_strb_way [0:1];

    assign hit0 = valid_q[0][set_idx] && (tag_q[0][set_idx] == tag_in) && (msi_q[0][set_idx] != MSI_I);
    assign hit1 = valid_q[1][set_idx] && (tag_q[1][set_idx] == tag_in) && (msi_q[1][set_idx] != MSI_I);

    cache #(.NUM_SETS(NUM_SETS), .WORDS_PER_LINE(WORDS_PER_LINE), .USE_BEHAVIORAL(USE_BEHAVIORAL_WAYS)) u_way0 (
        .clk_i(clk_i), .rst_ni(rst_ni),
        .rd_en_i(rd_en_way[0]), .rd_set_i(set_idx), .rd_word_i(word_off), .rd_data_o(way_rdata[0]),
        .wr_en_i(wr_en_way[0]), .wr_set_i(wr_set_way[0]), .wr_word_i(wr_word_way[0]), .wr_data_i(wr_data_way[0]), .wr_strb_i(wr_strb_way[0])
    );
    cache #(.NUM_SETS(NUM_SETS), .WORDS_PER_LINE(WORDS_PER_LINE), .USE_BEHAVIORAL(USE_BEHAVIORAL_WAYS)) u_way1 (
        .clk_i(clk_i), .rst_ni(rst_ni),
        .rd_en_i(rd_en_way[1]), .rd_set_i(set_idx), .rd_word_i(word_off), .rd_data_o(way_rdata[1]),
        .wr_en_i(wr_en_way[1]), .wr_set_i(wr_set_way[1]), .wr_word_i(wr_word_way[1]), .wr_data_i(wr_data_way[1]), .wr_strb_i(wr_strb_way[1])
    );

    mem_ctrl_512x32 u_backing_mem (
        .clk_i(clk_i), .rst_ni(rst_ni),
        .mem_valid_i(backing_valid_q), .mem_instr_i(1'b0), .mem_addr_i(backing_addr_q), .mem_wdata_i(backing_wdata_q), .mem_wstrb_i(backing_wstrb_q),
        .mem_rdata_o(backing_rdata), .mem_ready_o(backing_ready)
    );

    logic        backing_valid_q;
    logic [31:0] backing_addr_q;
    logic [31:0] backing_wdata_q;
    logic [3:0]  backing_wstrb_q;
    logic [31:0] backing_rdata;
    logic        backing_ready;

    logic [5:0]  miss_set_q;
    logic [TAG_BITS-1:0] miss_tag_q;
    logic [1:0]  miss_word_q;
    logic        miss_is_write_q;
    logic [31:0] miss_wdata_q;
    logic [3:0]  miss_wstrb_q;
    logic        victim_way_q;
    logic [1:0]  phase_word_q;
    logic [31:0] linebuf_q [0:3];
    logic [31:0] snoop_saved_addr_q;
    logic [3:0]  pending_meta_q;
    logic [31:0] pending_addr_q;
    logic [31:0] pending_wdata_q;

    integer s, w;

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            state_q <= ST_IDLE;
            mem_ready_o <= 1'b0;
            mem_rdata_o <= '0;
            out_valid_o <= 1'b0;
            out_meta_o  <= META_NULL;
            out_addr_o  <= '0;
            out_wdata_o <= '0;
            cpu_id_o    <= CPU_ID;
            backing_valid_q <= 1'b0;
            backing_addr_q  <= '0;
            backing_wdata_q <= '0;
            backing_wstrb_q <= '0;
            miss_set_q <= '0; miss_tag_q <= '0; miss_word_q <= '0; miss_is_write_q <= 1'b0; miss_wdata_q <= '0; miss_wstrb_q <= '0;
            victim_way_q <= 1'b0; phase_word_q <= '0; pending_meta_q <= META_NULL; pending_addr_q <= '0; pending_wdata_q <= '0; snoop_saved_addr_q <= '0;
            for (s = 0; s < NUM_SETS; s++) begin
                lru_q[s] <= 1'b0;
                for (w = 0; w < WAYS; w++) begin
                    valid_q[w][s] <= 1'b0;
                    msi_q[w][s] <= MSI_I;
                    tag_q[w][s] <= '0;
                end
            end
            for (s = 0; s < WORDS_PER_LINE; s++) linebuf_q[s] <= '0;
        end else begin
            mem_ready_o <= 1'b0;
            out_valid_o <= 1'b0;
            backing_valid_q <= 1'b0;
            for (s = 0; s < WORDS_PER_LINE; s++) begin end

            case (state_q)
                ST_IDLE: begin
                    cpu_id_o <= CPU_ID;
                    if (snoop_valid_i) begin
                        snoop_saved_addr_q <= snoop_addr_i;
                        if (snoop_meta_i == META_SNOOP_RD || snoop_meta_i == META_SNOOP_RDX || snoop_meta_i == META_SNOOP_UPGR) begin
                            miss_set_q  <= snoop_addr_i[9:4];
                            miss_word_q <= snoop_addr_i[3:2];
                            miss_tag_q  <= snoop_addr_i[31:8];
                            if (valid_q[0][snoop_addr_i[9:4]] && tag_q[0][snoop_addr_i[9:4]] == snoop_addr_i[31:8] && msi_q[0][snoop_addr_i[9:4]] != MSI_I) begin
                                victim_way_q <= 1'b0;
                                if (msi_q[0][snoop_addr_i[9:4]] == MSI_M) begin
                                    phase_word_q <= 2'd0;
                                    if (snoop_meta_i == META_SNOOP_UPGR) begin
                                        valid_q[0][snoop_addr_i[9:4]] <= 1'b0;
                                        msi_q[0][snoop_addr_i[9:4]] <= MSI_I;
                                    end else begin
                                        state_q <= ST_SNOOP_WB;
                                    end
                                end else begin
                                    valid_q[0][snoop_addr_i[9:4]] <= 1'b0;
                                    msi_q[0][snoop_addr_i[9:4]] <= MSI_I;
                                end
                            end else if (valid_q[1][snoop_addr_i[9:4]] && tag_q[1][snoop_addr_i[9:4]] == snoop_addr_i[31:8] && msi_q[1][snoop_addr_i[9:4]] != MSI_I) begin
                                victim_way_q <= 1'b1;
                                if (msi_q[1][snoop_addr_i[9:4]] == MSI_M) begin
                                    phase_word_q <= 2'd0;
                                    if (snoop_meta_i == META_SNOOP_UPGR) begin
                                        valid_q[1][snoop_addr_i[9:4]] <= 1'b0;
                                        msi_q[1][snoop_addr_i[9:4]] <= MSI_I;
                                    end else begin
                                        state_q <= ST_SNOOP_WB;
                                    end
                                end else begin
                                    valid_q[1][snoop_addr_i[9:4]] <= 1'b0;
                                    msi_q[1][snoop_addr_i[9:4]] <= MSI_I;
                                end
                            end
                        end else if (snoop_meta_i == META_WHOAMI) begin
                            out_valid_o <= 1'b1;
                            out_meta_o  <= META_WHOAMI;
                            out_wdata_o <= {24'd0, CPU_ID};
                            out_addr_o  <= 32'd0;
                        end else if (snoop_meta_i == META_RESETDONE) begin
                            out_valid_o <= 1'b1;
                            out_meta_o  <= META_RESETDONE;
                            out_addr_o  <= 32'd0;
                            out_wdata_o <= 32'd0;
                        end
                    end

                    if (mem_valid_i) begin
                        miss_set_q      <= set_idx;
                        miss_tag_q      <= tag_in;
                        miss_word_q     <= word_off;
                        miss_is_write_q <= |mem_wstrb_i;
                        miss_wdata_q    <= mem_wdata_i;
                        miss_wstrb_q    <= mem_wstrb_i;

                        if (hit0 || hit1) begin
                            if (!(|mem_wstrb_i)) begin
                                mem_rdata_o <= hit0 ? way_rdata[0] : way_rdata[1];
                                mem_ready_o <= 1'b1;
                                lru_q[set_idx] <= hit0 ? 1'b1 : 1'b0;
                            end else begin
                                if (hit0) begin
                                    if (msi_q[0][set_idx] == MSI_S) begin
                                        out_valid_o <= 1'b1;
                                        out_meta_o  <= META_BUS_UPGR;
                                        out_addr_o  <= {tag_in, set_idx, 4'b0};
                                        if (out_ready_i) msi_q[0][set_idx] <= MSI_M;
                                    end
                                    if (out_ready_i || msi_q[0][set_idx] == MSI_M) begin
                                        lru_q[set_idx] <= 1'b1;
                                        mem_ready_o <= 1'b1;
                                    end
                                end else begin
                                    if (msi_q[1][set_idx] == MSI_S) begin
                                        out_valid_o <= 1'b1;
                                        out_meta_o  <= META_BUS_UPGR;
                                        out_addr_o  <= {tag_in, set_idx, 4'b0};
                                        if (out_ready_i) msi_q[1][set_idx] <= MSI_M;
                                    end
                                    if (out_ready_i || msi_q[1][set_idx] == MSI_M) begin
                                        lru_q[set_idx] <= 1'b0;
                                        mem_ready_o <= 1'b1;
                                    end
                                end
                            end
                        end else begin
                            victim_way_q <= lru_q[set_idx];
                            phase_word_q <= 2'd0;
                            if (valid_q[lru_q[set_idx]][set_idx] && msi_q[lru_q[set_idx]][set_idx] == MSI_M) begin
                                state_q <= ST_WB;
                            end else begin
                                if (valid_q[lru_q[set_idx]][set_idx] && msi_q[lru_q[set_idx]][set_idx] == MSI_S) begin
                                    pending_meta_q <= META_EVICT_CLEAN;
                                    pending_addr_q <= {tag_q[lru_q[set_idx]][set_idx], set_idx, 4'b0};
                                    state_q <= ST_SEND_META;
                                end else begin
                                    out_valid_o <= 1'b1;
                                    out_meta_o  <= miss_is_write_q ? META_BUS_RDX : META_BUS_RD;
                                    out_addr_o  <= {tag_in, set_idx, 4'b0};
                                    state_q <= ST_FILL;
                                end
                            end
                        end
                    end
                end

                ST_SEND_META: begin
                    out_valid_o <= 1'b1;
                    out_meta_o  <= pending_meta_q;
                    out_addr_o  <= pending_addr_q;
                    out_wdata_o <= pending_wdata_q;
                    if (out_ready_i) begin
                        out_valid_o <= 1'b1;
                        out_meta_o  <= miss_is_write_q ? META_BUS_RDX : META_BUS_RD;
                        out_addr_o  <= {miss_tag_q, miss_set_q, 4'b0};
                        state_q <= ST_FILL;
                    end
                end

                ST_WB: begin
                    out_valid_o <= 1'b1;
                    out_meta_o  <= META_EVICT_DIRTY;
                    out_addr_o  <= {tag_q[victim_way_q][miss_set_q], miss_set_q, phase_word_q, 2'b00};
                    out_wdata_o <= victim_way_q ? way_rdata[1] : way_rdata[0];
                    backing_valid_q <= 1'b1;
                    backing_addr_q  <= {tag_q[victim_way_q][miss_set_q], miss_set_q, phase_word_q, 2'b00};
                    backing_wdata_q <= victim_way_q ? way_rdata[1] : way_rdata[0];
                    backing_wstrb_q <= 4'hF;
                    if (phase_word_q == 2'd3) begin
                        pending_meta_q <= META_NULL;
                        state_q <= ST_FILL;
                        valid_q[victim_way_q][miss_set_q] <= 1'b0;
                        msi_q[victim_way_q][miss_set_q] <= MSI_I;
                        phase_word_q <= 2'd0;
                    end else begin
                        phase_word_q <= phase_word_q + 2'd1;
                    end
                end

                ST_FILL: begin
                    backing_valid_q <= 1'b1;
                    backing_addr_q  <= {miss_tag_q, miss_set_q, phase_word_q, 2'b00};
                    backing_wdata_q <= 32'd0;
                    backing_wstrb_q <= 4'h0;
                    linebuf_q[phase_word_q] <= backing_rdata;
                    if (phase_word_q == 2'd3) begin
                        valid_q[victim_way_q][miss_set_q] <= 1'b1;
                        tag_q[victim_way_q][miss_set_q]   <= miss_tag_q;
                        msi_q[victim_way_q][miss_set_q]   <= miss_is_write_q ? MSI_M : MSI_S;
                        lru_q[miss_set_q] <= ~victim_way_q;
                        state_q <= ST_CPU_RESP;
                        phase_word_q <= 2'd0;
                    end else begin
                        phase_word_q <= phase_word_q + 2'd1;
                    end
                end

                ST_CPU_RESP: begin
                    mem_ready_o <= 1'b1;
                    mem_rdata_o <= linebuf_q[miss_word_q];
                    state_q <= ST_IDLE;
                end

                ST_SNOOP_WB: begin
                    out_valid_o <= 1'b1;
                    out_meta_o  <= (snoop_meta_i == META_SNOOP_RD) ? META_SNOOP_RD : META_SNOOP_RDX;
                    out_addr_o  <= {tag_q[victim_way_q][miss_set_q], miss_set_q, phase_word_q, 2'b00};
                    out_wdata_o <= victim_way_q ? way_rdata[1] : way_rdata[0];
                    backing_valid_q <= 1'b1;
                    backing_addr_q  <= {tag_q[victim_way_q][miss_set_q], miss_set_q, phase_word_q, 2'b00};
                    backing_wdata_q <= victim_way_q ? way_rdata[1] : way_rdata[0];
                    backing_wstrb_q <= 4'hF;
                    if (phase_word_q == 2'd3) begin
                        if (snoop_meta_i == META_SNOOP_RD) begin
                            msi_q[victim_way_q][miss_set_q] <= MSI_S;
                        end else begin
                            valid_q[victim_way_q][miss_set_q] <= 1'b0;
                            msi_q[victim_way_q][miss_set_q] <= MSI_I;
                        end
                        state_q <= ST_IDLE;
                        phase_word_q <= 2'd0;
                    end else begin
                        phase_word_q <= phase_word_q + 2'd1;
                    end
                end

                default: state_q <= ST_IDLE;
            endcase
        end
    end

    always_comb begin
        rd_en_way[0] = 1'b1;
        rd_en_way[1] = 1'b1;
        wr_en_way[0] = 1'b0;
        wr_en_way[1] = 1'b0;
        wr_set_way[0] = miss_set_q; wr_set_way[1] = miss_set_q;
        wr_word_way[0] = miss_word_q; wr_word_way[1] = miss_word_q;
        wr_data_way[0] = miss_wdata_q; wr_data_way[1] = miss_wdata_q;
        wr_strb_way[0] = miss_wstrb_q; wr_strb_way[1] = miss_wstrb_q;

        if (state_q == ST_FILL) begin
            wr_en_way[victim_way_q] = 1'b1;
            wr_set_way[victim_way_q] = miss_set_q;
            wr_word_way[victim_way_q] = phase_word_q;
            wr_data_way[victim_way_q] = backing_rdata;
            wr_strb_way[victim_way_q] = 4'hF;
        end else if (state_q == ST_IDLE && mem_valid_i && (hit0 || hit1) && (|mem_wstrb_i) && ((hit0 && (msi_q[0][set_idx]==MSI_M || out_ready_i)) || (hit1 && (msi_q[1][set_idx]==MSI_M || out_ready_i)))) begin
            wr_en_way[hit1] = hit1;
            wr_en_way[hit0] = hit0;
            wr_set_way[0] = set_idx; wr_set_way[1] = set_idx;
            wr_word_way[0] = word_off; wr_word_way[1] = word_off;
            wr_data_way[0] = mem_wdata_i; wr_data_way[1] = mem_wdata_i;
            wr_strb_way[0] = mem_wstrb_i; wr_strb_way[1] = mem_wstrb_i;
        end else if (state_q == ST_CPU_RESP && miss_is_write_q) begin
            wr_en_way[victim_way_q] = 1'b1;
            wr_set_way[victim_way_q] = miss_set_q;
            wr_word_way[victim_way_q] = miss_word_q;
            wr_data_way[victim_way_q] = miss_wdata_q;
            wr_strb_way[victim_way_q] = miss_wstrb_q;
        end
    end
endmodule

`default_nettype wire

