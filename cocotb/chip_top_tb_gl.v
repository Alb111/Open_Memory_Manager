`timescale 1ns / 1ps

module chip_top_tb_gl;

    parameter NUM_BIDIR_PADS = 66;
    parameter SER_PINS = 9;

    localparam DEBUG_MODE_ID = 0;
    localparam BOOT_PASS_EN_ID = 1;
    localparam SPI_MISO_ID = 3;
    localparam C0_REQ_I_ID = 6;
    localparam C0_SERIAL_I_START_ID = 7;
    localparam C0_TRAP_I_ID = 65;
    localparam DFT_START_ID = 32;
    localparam DFT_PINS = 8;
    localparam C1_REQ_I_ID = 40;
    localparam C1_SERIAL_I_START_ID = 41;
    localparam C1_TRAP_I_ID = 31;

    wire clk_PAD;
    wire rst_n_PAD;

    reg clk_drv;
    reg rst_n_drv;

`ifdef USE_POWER_PINS
    wire VDD;
    wire VSS;
`endif

    wire [NUM_BIDIR_PADS-1:0] bidir_PAD;
    reg  [NUM_BIDIR_PADS-1:0] bidir_drv;
    reg  [NUM_BIDIR_PADS-1:0] bidir_oe;

    genvar i;
    integer j;

    assign clk_PAD = clk_drv;
    assign rst_n_PAD = rst_n_drv;

`ifdef USE_POWER_PINS
    assign VDD = 1'b1;
    assign VSS = 1'b0;
`endif

    generate
        for (i = 0; i < NUM_BIDIR_PADS; i = i + 1) begin : gen_bidir_pad
            assign bidir_PAD[i] = bidir_oe[i] ? bidir_drv[i] : 1'bz;
        end
    endgenerate

    chip_top dut (
`ifdef USE_POWER_PINS
        .VDD       (VDD),
        .VSS       (VSS),
`endif
        .clk_PAD   (clk_PAD),
        .rst_n_PAD (rst_n_PAD),
        .bidir_PAD (bidir_PAD)
    );

`ifdef USE_SDF

`include "sdf_file_define.vh"

    initial begin
        $display("CVC: annotating SDF file: %0s", `SDF_FILE);

        $sdf_annotate(
            `SDF_FILE,
            chip_top_tb_gl.dut
        );

        $display("CVC: SDF annotation complete.");
    end

`endif

    initial begin
        clk_drv = 1'b0;
        forever #25 clk_drv = ~clk_drv;
    end
/*
    initial begin
        $dumpfile("chip_top_tb_gl.vcd");
        $dumpvars(0, chip_top_tb_gl);
    end
*/
    initial begin
        bidir_drv = {NUM_BIDIR_PADS{1'b0}};
        bidir_oe  = {NUM_BIDIR_PADS{1'b0}};

        // External inputs to the memory-manager chip.
        bidir_oe[DEBUG_MODE_ID] = 1'b1;
        bidir_oe[BOOT_PASS_EN_ID] = 1'b1;
        bidir_oe[SPI_MISO_ID] = 1'b1;
        bidir_oe[C0_REQ_I_ID] = 1'b1;
        bidir_oe[C1_REQ_I_ID] = 1'b1;
        bidir_oe[C0_TRAP_I_ID] = 1'b1;
        bidir_oe[C1_TRAP_I_ID] = 1'b1;

        for (j = 0; j < SER_PINS; j = j + 1) begin
            bidir_oe[C0_SERIAL_I_START_ID + j] = 1'b1;
            bidir_oe[C1_SERIAL_I_START_ID + j] = 1'b1;
        end

        for (j = 0; j < DFT_PINS; j = j + 1) begin
            bidir_oe[DFT_START_ID + j] = 1'b1;
        end

        rst_n_drv = 1'b0;
        #1000;

        rst_n_drv = 1'b1;
        #250000;

        $display("CVC GL timing smoke test completed.");
        $finish;
    end

endmodule
