`default_nettype none
module mem_ctrl_2048x32 (
	clk_i,
	rst_ni,
	mem_valid_i,
	mem_instr_i,
	mem_addr_i,
	mem_wdata_i,
	mem_wstrb_i,
	mem_rdata_o,
	mem_ready_o
);
	reg _sv2v_0;
	input wire clk_i;
	input wire rst_ni;
	input wire [0:0] mem_valid_i;
	input wire [0:0] mem_instr_i;
	input wire [31:0] mem_addr_i;
	input wire [31:0] mem_wdata_i;
	input wire [3:0] mem_wstrb_i;
	output wire [31:0] mem_rdata_o;
	output wire [0:0] mem_ready_o;
	wire [31:0] mem_rdata_o_0;
	wire [31:0] mem_rdata_o_1;
	wire [31:0] mem_rdata_o_2;
	wire [31:0] mem_rdata_o_3;
	reg [31:0] mem_rdata_o_logic;
	wire [0:0] mem_ready_o_0;
	wire [0:0] mem_ready_o_1;
	wire [0:0] mem_ready_o_2;
	wire [0:0] mem_ready_o_3;
	reg [0:0] mem_ready_o_logic;
	reg [0:0] mem_valid_i_0;
	reg [0:0] mem_valid_i_1;
	reg [0:0] mem_valid_i_2;
	reg [0:0] mem_valid_i_3;
	always @(*) begin
		if (_sv2v_0)
			;
		mem_valid_i_0 = 1'b0;
		mem_valid_i_1 = 1'b0;
		mem_valid_i_2 = 1'b0;
		mem_valid_i_3 = 1'b0;
		mem_rdata_o_logic = 32'd0;
		mem_ready_o_logic = 1'b0;
		case (mem_addr_i[10:9])
			2'b00: begin
				mem_rdata_o_logic = mem_rdata_o_0;
				mem_ready_o_logic = mem_ready_o_0;
				mem_valid_i_0 = mem_valid_i;
			end
			2'b01: begin
				mem_rdata_o_logic = mem_rdata_o_1;
				mem_ready_o_logic = mem_ready_o_1;
				mem_valid_i_1 = mem_valid_i;
			end
			2'b10: begin
				mem_rdata_o_logic = mem_rdata_o_2;
				mem_ready_o_logic = mem_ready_o_2;
				mem_valid_i_2 = mem_valid_i;
			end
			2'b11: begin
				mem_rdata_o_logic = mem_rdata_o_3;
				mem_ready_o_logic = mem_ready_o_3;
				mem_valid_i_3 = mem_valid_i;
			end
		endcase
	end
	mem_ctrl_512x32 memblock0(
		.clk_i(clk_i),
		.rst_ni(rst_ni),
		.mem_valid_i(mem_valid_i_0),
		.mem_instr_i(mem_instr_i),
		.mem_addr_i(mem_addr_i),
		.mem_wdata_i(mem_wdata_i),
		.mem_wstrb_i(mem_wstrb_i),
		.mem_rdata_o(mem_rdata_o_0),
		.mem_ready_o(mem_ready_o_0)
	);
	mem_ctrl_512x32 memblock1(
		.clk_i(clk_i),
		.rst_ni(rst_ni),
		.mem_valid_i(mem_valid_i_1),
		.mem_instr_i(mem_instr_i),
		.mem_addr_i(mem_addr_i),
		.mem_wdata_i(mem_wdata_i),
		.mem_wstrb_i(mem_wstrb_i),
		.mem_rdata_o(mem_rdata_o_1),
		.mem_ready_o(mem_ready_o_1)
	);
	mem_ctrl_512x32 memblock2(
		.clk_i(clk_i),
		.rst_ni(rst_ni),
		.mem_valid_i(mem_valid_i_2),
		.mem_instr_i(mem_instr_i),
		.mem_addr_i(mem_addr_i),
		.mem_wdata_i(mem_wdata_i),
		.mem_wstrb_i(mem_wstrb_i),
		.mem_rdata_o(mem_rdata_o_2),
		.mem_ready_o(mem_ready_o_2)
	);
	mem_ctrl_512x32 memblock3(
		.clk_i(clk_i),
		.rst_ni(rst_ni),
		.mem_valid_i(mem_valid_i_3),
		.mem_instr_i(mem_instr_i),
		.mem_addr_i(mem_addr_i),
		.mem_wdata_i(mem_wdata_i),
		.mem_wstrb_i(mem_wstrb_i),
		.mem_rdata_o(mem_rdata_o_3),
		.mem_ready_o(mem_ready_o_3)
	);
	assign mem_rdata_o = mem_rdata_o_logic;
	assign mem_ready_o = mem_ready_o_logic;
	initial _sv2v_0 = 0;
endmodule
`default_nettype wire
