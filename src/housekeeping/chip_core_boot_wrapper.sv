`timescale 1ns/1ps

// test wrapper that instantiates chip_core with the cypress flash model connected through pad indices
// pad assignments match localparams in chip_core.sv:
//   bidir_in[40] = MISO (flash SO)
//   bidir_in[41] = debug/pass-through enable
//   bidir_out[1] = SCK (flash clock)
//   bidir_out[2] = MOSI (flash SI data)
//   bidir_out[3] = CSB (flash chip select)

module chip_core_boot_wrapper #(
    parameter NUM_INPUT_PADS = 12,
    parameter NUM_BIDIR_PADS = 52
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

    localparam int PIN_BOOT_MISO = 40;
    localparam int PIN_DEBUG_MODE = 41;
    localparam int PIN_BOOT_SCLK = 1;
    localparam int PIN_BOOT_MOSI = 2;
    localparam int PIN_BOOT_CS = 3;

    wire flash_miso;

    always_comb begin
        core_bidir_in = bidir_in;
        core_bidir_in[PIN_BOOT_MISO] = flash_miso;
        core_bidir_in[PIN_DEBUG_MODE] = input_in[1];
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
    wire flash_sck = bidir_out[PIN_BOOT_SCLK];
    wire flash_mosi = bidir_out[PIN_BOOT_MOSI];
    wire flash_csb = bidir_out[PIN_BOOT_CS];

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
