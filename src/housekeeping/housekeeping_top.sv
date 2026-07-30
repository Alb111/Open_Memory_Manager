`timescale 1ns/1ps

module housekeeping_top #(
   parameter BOOT_SIZE = 512,
   parameter SRAM_BASE_ADDR = 32'h0000_0000
)(
   input logic clk_i,
   input logic reset_ni,
    
   // spi flash pins
   output logic spi_sck_o,
   output logic spi_mosi_o,
   input logic spi_miso_i,
   output logic flash_csb_o,

   input logic pass_thru_en_i,   // switch: 0 = boot, 1 = pass thru
    
   input logic whoami_ready_i,   // dir_ready_o from directory interface

   // output writing
   output logic mem_valid_o,
   output logic [31:0] mem_addr_o,
   output logic [31:0] mem_wdata_o,
   output logic [3:0] mem_wstrb_o,
   output logic mem_instr_o,
    
   //core control
   output logic cores_en_o,
   output logic boot_done_o,

   output logic whoami_pulse_o,

   // Reset-time memory clear handshake with the external reset generator.
   output logic mem_clear_start_o,  // request a full clear (held until done)
   input  logic mem_clear_done_i,   // asserted when the reset generator is done

   input  logic scan_en_i,
   input  logic scan_in_i,
   output logic scan_out_o
);
   
   // wires between spi and fsm
   logic spi_start;
   logic spi_done;
   logic spi_busy;
   logic [7:0] spi_data_out;
   logic [7:0] spi_data_in;

   // internal wires from boot_fsm to mem controller adapter
   logic boot_wr_en;
   logic [31:0] boot_addr;
   logic [31:0] boot_data;

   logic boot_started;
   logic whoami_sent;
   logic spi_scan_out;
   logic boot_scan_out;

   //boot_fsm signals to memory controller interface
   assign mem_valid_o = boot_wr_en;
   assign mem_addr_o = boot_addr;
   assign mem_wdata_o = boot_data;
   assign mem_wstrb_o = boot_wr_en ? 4'b1111 : 4'b0000;
   assign mem_instr_o = 1'b0;

   logic clear_done;

   // Boot/SPI stay in reset until the external reset generator reports the
   // memories are fully cleared, so the boot process never begins over dirty
   // memory. There is no blind settle counter: the handshake is the only gate.
   assign clear_done = mem_clear_done_i;

   // Prompt the reset generator out of reset and hold the request asserted until
   // it reports completion (its start is rising-edge triggered).
   assign mem_clear_start_o = !mem_clear_done_i;


   // spi engine
   spi_engine spi_master (
      .clk_i(clk_i),
      .reset_ni(reset_ni && (scan_en_i || (!pass_thru_en_i && clear_done))),
      .start_i(spi_start),
      .data_in_i(spi_data_out),
      .data_out_o(spi_data_in),
      .done_o(spi_done),
      .busy_o(spi_busy),
      .spi_sck_o(spi_sck_o), 
      .spi_mosi_o(spi_mosi_o),
      .spi_miso_i(spi_miso_i),
      .scan_en_i(scan_en_i),
      .scan_in_i(scan_in_i),
      .scan_out_o(spi_scan_out)
   );
   
   // boot fsm
   boot_fsm #(
      .BOOT_SIZE      (BOOT_SIZE),
      .SRAM_BASE_ADDR (SRAM_BASE_ADDR)
   ) boot_controller (
      .clk_i(clk_i),
      .reset_ni(reset_ni && (scan_en_i || (!pass_thru_en_i && clear_done))),
      .spi_start_o(spi_start),
      .spi_out_o(spi_data_out),
      .spi_in_i(spi_data_in),
      .spi_done_i(spi_done),
      .spi_busy_i(spi_busy),
      .flash_csb_o(flash_csb_o),
      .sram_wr_en_o(boot_wr_en),
      .sram_addr_o(boot_addr),
      .sram_data_o(boot_data),
      .cores_en_o(cores_en_o),
      .boot_done_o(boot_done_o),
      .boot_started_o(boot_started),
      .scan_en_i(scan_en_i),
      .scan_in_i(spi_scan_out),
      .scan_out_o(boot_scan_out)
   );

   // hold whoami_pulse high until the directory interface accepts it
   always_ff @(posedge clk_i) begin
      if (!reset_ni)
         whoami_sent <= 1'b0;
      else if (scan_en_i)
         // Scan chain: boot_fsm -> whoami_sent (clear_counter removed).
         whoami_sent <= boot_scan_out;
      else if (whoami_pulse_o && whoami_ready_i)
         whoami_sent <= 1'b1;
   end

   // assert pulse once boot starts, hold until accepted, never repeat
   assign whoami_pulse_o = boot_started && !whoami_sent;
   assign scan_out_o = whoami_sent;

endmodule
