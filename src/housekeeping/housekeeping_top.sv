module housekeeping_top #(
    parameter BOOT_SIZE = 32,
    parameter SRAM_BASE_ADDR = 32'h0000_0000
)(
    input logic clk_i,
    input logic reset_i,
    
    // spi Flash pins
    output logic spi_sck_o,
    output logic spi_mosi_o,
    input logic spi_miso_i,
    output logic flash_csb_o,
    
    // output writing
    output logic sram_wr_en_o,
    output logic [31:0] sram_addr_o,
    output logic [31:0] sram_data_o,
    
    // Core control
    output logic cores_en_o,
    output logic boot_done_o
);
    // wires between spi and fsm
   logic spi_start;
   logic [7:0] spi_data_out;
   logic [7:0] spi_data_in;
   logic spi_done;
   logic spi_busy;
   
   // spi Engine
   spi_engine spi_master (
      .clk_i(clk_i),
      .reset_i(reset_i),
      .start_i(spi_start),
      .data_in_i(spi_data_out),
      .data_out_o(spi_data_in),
      .done_o(spi_done),
      .busy_o(spi_busy),
      .spi_sck_o(spi_sck_o),
      .spi_mosi_o(spi_mosi_o),
      .spi_miso_i(spi_miso_i)
   );
   
   // boot fsm
   boot_fsm #(
      .BOOT_SIZE      (BOOT_SIZE),
      .SRAM_BASE_ADDR (SRAM_BASE_ADDR)
   ) boot_controller (
      .clk_i(clk_i),
      .reset_i(reset_i),
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
