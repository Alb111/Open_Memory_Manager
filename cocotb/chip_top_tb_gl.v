`timescale 1ns / 1ps

module chip_top_tb_gl;

    parameter NUM_BIDIR_PADS = 52;

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

        // External input pads from your existing 52-bit pad mapping.
        bidir_oe[40]  = 1'b1;  // boot_miso
        bidir_drv[40] = 1'b0;

        bidir_oe[41]  = 1'b1;  // debug_mode
        bidir_drv[41] = 1'b0;

        bidir_oe[42]  = 1'b1;  // dft_in
        bidir_drv[42] = 1'b0;

        rst_n_drv = 1'b0;
        #1000;

        rst_n_drv = 1'b1;
        #250000;

        $display("CVC GL timing smoke test completed.");
        $finish;
    end

endmodule
