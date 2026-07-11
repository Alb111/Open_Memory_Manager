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
    localparam int BOOT_SIZE = 512;
    localparam int SRAM_BASE_ADDR = 0;

    localparam int DEBUG_MODE_ID = 0;
    localparam int BOOT_PASS_EN_ID = 1;
    localparam int FLASH_CSB_ID = 2;
    localparam int SPI_MISO_ID = 3;
    localparam int SPI_MOSI_ID = 4;
    localparam int SPI_SCLK_ID = 5;

    localparam int C0_REQ_O_ID = 6;
    localparam int C0_SERIAL_O_START_ID = 7;
    localparam int C0_REQ_I_ID = 16;
    localparam int C0_SERIAL_I_START_ID = 17;
    localparam int C0_BOOT_DONE = 26;
    localparam int C0_DEBUG_MODE_ID = 27;
    localparam int C0_RST_N_ID = 28;
    localparam int C0_CLK_ID = 29;
    localparam int C0_TRAP_I_ID = 65;
    localparam int C0_TRAP_O_ID = 64;

    localparam int DFT_START_ID = 32;
    localparam int DFT_PINS = 8;

    localparam int C1_REQ_O_ID = 40;
    localparam int C1_SERIAL_O_START_ID = 41;
    localparam int C1_REQ_I_ID = 50;
    localparam int C1_SERIAL_I_START_ID = 51;
    localparam int C1_BOOT_DONE = 60;
    localparam int C1_DEBUG_MODE_ID = 61;
    localparam int C1_RST_N_ID = 62;
    localparam int C1_CLK_ID = 63;
    localparam int C1_TRAP_I_ID = 31;
    localparam int C1_TRAP_O_ID = 30;

    assign bidir_cs = '0;
    // SL=0 selects the fastest slew on the GF180 bidirectional pads.
    assign bidir_sl = '0;
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
    logic        boot_pass_en;
    logic        core_mem_select;
    logic        core_rst_n;

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

    assign debug_mode = bidir_in[DEBUG_MODE_ID];
    assign boot_pass_en = bidir_in[BOOT_PASS_EN_ID];
    assign core_mem_select = debug_mode | boot_done;
    assign core_rst_n = rst_n & (debug_mode | cores_en);

    assign c0_serial_rx = bidir_in[C0_SERIAL_I_START_ID +: SER_PINS];
    assign c1_serial_rx = bidir_in[C1_SERIAL_I_START_ID +: SER_PINS];
    assign c0_req_rx = bidir_in[C0_REQ_I_ID];
    assign c1_req_rx = bidir_in[C1_REQ_I_ID];

    always_comb begin
        bidir_out_int = '0;
        bidir_oe_int = '0;

        bidir_out_int[FLASH_CSB_ID] = boot_flash_csb;
        bidir_oe_int[FLASH_CSB_ID] = !boot_pass_en;

        bidir_out_int[SPI_MOSI_ID] = boot_spi_mosi;
        bidir_oe_int[SPI_MOSI_ID] = !boot_pass_en;

        bidir_out_int[SPI_SCLK_ID] = boot_spi_sck;
        bidir_oe_int[SPI_SCLK_ID] = !boot_pass_en;

        bidir_out_int[C0_REQ_O_ID] = c0_req_tx;
        bidir_oe_int[C0_REQ_O_ID] = 1'b1;

        bidir_out_int[C0_SERIAL_O_START_ID +: SER_PINS] = c0_serial_tx;
        bidir_oe_int[C0_SERIAL_O_START_ID +: SER_PINS] = {SER_PINS{1'b1}};

        bidir_out_int[C0_BOOT_DONE] = boot_done;
        bidir_oe_int[C0_BOOT_DONE] = 1'b1;

        bidir_out_int[C0_DEBUG_MODE_ID] = debug_mode;
        bidir_oe_int[C0_DEBUG_MODE_ID] = 1'b1;

        bidir_out_int[C0_RST_N_ID] = rst_n;
        bidir_oe_int[C0_RST_N_ID] = 1'b1;

        bidir_out_int[C0_CLK_ID] = clk;
        bidir_oe_int[C0_CLK_ID] = 1'b1;

        bidir_out_int[C0_TRAP_O_ID] = bidir_in[C0_TRAP_I_ID];
        bidir_oe_int[C0_TRAP_O_ID] = 1'b1;

        bidir_out_int[C1_REQ_O_ID] = c1_req_tx;
        bidir_oe_int[C1_REQ_O_ID] = 1'b1;

        bidir_out_int[C1_SERIAL_O_START_ID +: SER_PINS] = c1_serial_tx;
        bidir_oe_int[C1_SERIAL_O_START_ID +: SER_PINS] = {SER_PINS{1'b1}};

        bidir_out_int[C1_BOOT_DONE] = boot_done;
        bidir_oe_int[C1_BOOT_DONE] = 1'b1;

        bidir_out_int[C1_DEBUG_MODE_ID] = debug_mode;
        bidir_oe_int[C1_DEBUG_MODE_ID] = 1'b1;

        bidir_out_int[C1_RST_N_ID] = rst_n;
        bidir_oe_int[C1_RST_N_ID] = 1'b1;

        bidir_out_int[C1_CLK_ID] = clk;
        bidir_oe_int[C1_CLK_ID] = 1'b1;

        bidir_out_int[C1_TRAP_O_ID] = bidir_in[C1_TRAP_I_ID];
        bidir_oe_int[C1_TRAP_O_ID] = 1'b1;
    end

    assign bidir_out = bidir_out_int;
    assign bidir_oe = bidir_oe_int;

    housekeeping_top #(
        .BOOT_SIZE      (BOOT_SIZE),
        .SRAM_BASE_ADDR (SRAM_BASE_ADDR)
    ) i_housekeeping_top (
        .clk_i          (clk),
        .reset_ni       (rst_n),
        .spi_sck_o      (boot_spi_sck),
        .spi_mosi_o     (boot_spi_mosi),
        .spi_miso_i     (bidir_in[SPI_MISO_ID]),
        .flash_csb_o    (boot_flash_csb),
        .pass_thru_en_i (boot_pass_en),
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
  	.rst_ni             (rst_n),

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
  	.rst_ni             (rst_n),

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
