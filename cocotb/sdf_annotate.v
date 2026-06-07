// sdf_annotate.v
// Compiled only when SDF_FILE is defined (i.e. make sim-sdf).
// Injects SDF back-annotation into the cocotb DUT instance at time 0.
`ifdef SDF_FILE
module sdf_annotate_shim;
  initial begin
    $sdf_annotate(`SDF_FILE, chip_top_tb.dut);
  end
endmodule
`endif
