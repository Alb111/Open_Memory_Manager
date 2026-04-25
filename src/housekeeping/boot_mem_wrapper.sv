`timescale 1ns/1ps

module boot_mem_wrapper #(
    parameter BOOT_SIZE = 512,
    parameter SRAM_BASE_ADDR = 32'h0000_0000
)(
    input logic clk_i,
    input logic reset_ni,
    input logic pass_thru_en_i,

    //boot status signals
    output logic boot_done_o,
    output logic cores_en_o,

    //mem cntrl read ports
    input logic mem_valid_i,
    input logic [31:0] mem_addr_i,
    input logic [3:0] mem_wstrb_i,
    output logic [31:0] mem_rdata_o,
    output logic mem_ready_o
);

    //housekeeping_top <-> flash model
    wire spi_sck;
    wire spi_mosi;
    wire flash_csb;
    wire flash_si;
    wire flash_so;

    assign flash_si = spi_mosi;   //dut output -> flash input

    //housekeeping_top -> mem_ctrl_2048x32
    wire boot_mem_valid;
    wire [31:0] boot_mem_addr;
    wire [31:0] boot_mem_wdata;
    wire [3:0] boot_mem_wstrb;
    wire boot_mem_instr;

    // Mux between boot writes and testbench reads
    // During boot (boot_done_o == 0): boot controller drives the memory
    // After boot (boot_done_o == 1): tb drives reads via mem_xx_i ports
    wire muxed_valid;
    wire [31:0] muxed_addr;
    wire [31:0] muxed_wdata;
    wire [3:0] muxed_wstrb;

    assign muxed_valid = boot_done_o ? mem_valid_i : boot_mem_valid;
    assign muxed_addr = boot_done_o ? mem_addr_i: boot_mem_addr;
    assign muxed_wdata = boot_done_o ? 32'h0 : boot_mem_wdata;
    assign muxed_wstrb = boot_done_o ? mem_wstrb_i : boot_mem_wstrb;

    //flash inout ports
    wire wp_tie;
    wire io3_tie;
    assign wp_tie  = 1'b1;
    assign io3_tie = 1'b1;

    // housekeeping_top
    housekeeping_top #(
        .BOOT_SIZE(BOOT_SIZE),
        .SRAM_BASE_ADDR (SRAM_BASE_ADDR)
    ) u_housekeeping (
        .clk_i(clk_i),
        .reset_ni(reset_ni),
        .pass_thru_en_i(pass_thru_en_i),
        .spi_sck_o(spi_sck),
        .spi_mosi_o(spi_mosi),
        .spi_miso_i(flash_so),
        .flash_csb_o(flash_csb),
        .mem_valid_o(boot_mem_valid),
        .mem_addr_o(boot_mem_addr),
        .mem_wdata_o(boot_mem_wdata),
        .mem_wstrb_o(boot_mem_wstrb),
        .mem_instr_o(boot_mem_instr),
        .cores_en_o(cores_en_o),
        .boot_done_o(boot_done_o)
    );

    // S25FL128L flash model instance
    s25fl128l #(
        .UserPreload(1),
        .mem_file_name ("boot_image.mem"),
        .TimingModel("S25fl128LAGMFI010")
    ) u_flash (
        .SI(flash_si),
        .SO(flash_so),
        .SCK(spi_sck),
        .CSNeg(flash_csb),
        .RESETNeg(1'b1),
        .WPNeg(wp_tie),
        .IO3_RESETNeg (io3_tie)
    );

    // mem_ctrl_2048x32 
    mem_ctrl_2048x32 u_mem_ctrl (
        .clk_i(clk_i),
        .rst_ni(reset_ni),
        .mem_valid_i(muxed_valid),
        .mem_instr_i(boot_mem_instr),
        .mem_addr_i(muxed_addr),
        .mem_wdata_i(muxed_wdata),
        .mem_wstrb_i(muxed_wstrb),
        .mem_rdata_o(mem_rdata_o),
        .mem_ready_o(mem_ready_o)
    );

endmodule