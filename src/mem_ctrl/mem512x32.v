`default_nettype none
module mem_ctrl_512x32 (
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
	input wire clk_i;
	input wire rst_ni;
	input wire [0:0] mem_valid_i;
	input wire [0:0] mem_instr_i;
	input wire [31:0] mem_addr_i;
	input wire [31:0] mem_wdata_i;
	input wire [3:0] mem_wstrb_i;
	output wire [31:0] mem_rdata_o;
	output wire [0:0] mem_ready_o;
	wire sram_enable_n;
	wire [3:0] sram_write_en_n;
	wire [7:0] sram_write_bit_mask_n;
	wire [8:0] sram_addr;
	wire [31:0] data_to_write;
	wire [31:0] data_read;
	assign sram_enable_n = !mem_valid_i;
	assign sram_write_en_n = mem_wstrb_i;
	assign sram_write_bit_mask_n = 8'b00000000;
	assign sram_addr = mem_addr_i[8:0];
	assign data_to_write = mem_wdata_i;
	gf180mcu_fd_ip_sram__sram512x8m8wm1 sram0(
		.CLK(clk_i),
		.CEN(sram_enable_n),
		.GWEN(~sram_write_en_n[0]),
		.WEN(sram_write_bit_mask_n),
		.A(sram_addr),
		.D(data_to_write[7:0]),
		.Q(data_read[7:0]),
		.VDD(),
		.VSS()
	);
	gf180mcu_fd_ip_sram__sram512x8m8wm1 sram1(
		.CLK(clk_i),
		.CEN(sram_enable_n),
		.GWEN(~sram_write_en_n[1]),
		.WEN(sram_write_bit_mask_n),
		.A(sram_addr),
		.D(data_to_write[15:8]),
		.Q(data_read[15:8]),
		.VDD(),
		.VSS()
	);
	gf180mcu_fd_ip_sram__sram512x8m8wm1 sram2(
		.CLK(clk_i),
		.CEN(sram_enable_n),
		.GWEN(~sram_write_en_n[2]),
		.WEN(sram_write_bit_mask_n),
		.A(sram_addr),
		.D(data_to_write[23:16]),
		.Q(data_read[23:16]),
		.VDD(),
		.VSS()
	);
	gf180mcu_fd_ip_sram__sram512x8m8wm1 sram3(
		.CLK(clk_i),
		.CEN(sram_enable_n),
		.GWEN(~sram_write_en_n[3]),
		.WEN(sram_write_bit_mask_n),
		.A(sram_addr),
		.D(data_to_write[31:24]),
		.Q(data_read[31:24]),
		.VDD(),
		.VSS()
	);
	assign mem_rdata_o = data_read;
	assign mem_ready_o = 1'b1;
endmodule
`default_nettype wire
