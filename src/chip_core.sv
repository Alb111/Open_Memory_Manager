// SPDX-FileCopyrightText: © 2025 XXX Authors
// SPDX-License-Identifier: Apache-2.0

`default_nettype none

`timescale 1ns/1ps

module chip_core #(
    parameter NUM_BIDIR_PADS
    )(

    `ifdef USE_POWER_PINS
    inout  wire VDD,
    inout  wire VSS,
    `endif

    input  wire clk,
    input  wire rst_n,

    input  wire [NUM_BIDIR_PADS-1:0] bidir_in, 	//Input value
    output wire [NUM_BIDIR_PADS-1:0] bidir_out, //Output value
    output wire [NUM_BIDIR_PADS-1:0] bidir_oe,  //Output enable
    output wire [NUM_BIDIR_PADS-1:0] bidir_cs,	//Input type (0=CMOS buffer, 1=Schmitt Trigger)
    output wire [NUM_BIDIR_PADS-1:0] bidir_sl,  //Slew rate (0=fast, 1=slow)
    output wire [NUM_BIDIR_PADS-1:0] bidir_ie,	//Input enable
    output wire [NUM_BIDIR_PADS-1:0] bidir_pu,	//Pull-up
    output wire [NUM_BIDIR_PADS-1:0] bidir_pd	//Pull-down
);
    localparam int SER_PINS = 9;

    // Former input pads, now carried on the appended bidirectional pads.
    localparam int PIN_BOOT_MISO = 40;
    localparam int PIN_DEBUG_MODE = 41;
    localparam int PIN_DFT_IN = 42;

    // Original bidirectional/output pad assignments are kept stable.
    localparam int PIN_TRAP_LED = 0;
    localparam int PIN_BOOT_SCLK = 1;
    localparam int PIN_BOOT_MOSI = 2;
    localparam int PIN_BOOT_CS = 3;
    localparam int PIN_DFT_OUT = 4;

    // TODO: Audit the 52-pad slot map. Only pads 0-4 and 40-42 are used here;
    // pads 5-39 and 43-51 are currently left as input-enabled, no-pull pads.
    // Either assign them real functions, disable their input buffers, or document
    // them as intentionally unused spare pads in the top-level pinout.
    // TODO: Add a NUM_BIDIR_PADS bounds check for the fixed pad indices above.
    // This core indexes through PIN_DFT_IN=42, so any slot with fewer than 43
    // bidirectional pads will compile/elaborate incorrectly.
    assign bidir_cs = '0;
    assign bidir_sl = '0;
    // TODO: Confirm the intended pad control policy for input-only and unused
    // bidirectional pads. Tying IE to ~OE enables every unused pad input buffer,
    // which can create floating inputs unless the board drives them or pulls are
    // enabled externally.
    assign bidir_ie = ~bidir_oe;
    assign bidir_pu = '0;
    assign bidir_pd = '0;

	//core0
    logic        c0_bus_valid, c0_bus_ready;
    logic [4:0]  c0_bus_cache_cmd;
    logic [31:0] c0_bus_addr, c0_bus_wdata;
    logic        c0_snoop_valid, c0_snoop_ready;
    logic [2:0]  c0_snoop_cache_cmd;
    logic [31:0] c0_snoop_data;
    logic        c0_dir_valid, c0_reset_done;
    logic [5:0]  c0_dir_cmd;
    logic [31:0] c0_dir_data, c0_dir_addr;
    logic 		 c0_tser_ready;

	//core1
    logic        c1_bus_valid, c1_bus_ready;
    logic [4:0]  c1_bus_cache_cmd;
    logic [31:0] c1_bus_addr, c1_bus_wdata;
    logic        c1_snoop_valid, c1_snoop_ready;
    logic [2:0]  c1_snoop_cache_cmd;
    logic [31:0] c1_snoop_data;
    logic        c1_dir_valid, c1_reset_done;
    logic [5:0]  c1_dir_cmd;
    logic [31:0] c1_dir_data, c1_dir_addr;
    logic		 c1_tser_ready;

	//directory
    logic        dir_mem_valid, dir_mem_ready;
    logic [3:0]  dir_mem_wstrb;
    logic [31:0] dir_mem_addr;

    logic [31:0] dir_mem_w_data;
    logic [1:0]  dir_mem_w_state;
    logic [1:0]  dir_mem_w_sharers;
    logic        dir_mem_w_owner;
    logic        dir_mem_w_valid_data;

    logic [31:0] dir_mem_r_data;
    logic [1:0]  dir_mem_r_state;
    logic [1:0]  dir_mem_r_sharers;
    logic [1:0]  dir_mem_r_owner;
    logic [1:0]  dir_mem_r_valid_data;
 
    logic        dir_mem_resp_ready;
    logic        dir_state_invalidated;


	//boot
    logic        boot_mem_valid;
    logic        boot_mem_instr;
    logic [31:0] boot_mem_addr;
    logic [31:0] boot_mem_wdata;
    logic [3:0]  boot_mem_wstrb;
    logic        boot_spi_sck;
    logic        boot_spi_mosi;
    logic        boot_flash_csb;
    logic        boot_done;
    logic        cores_en;
    logic        debug_mode;
    logic        core_mem_select;
    logic        core_rst_n;
    logic        trap_led;
    logic        dft_in;
    logic        dft_out;

	//SERDES
    logic [SER_PINS-1:0] c0_serial_tx;
    logic [SER_PINS-1:0] c1_serial_tx;
    logic [SER_PINS-1:0] c0_serial_rx;
    logic [SER_PINS-1:0] c1_serial_rx;
    logic                c0_req_tx;
    logic                c1_req_tx;
    logic                c0_req_rx;
    logic                c1_req_rx;


    logic [NUM_BIDIR_PADS-1:0] bidir_out_int;
    logic [NUM_BIDIR_PADS-1:0] bidir_oe_int;

    wire whoami_pulse;
    wire whoami_ready;

    assign whoami_ready = c0_tser_ready && c1_tser_ready;

    assign debug_mode = bidir_in[PIN_DEBUG_MODE];
    assign dft_in = bidir_in[PIN_DFT_IN];
    assign dft_out = dft_in;
    // TODO: Drive trap_led from a real trap/fault source or rename this pad as a
    // constant-low output. It is currently marked as used but never reflects core
    // state.
    assign trap_led = 1'b0;
    assign core_mem_select = debug_mode | boot_done;
    assign core_rst_n = rst_n & (debug_mode | cores_en);

    assign c0_serial_rx = c1_serial_tx;
    assign c1_serial_rx = c0_serial_tx;
    assign c0_req_rx = c1_req_tx;
    assign c1_req_rx = c0_req_tx;

    always_comb begin
        bidir_out_int = '0;
        bidir_oe_int = '0;

        bidir_out_int[PIN_TRAP_LED] = trap_led;
        bidir_oe_int[PIN_TRAP_LED] = 1'b1;

        bidir_out_int[PIN_BOOT_SCLK] = boot_spi_sck;
        bidir_oe_int[PIN_BOOT_SCLK] = !debug_mode;

        bidir_out_int[PIN_BOOT_MOSI] = boot_spi_mosi;
        bidir_oe_int[PIN_BOOT_MOSI] = !debug_mode;

        bidir_out_int[PIN_BOOT_CS] = boot_flash_csb;
        bidir_oe_int[PIN_BOOT_CS] = !debug_mode;

        bidir_out_int[PIN_DFT_OUT] = dft_out;
        bidir_oe_int[PIN_DFT_OUT] = 1'b1;
    end

    assign bidir_out = bidir_out_int;
    assign bidir_oe = bidir_oe_int;

    housekeeping_top i_housekeeping_top (
        .clk_i          (clk),
        .reset_ni       (rst_n),
        .spi_sck_o      (boot_spi_sck),
        .spi_mosi_o     (boot_spi_mosi),
        .spi_miso_i     (bidir_in[PIN_BOOT_MISO]),
        .flash_csb_o    (boot_flash_csb),
        .pass_thru_en_i (debug_mode),
        .whoami_ready_i (whoami_ready),
        .mem_valid_o    (boot_mem_valid),
        .mem_addr_o     (boot_mem_addr),
        .mem_wdata_o    (boot_mem_wdata),
        .mem_wstrb_o    (boot_mem_wstrb),
        .mem_instr_o    (boot_mem_instr),
        .cores_en_o     (cores_en),
        .boot_done_o    (boot_done),
        .whoami_pulse_o (whoami_pulse)
    );

    directory_interface #(
  	.NUM_TPINS(SER_PINS),
    .NUM_RPINS(9)
    ) i_directory_interface_0 (
  	.clk_i              (clk),
  	.rst_ni             (core_rst_n),

  	.bus_valid_o        (c0_bus_valid),
  	.bus_addr_o         (c0_bus_addr),
  	.bus_wdata_o        (c0_bus_wdata),
  	.bus_cache_cmd_o    (c0_bus_cache_cmd),
  	.bus_ready_i        (c0_bus_ready),

  	.snoop_valid_o      (c0_snoop_valid),
  	.snoop_data_o       (c0_snoop_data),
  	.snoop_cache_cmd_o  (c0_snoop_cache_cmd),
  	.snoop_ready_i      (c0_snoop_ready),

  	.dir_valid_i        (c0_dir_valid),
  	.dir_data_i         (c0_dir_data),
  	.dir_addr_i         (c0_dir_addr),
  	.dir_cmd_i          (c0_dir_cmd),
    .dir_ready_o        (c0_tser_ready),

    // TODO: Decide whether receive-side busy should feed reset/boot sequencing,
    // flow control, or status. Leaving rbusy_o open hides serializer receive
    // activity from the chip core.
  	.rbusy_o            (),
    .send_WhoAmI_i      (whoami_pulse),
  	.cpu_id_i           (8'h00),
  	.reset_done_o       (c0_reset_done),

  	.req_i              (c0_req_rx),
  	.serial_i           (c0_serial_rx),
  	.req_o              (c0_req_tx),
  	.serial_o           (c0_serial_tx)
    );

    directory_interface #(
  	.NUM_TPINS(SER_PINS),
  	.NUM_RPINS(SER_PINS)
    ) i_directory_interface_1 (
  	.clk_i              (clk),
  	.rst_ni             (core_rst_n),

  	.bus_valid_o        (c1_bus_valid),
  	.bus_addr_o         (c1_bus_addr),
  	.bus_wdata_o        (c1_bus_wdata),
  	.bus_cache_cmd_o    (c1_bus_cache_cmd),
  	.bus_ready_i        (c1_bus_ready),

  	.snoop_valid_o      (c1_snoop_valid),
  	.snoop_data_o       (c1_snoop_data),
  	.snoop_cache_cmd_o  (c1_snoop_cache_cmd),
  	.snoop_ready_i      (c1_snoop_ready),

  	.dir_valid_i        (c1_dir_valid),
  	.dir_data_i         (c1_dir_data),
  	.dir_addr_i         (c1_dir_addr),
  	.dir_cmd_i          (c1_dir_cmd),
    .dir_ready_o        (c1_tser_ready),

    // TODO: Decide whether receive-side busy should feed reset/boot sequencing,
    // flow control, or status. Leaving rbusy_o open hides serializer receive
    // activity from the chip core.
  	.rbusy_o            (),
    .send_WhoAmI_i      (whoami_pulse),
  	.cpu_id_i           (8'h01),
  	.reset_done_o       (c1_reset_done),

  	.req_i              (c1_req_rx),
  	.serial_i           (c1_serial_rx),
  	.req_o              (c1_req_tx),
  	.serial_o           (c1_serial_tx)
    );

    directory_controller i_directory_controller (
  	.clk_i                  (clk),
  	.rst_ni                 (core_rst_n),

  	.c0_bus_valid_i         (c0_bus_valid),
  	.c0_bus_addr_i          (c0_bus_addr),
  	.c0_bus_wdata_i         (c0_bus_wdata),
  	.c0_bus_cache_cmd_i     (c0_bus_cache_cmd),
  	.c0_bus_ready_o         (c0_bus_ready),

  	.c0_snoop_valid_i       (c0_snoop_valid),
  	.c0_snoop_data_i        (c0_snoop_data),
  	.c0_snoop_cache_cmd_i   (c0_snoop_cache_cmd),
  	.c0_snoop_ready_o       (c0_snoop_ready),

  	.c0_dir_valid_o         (c0_dir_valid),
  	.c0_dir_data_o          (c0_dir_data),
  	.c0_dir_addr_o          (c0_dir_addr),
  	.c0_dir_cmd_o           (c0_dir_cmd),
    .c0_dir_ready_i         (c0_tser_ready),

  	.c1_bus_valid_i         (c1_bus_valid),
  	.c1_bus_addr_i          (c1_bus_addr),
  	.c1_bus_wdata_i         (c1_bus_wdata),
  	.c1_bus_cache_cmd_i     (c1_bus_cache_cmd),
  	.c1_bus_ready_o         (c1_bus_ready),

  	.c1_snoop_valid_i       (c1_snoop_valid),
  	.c1_snoop_data_i        (c1_snoop_data),
  	.c1_snoop_cache_cmd_i   (c1_snoop_cache_cmd),
  	.c1_snoop_ready_o       (c1_snoop_ready),

  	.c1_dir_valid_o         (c1_dir_valid),
  	.c1_dir_data_o          (c1_dir_data),
  	.c1_dir_addr_o          (c1_dir_addr),
  	.c1_dir_cmd_o           (c1_dir_cmd),
    .c1_dir_ready_i         (c1_tser_ready),
	
  	.dir_mem_valid_o        (dir_mem_valid),
  	.dir_mem_ready_i        (dir_mem_ready),
  	.dir_mem_addr_o         (dir_mem_addr),
  	.dir_mem_wstrb_o        (dir_mem_wstrb),
  	.dir_mem_w_data_o       (dir_mem_w_data),
  	.dir_mem_w_state_o      (dir_mem_w_state),
  	.dir_mem_w_sharers_o    (dir_mem_w_sharers),
  	.dir_mem_w_owner_o      (dir_mem_w_owner),
  	.dir_mem_w_valid_data_o (dir_mem_w_valid_data),

  	.dir_mem_r_data_i       (dir_mem_r_data),
  	.dir_mem_r_state_i      (dir_mem_r_state),
  	.dir_mem_r_sharers_i    (dir_mem_r_sharers),
  	.dir_mem_r_owner_i      (dir_mem_r_owner),
  	.dir_mem_r_valid_data_i (dir_mem_r_valid_data),
  	.dir_mem_resp_ready_o   (dir_mem_resp_ready),

  	.dir_state_invalidated_o(dir_state_invalidated)
    );
	
    directory_mem i_directory_mem (
  	.clk_i             (clk),
  	.rst_ni            (core_rst_n),
	.mem_rst_ni        (rst_n),

  	// Directory controller side
  	.valid_i           (dir_mem_valid),
  	.ready_o           (dir_mem_ready),
  	.addr_i            (dir_mem_addr),
  	.wstrb_i           (dir_mem_wstrb),

  	.w_data_i          (dir_mem_w_data),
  	.w_state_i         (dir_mem_w_state),
  	.w_sharers_i       (dir_mem_w_sharers),
  	.w_owner_i         (dir_mem_w_owner),
  	.w_valid_data_i    (dir_mem_w_valid_data),

  	.r_data_o          (dir_mem_r_data),
  	.r_state_o         (dir_mem_r_state),
  	.r_tag_o           (dir_mem_r_sharers),
  	.r_owner_o         (dir_mem_r_owner),
  	.r_valid_data_o    (dir_mem_r_valid_data),
  	.ready_i           (dir_mem_resp_ready),

	.core_mem_select_i (core_mem_select),
	.boot_mem_valid_i  (boot_mem_valid),
	.boot_mem_instr_i  (boot_mem_instr),
	.boot_mem_addr_i   (boot_mem_addr),
	.boot_mem_wdata_i  (boot_mem_wdata),
	.boot_mem_wstrb_i  (boot_mem_wstrb)
    `ifdef USE_POWER_PINS
      ,.VDD            (VDD)
      ,.VSS            (VSS)
    `endif
    );

    logic _unused;
    assign _unused = &{bidir_in, c0_reset_done, c1_reset_done};

endmodule

`default_nettype wire
