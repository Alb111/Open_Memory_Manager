// SPDX-FileCopyrightText: © 2025 Albert Felix
// SPDX-License-Identifier: Apache-2.0
//
// 8192 x 32-bit main memory: eight 1024-deep banks (mem_ctrl_1024x32),
// selected by mem_addr_i[12:10]. This is the 3.3V/8192-word replacement for
// mem_ctrl_2048x32.
//
// Banks are instantiated with explicit names memblock0..memblock7 (not a
// generate loop) so the physical hierarchy matches the macro placement in
// librelane/macros/macros_3v3.yaml and the PDN list in pdn_3v3_sram.tcl:
//   i_chip_core.i_main_memory.memblockN.sramM
//
// CONTENTS CLEAR: a single broadcast counter (clr_cnt) sweeps 0..1023 and
// writes zero to EVERY bank at the same address on the same cycle, so all eight
// banks clear in parallel. Clear latency is therefore the depth of one bank
// (1024 cycles), not the whole array. This replaces the external
// memory_reset_generator; the clear FSM here is NOT on any scan chain.

`default_nettype none

module mem_ctrl_8192x32
(
	input wire         clk_i,
	input wire         rst_ni,

	input wire [0:0]   mem_valid_i,
	input wire [0:0]   mem_instr_i,

	input wire [31:0]  mem_addr_i,
	input wire [31:0]  mem_wdata_i,
	input wire [3:0]   mem_wstrb_i,

	output wire [31:0] mem_rdata_o,
	output wire [0:0]  mem_ready_o,

	// Contents-clear handshake. clear_start_i high (held) requests a full zero
	// sweep; clear_done_o rises when done and stays high until the next request.
	input wire         clear_start_i,
	output wire        clear_done_o,

	// DFT scan chain for the clear FSM (debug_mode_i selects scan vs functional).
	input wire         debug_mode_i,
	input wire         scan_in_i,
	output wire        scan_out_o

	`ifdef USE_POWER_PINS
	    ,input wire VDD //adding these for librelane
	    ,input wire VSS
 	`endif
);

// ---------------------------------------------------------------------------
// Clear FSM: one 10-bit counter broadcasts a zero write to all eight banks.
// ---------------------------------------------------------------------------
localparam logic [9:0] CLR_LAST = 10'd1023;

logic        clr_state_q, clr_state_d;   // 0 = idle, 1 = clearing
logic [9:0]  clr_cnt_q,   clr_cnt_d;
logic        clr_done_q,  clr_done_d;
logic        start_q;

wire start_pulse = clear_start_i & ~start_q;
wire clearing    = clr_state_q;           // high while sweeping

always_comb begin
	clr_state_d = clr_state_q;
	clr_cnt_d   = clr_cnt_q;
	clr_done_d  = clr_done_q;

	if (!clr_state_q) begin
		// idle
		if (start_pulse) begin
			clr_done_d  = 1'b0;
			clr_cnt_d   = 10'd0;
			clr_state_d = 1'b1;
		end
	end else begin
		// clearing: one word per cycle (banks are always ready)
		if (clr_cnt_q == CLR_LAST) begin
			clr_done_d  = 1'b1;
			clr_state_d = 1'b0;
		end
		clr_cnt_d = clr_cnt_q + 10'd1;
	end
end

// DFT scan chain: concat of the clear-FSM registers. scan_in enters clr_state_q
// (LSB); the MSB (start_q) drives scan_out. debug_mode_i selects scan below.
localparam int CLR_SCAN_N = 13;
wire [CLR_SCAN_N-1:0] scan_state = {start_q, clr_done_q, clr_cnt_q, clr_state_q};
assign scan_out_o = scan_state[CLR_SCAN_N-1];

always_ff @(posedge clk_i) begin
	if (!rst_ni) begin
		clr_state_q <= 1'b0;
		clr_cnt_q   <= 10'd0;
		clr_done_q  <= 1'b0;
		start_q     <= 1'b0;
	end else if (debug_mode_i) begin
		{start_q, clr_done_q, clr_cnt_q, clr_state_q} <= {scan_state[CLR_SCAN_N-2:0], scan_in_i};
	end else begin
		clr_state_q <= clr_state_d;
		clr_cnt_q   <= clr_cnt_d;
		clr_done_q  <= clr_done_d;
		start_q     <= clear_start_i;
	end
end

assign clear_done_o = clr_done_q;

// ---------------------------------------------------------------------------
// Bank drive: functional access, or the broadcast clear sweep.
// ---------------------------------------------------------------------------
// During a clear every bank sees the same counter address + zero write; the
// per-bank valid is forced high. Otherwise the addr[12:10] decode enables one.
wire [31:0] bank_addr  = clearing ? {22'b0, clr_cnt_q} : mem_addr_i;
wire [31:0] bank_wdata = clearing ? 32'b0              : mem_wdata_i;
wire [3:0]  bank_wstrb = clearing ? 4'b1111            : mem_wstrb_i;

// output singals to mux
logic [31:0] mem_rdata_o_0, mem_rdata_o_1, mem_rdata_o_2, mem_rdata_o_3;
logic [31:0] mem_rdata_o_4, mem_rdata_o_5, mem_rdata_o_6, mem_rdata_o_7;
logic [31:0] mem_rdata_o_logic;
logic [0:0]  mem_ready_o_0, mem_ready_o_1, mem_ready_o_2, mem_ready_o_3;
logic [0:0]  mem_ready_o_4, mem_ready_o_5, mem_ready_o_6, mem_ready_o_7;
logic [0:0]  mem_ready_o_logic;

// functional per-bank valid (before the clear override)
logic [0:0]  fv_0, fv_1, fv_2, fv_3, fv_4, fv_5, fv_6, fv_7;

// logic to select which sram bank (eight 1024-deep banks -> addr[12:10])
always_comb begin

	fv_0 = 1'b0; fv_1 = 1'b0; fv_2 = 1'b0; fv_3 = 1'b0;
	fv_4 = 1'b0; fv_5 = 1'b0; fv_6 = 1'b0; fv_7 = 1'b0;
	mem_rdata_o_logic = 32'd0;
	mem_ready_o_logic = 1'b0;

	case (mem_addr_i[12:10])
		3'b000: begin mem_rdata_o_logic = mem_rdata_o_0; mem_ready_o_logic = mem_ready_o_0; fv_0 = mem_valid_i; end
		3'b001: begin mem_rdata_o_logic = mem_rdata_o_1; mem_ready_o_logic = mem_ready_o_1; fv_1 = mem_valid_i; end
		3'b010: begin mem_rdata_o_logic = mem_rdata_o_2; mem_ready_o_logic = mem_ready_o_2; fv_2 = mem_valid_i; end
		3'b011: begin mem_rdata_o_logic = mem_rdata_o_3; mem_ready_o_logic = mem_ready_o_3; fv_3 = mem_valid_i; end
		3'b100: begin mem_rdata_o_logic = mem_rdata_o_4; mem_ready_o_logic = mem_ready_o_4; fv_4 = mem_valid_i; end
		3'b101: begin mem_rdata_o_logic = mem_rdata_o_5; mem_ready_o_logic = mem_ready_o_5; fv_5 = mem_valid_i; end
		3'b110: begin mem_rdata_o_logic = mem_rdata_o_6; mem_ready_o_logic = mem_ready_o_6; fv_6 = mem_valid_i; end
		3'b111: begin mem_rdata_o_logic = mem_rdata_o_7; mem_ready_o_logic = mem_ready_o_7; fv_7 = mem_valid_i; end
		default: begin end  // fully covered; pre-initialized defaults hold
	endcase
end

// clear forces all banks active; otherwise use the decoded functional valid
wire [0:0] bv_0 = clearing ? 1'b1 : fv_0;
wire [0:0] bv_1 = clearing ? 1'b1 : fv_1;
wire [0:0] bv_2 = clearing ? 1'b1 : fv_2;
wire [0:0] bv_3 = clearing ? 1'b1 : fv_3;
wire [0:0] bv_4 = clearing ? 1'b1 : fv_4;
wire [0:0] bv_5 = clearing ? 1'b1 : fv_5;
wire [0:0] bv_6 = clearing ? 1'b1 : fv_6;
wire [0:0] bv_7 = clearing ? 1'b1 : fv_7;

mem_ctrl_1024x32 memblock0 (
	.clk_i(clk_i), .rst_ni(rst_ni),
	.mem_valid_i(bv_0), .mem_instr_i(mem_instr_i),
	.mem_addr_i(bank_addr), .mem_wdata_i(bank_wdata), .mem_wstrb_i(bank_wstrb),
	.mem_rdata_o(mem_rdata_o_0), .mem_ready_o(mem_ready_o_0)
	`ifdef USE_POWER_PINS
     // verilator lint_off ASSIGNIN
     ,.VDD(VDD) ,.VSS(VSS)
     // verilator lint_on ASSIGNIN
     `endif
);

mem_ctrl_1024x32 memblock1 (
	.clk_i(clk_i), .rst_ni(rst_ni),
	.mem_valid_i(bv_1), .mem_instr_i(mem_instr_i),
	.mem_addr_i(bank_addr), .mem_wdata_i(bank_wdata), .mem_wstrb_i(bank_wstrb),
	.mem_rdata_o(mem_rdata_o_1), .mem_ready_o(mem_ready_o_1)
	`ifdef USE_POWER_PINS
     // verilator lint_off ASSIGNIN
     ,.VDD(VDD) ,.VSS(VSS)
     // verilator lint_on ASSIGNIN
     `endif
);

mem_ctrl_1024x32 memblock2 (
	.clk_i(clk_i), .rst_ni(rst_ni),
	.mem_valid_i(bv_2), .mem_instr_i(mem_instr_i),
	.mem_addr_i(bank_addr), .mem_wdata_i(bank_wdata), .mem_wstrb_i(bank_wstrb),
	.mem_rdata_o(mem_rdata_o_2), .mem_ready_o(mem_ready_o_2)
	`ifdef USE_POWER_PINS
     // verilator lint_off ASSIGNIN
     ,.VDD(VDD) ,.VSS(VSS)
     // verilator lint_on ASSIGNIN
     `endif
);

mem_ctrl_1024x32 memblock3 (
	.clk_i(clk_i), .rst_ni(rst_ni),
	.mem_valid_i(bv_3), .mem_instr_i(mem_instr_i),
	.mem_addr_i(bank_addr), .mem_wdata_i(bank_wdata), .mem_wstrb_i(bank_wstrb),
	.mem_rdata_o(mem_rdata_o_3), .mem_ready_o(mem_ready_o_3)
	`ifdef USE_POWER_PINS
     // verilator lint_off ASSIGNIN
     ,.VDD(VDD) ,.VSS(VSS)
     // verilator lint_on ASSIGNIN
     `endif
);

mem_ctrl_1024x32 memblock4 (
	.clk_i(clk_i), .rst_ni(rst_ni),
	.mem_valid_i(bv_4), .mem_instr_i(mem_instr_i),
	.mem_addr_i(bank_addr), .mem_wdata_i(bank_wdata), .mem_wstrb_i(bank_wstrb),
	.mem_rdata_o(mem_rdata_o_4), .mem_ready_o(mem_ready_o_4)
	`ifdef USE_POWER_PINS
     // verilator lint_off ASSIGNIN
     ,.VDD(VDD) ,.VSS(VSS)
     // verilator lint_on ASSIGNIN
     `endif
);

mem_ctrl_1024x32 memblock5 (
	.clk_i(clk_i), .rst_ni(rst_ni),
	.mem_valid_i(bv_5), .mem_instr_i(mem_instr_i),
	.mem_addr_i(bank_addr), .mem_wdata_i(bank_wdata), .mem_wstrb_i(bank_wstrb),
	.mem_rdata_o(mem_rdata_o_5), .mem_ready_o(mem_ready_o_5)
	`ifdef USE_POWER_PINS
     // verilator lint_off ASSIGNIN
     ,.VDD(VDD) ,.VSS(VSS)
     // verilator lint_on ASSIGNIN
     `endif
);

mem_ctrl_1024x32 memblock6 (
	.clk_i(clk_i), .rst_ni(rst_ni),
	.mem_valid_i(bv_6), .mem_instr_i(mem_instr_i),
	.mem_addr_i(bank_addr), .mem_wdata_i(bank_wdata), .mem_wstrb_i(bank_wstrb),
	.mem_rdata_o(mem_rdata_o_6), .mem_ready_o(mem_ready_o_6)
	`ifdef USE_POWER_PINS
     // verilator lint_off ASSIGNIN
     ,.VDD(VDD) ,.VSS(VSS)
     // verilator lint_on ASSIGNIN
     `endif
);

mem_ctrl_1024x32 memblock7 (
	.clk_i(clk_i), .rst_ni(rst_ni),
	.mem_valid_i(bv_7), .mem_instr_i(mem_instr_i),
	.mem_addr_i(bank_addr), .mem_wdata_i(bank_wdata), .mem_wstrb_i(bank_wstrb),
	.mem_rdata_o(mem_rdata_o_7), .mem_ready_o(mem_ready_o_7)
	`ifdef USE_POWER_PINS
     // verilator lint_off ASSIGNIN
     ,.VDD(VDD) ,.VSS(VSS)
     // verilator lint_on ASSIGNIN
     `endif
);

// assign logic to wires
assign mem_rdata_o = mem_rdata_o_logic;
assign mem_ready_o = mem_ready_o_logic;

endmodule
`default_nettype wire
