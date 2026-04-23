`timescale 1ns/1ps

module boot_wrapper #(
    parameter BOOT_SIZE = 512,
    parameter SRAM_BASE_ADDR = 32'h0000_0000
)(
    input  logic clk_i,
    input  logic reset_ni,
    input  logic pass_thru_en_i,

    output logic sram_wr_en_o,
    output logic [31:0] sram_addr_o,
    output logic [31:0] sram_data_o,
    output logic cores_en_o,
    output logic boot_done_o
);

    // SPI wires connecting DUT to flash model
    wire spi_sck;
    wire spi_mosi;
    wire spi_miso;
    wire flash_csb;

    wire flash_si;
    wire flash_so;

    assign flash_si = spi_mosi;

    wire wp_tie;
    wire io3_tie;
    assign wp_tie  = 1'b1;
    assign io3_tie = 1'b1;

    // Your DUT
    housekeeping_top #(
        .BOOT_SIZE      (BOOT_SIZE),
        .SRAM_BASE_ADDR (SRAM_BASE_ADDR)
    ) dut (
        .clk_i          (clk_i),
        .reset_ni       (reset_ni),
        .pass_thru_en_i (pass_thru_en_i),
        .spi_sck_o      (spi_sck),
        .spi_mosi_o     (spi_mosi),
        .spi_miso_i     (flash_so),
        .flash_csb_o    (flash_csb),
        .sram_wr_en_o   (sram_wr_en_o),
        .sram_addr_o    (sram_addr_o),
        .sram_data_o    (sram_data_o),
        .cores_en_o     (cores_en_o),
        .boot_done_o    (boot_done_o)
    );

    // Vendor flash model
    // mem_file_name points to your preload file (relative to sim run dir)
    s25fl128l #(
        .UserPreload    (1),
        .mem_file_name  ("boot_image.mem"),
        .TimingModel    ("S25fl128LAGMFI010")
    ) flash (
        .SI             (flash_si),
        .SO             (flash_so),
        .SCK            (spi_sck),
        .CSNeg          (flash_csb),
        .RESETNeg       (1'b1),
        .WPNeg          (wp_tie),
        .IO3_RESETNeg   (io3_tie)
    );

endmodule