`timescale 1ns/1ps

// test wrapper that instantiates chip_core with the cypress flash model connected through pad indices
// pad assignments match localparams in chip_core.sv:
//   bidir_in[0] = debug mode
//   bidir_in[1] = boot pass-through enable
//   bidir_out[2] = CSB (flash chip select)
//   bidir_in[3] = MISO (flash SO)
//   bidir_out[4] = MOSI (flash SI data)
//   bidir_out[5] = SCK (flash clock)

module chip_core_boot_wrapper #(
    parameter NUM_INPUT_PADS = 2,
    parameter NUM_BIDIR_PADS = 66
)(
    input logic clk,
    input logic rst_n,
    input logic [NUM_INPUT_PADS-1:0] input_in,
    input logic [NUM_BIDIR_PADS-1:0] bidir_in,
    output logic boot_done_o,
    output logic cores_en_o
);

    //wires for chip_core pad interface
    logic [NUM_BIDIR_PADS-1:0] bidir_out;
    logic [NUM_BIDIR_PADS-1:0] bidir_oe;
    logic [NUM_BIDIR_PADS-1:0] bidir_cs;
    logic [NUM_BIDIR_PADS-1:0] bidir_sl;
    logic [NUM_BIDIR_PADS-1:0] bidir_ie;
    logic [NUM_BIDIR_PADS-1:0] bidir_pu;
    logic [NUM_BIDIR_PADS-1:0] bidir_pd;
    logic [NUM_BIDIR_PADS-1:0] core_bidir_in;

    localparam int DEBUG_MODE_ID = 0;
    localparam int BOOT_PASS_EN_ID = 1;
    localparam int FLASH_CSB_ID = 2;
    localparam int SPI_MISO_ID = 3;
    localparam int SPI_MOSI_ID = 4;
    localparam int SPI_SCLK_ID = 5;

    wire flash_miso;

    always_comb begin
        core_bidir_in = bidir_in;
        core_bidir_in[DEBUG_MODE_ID] = input_in[DEBUG_MODE_ID];
        core_bidir_in[BOOT_PASS_EN_ID] = input_in[BOOT_PASS_EN_ID];
        core_bidir_in[SPI_MISO_ID] = flash_miso;
    end

    chip_core #(
        .NUM_BIDIR_PADS  (NUM_BIDIR_PADS)
    ) dut (
        .clk       (clk),
        .rst_n     (rst_n),
        .bidir_in  (core_bidir_in),
        .bidir_out (bidir_out),
        .bidir_oe  (bidir_oe),
        .bidir_cs  (bidir_cs),
        .bidir_sl  (bidir_sl),
        .bidir_ie  (bidir_ie),
        .bidir_pu  (bidir_pu),
        .bidir_pd  (bidir_pd)
    );

    //get spi signals from the bidir pad outputs
    wire flash_sck = bidir_out[SPI_SCLK_ID];
    wire flash_mosi = bidir_out[SPI_MOSI_ID];
    wire flash_csb = bidir_out[FLASH_CSB_ID];

    //flash model tie-off wires (inout ports)
    wire wp_tie;
    wire io3_tie;
    assign wp_tie = 1'b1;
    assign io3_tie = 1'b1;

    //cypress flash model
    s25fl128l #(
        .UserPreload   (1),
        .mem_file_name ("boot_image.mem"),
        .TimingModel   ("S25fl128LAGMFI010")
    ) u_flash (
        .SI           (flash_mosi),
        .SO           (flash_miso),
        .SCK          (flash_sck),
        .CSNeg        (flash_csb),
        .RESETNeg     (1'b1),
        .WPNeg        (wp_tie),
        .IO3_RESETNeg (io3_tie)
    );

    //expose boot status signals for cocotb
    assign boot_done_o = dut.i_housekeeping_top.boot_done_o;
    assign cores_en_o = dut.i_housekeeping_top.cores_en_o;

endmodule
