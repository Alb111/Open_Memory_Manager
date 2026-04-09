module housekeeping_top (
	clk_i,
	reset_i,
	spi_sck_o,
	spi_mosi_o,
	spi_miso_i,
	flash_csb_o,
	pass_thru_en_i,
	sram_wr_en_o,
	sram_addr_o,
	sram_data_o,
	cores_en_o,
	boot_done_o
);
	parameter BOOT_SIZE = 32;
	parameter SRAM_BASE_ADDR = 32'h00000000;
	input wire clk_i;
	input wire reset_i;
	output wire spi_sck_o;
	output wire spi_mosi_o;
	input wire spi_miso_i;
	output wire flash_csb_o;
	input wire pass_thru_en_i;
	output wire sram_wr_en_o;
	output wire [31:0] sram_addr_o;
	output wire [31:0] sram_data_o;
	output wire cores_en_o;
	output wire boot_done_o;
	wire spi_start;
	wire spi_done;
	wire spi_busy;
	wire [7:0] spi_data_out;
	wire [7:0] spi_data_in;
	spi_engine spi_master(
		.clk_i(clk_i),
		.reset_i(reset_i || pass_thru_en_i),
		.start_i(spi_start),
		.data_in_i(spi_data_out),
		.data_out_o(spi_data_in),
		.done_o(spi_done),
		.busy_o(spi_busy),
		.spi_sck_o(spi_sck_o),
		.spi_mosi_o(spi_mosi_o),
		.spi_miso_i(spi_miso_i)
	);
	boot_fsm #(
		.BOOT_SIZE(BOOT_SIZE),
		.SRAM_BASE_ADDR(SRAM_BASE_ADDR)
	) boot_controller(
		.clk_i(clk_i),
		.reset_i(reset_i || pass_thru_en_i),
		.spi_start_o(spi_start),
		.spi_out_o(spi_data_out),
		.spi_in_i(spi_data_in),
		.spi_done_i(spi_done),
		.spi_busy_i(spi_busy),
		.flash_csb_o(flash_csb_o),
		.sram_wr_en_o(sram_wr_en_o),
		.sram_addr_o(sram_addr_o),
		.sram_data_o(sram_data_o),
		.cores_en_o(cores_en_o),
		.boot_done_o(boot_done_o)
	);
endmodule
