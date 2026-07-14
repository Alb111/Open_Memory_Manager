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

    // Physically buffered scan/functional-mode controls. Separate branches
    // prevent one pad-driven net from spanning every scan mux in the core.
    input  wire [3:0] debug_mode_i,
    input  wire [4:0] c0_req_i_branches,
    input  wire [4:0] c1_req_i_branches,

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

    localparam int BOOT_PASS_EN_ID = 1;
    localparam int FLASH_CSB_ID = 2;
    localparam int SPI_MISO_ID = 3;
    localparam int SPI_MOSI_ID = 4;
    localparam int SPI_SCLK_ID = 5;

    // I/O suffixes are from this chip's perspective: *_I pads are driven by
    // the external chips, while *_O pads are driven by this chip.
    localparam int C0_SERIAL_I_START_ID = 7;
    localparam int C0_REQ_O_ID = 16;
    localparam int C0_SERIAL_O_START_ID = 17;
    localparam int C0_BOOT_DONE = 26;
    localparam int C0_DEBUG_MODE_ID = 27;
    localparam int C0_RST_N_ID = 28;
    localparam int C0_TRAP_I_ID = 65;
    localparam int C0_TRAP_O_ID = 64;

    localparam int DFT_START_ID = 32;
    localparam int DFT_PINS = 8;
    localparam int DFT_CHAINS = DFT_PINS / 2;

    localparam int C1_SERIAL_I_START_ID = 41;
    localparam int C1_REQ_O_ID = 50;
    localparam int C1_SERIAL_O_START_ID = 51;
    localparam int C1_BOOT_DONE = 60;
    localparam int C1_DEBUG_MODE_ID = 61;
    localparam int C1_RST_N_ID = 62;
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
    logic [3:0]  c0_bus_cache_cmd;
    logic [31:0] c0_bus_addr, c0_bus_wdata;
    logic        c0_snoop_valid, c0_snoop_ready;
    logic [3:0]  c0_snoop_cache_cmd;
    logic [31:0] c0_snoop_data;
    logic        c0_dir_valid, c0_reset_done;
    logic [3:0]  c0_dir_cmd;
    logic [31:0] c0_dir_data, c0_dir_addr;
    logic 		 c0_tser_ready;

	//core1
    logic        c1_bus_valid, c1_bus_ready;
    logic [3:0]  c1_bus_cache_cmd;
    logic [31:0] c1_bus_addr, c1_bus_wdata;
    logic        c1_snoop_valid, c1_snoop_ready;
    logic [3:0]  c1_snoop_cache_cmd;
    logic [31:0] c1_snoop_data;
    logic        c1_dir_valid, c1_reset_done;
    logic [3:0]  c1_dir_cmd;
    logic [31:0] c1_dir_data, c1_dir_addr;
    logic		 c1_tser_ready;

	//directory subsystem (full-directory controller + external memories)
    // Controller metadata port (drives mem2048x3 when reset generator is idle).
    logic        ctrl_md_enable_n, ctrl_md_we;
    logic [10:0] ctrl_md_addr;
    logic [2:0]  ctrl_md_wdata;

    // Controller main-memory port.
    logic        ctrl_mm_valid, ctrl_mm_instr;
    logic [31:0] ctrl_mm_addr, ctrl_mm_wdata;
    logic [3:0]  ctrl_mm_wstrb;

    // Reset generator control + memory ports.
    logic        rg_start, rg_busy, rg_ready;
    logic        rg_md_enable_n, rg_md_we, rg_md_clear;
    logic [10:0] rg_md_addr;
    logic [2:0]  rg_md_wdata;
    logic        rg_mm_valid, rg_mm_instr;
    logic [31:0] rg_mm_addr, rg_mm_wdata;
    logic [3:0]  rg_mm_wstrb;

    // Muxed metadata memory (mem2048x3) port.
    logic        md_enable_n, md_we, md_clear;
    logic [10:0] md_addr;
    logic [2:0]  md_wdata, md_rdata;

    // Muxed main memory (mem_ctrl_2048x32) port.
    logic        mm_valid, mm_instr, mm_ready;
    logic [31:0] mm_addr, mm_wdata, mm_rdata;
    logic [3:0]  mm_wstrb;


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
    logic        boot_pass_en;
    logic        core_mem_select;
    logic        core_rst_n;

    logic [DFT_CHAINS-1:0] scan_in;
    logic [DFT_CHAINS-1:0] scan_out;

	//SERDES
    logic [SER_PINS-1:0] c0_serial_tx;
    logic [SER_PINS-1:0] c1_serial_tx;
    logic [SER_PINS-1:0] c0_serial_rx;
    logic [SER_PINS-1:0] c1_serial_rx;
    logic                c0_req_tx;
    logic                c1_req_tx;


    logic [NUM_BIDIR_PADS-1:0] bidir_out_int;
    logic [NUM_BIDIR_PADS-1:0] bidir_oe_int;

    wire whoami_pulse;
    wire whoami_ready;

    assign whoami_ready = c0_tser_ready && c1_tser_ready;

    assign boot_pass_en = bidir_in[BOOT_PASS_EN_ID];
    assign core_mem_select = debug_mode_i[3] | boot_done;
    assign core_rst_n = rst_n & (debug_mode_i[3] | cores_en);
    assign scan_in = bidir_in[DFT_START_ID +: DFT_CHAINS];

    assign c0_serial_rx = bidir_in[C0_SERIAL_I_START_ID +: SER_PINS];
    assign c1_serial_rx = bidir_in[C1_SERIAL_I_START_ID +: SER_PINS];

    always_comb begin
        bidir_out_int = '0;
        bidir_oe_int = '0;

        bidir_out_int[FLASH_CSB_ID] = boot_flash_csb;
        bidir_oe_int[FLASH_CSB_ID] = !boot_pass_en;

        bidir_out_int[SPI_MOSI_ID] = boot_spi_mosi;
        bidir_oe_int[SPI_MOSI_ID] = !boot_pass_en;

        bidir_out_int[SPI_SCLK_ID] = boot_spi_sck;
        bidir_oe_int[SPI_SCLK_ID] = !boot_pass_en;

        // The lower half of the DFT range remains inputs. The upper half is
        // driven by the four parallel scan-chain outputs.
        bidir_out_int[DFT_START_ID + DFT_CHAINS +: DFT_CHAINS] = scan_out;
        bidir_oe_int[DFT_START_ID + DFT_CHAINS +: DFT_CHAINS] = {DFT_CHAINS{debug_mode_i[0]}};

        bidir_out_int[C0_REQ_O_ID] = c0_req_tx;
        bidir_oe_int[C0_REQ_O_ID] = 1'b1;

        bidir_out_int[C0_SERIAL_O_START_ID +: SER_PINS] = c0_serial_tx;
        bidir_oe_int[C0_SERIAL_O_START_ID +: SER_PINS] = {SER_PINS{1'b1}};

        bidir_out_int[C0_BOOT_DONE] = boot_done;
        bidir_oe_int[C0_BOOT_DONE] = 1'b1;

        bidir_out_int[C0_DEBUG_MODE_ID] = debug_mode_i[1];
        bidir_oe_int[C0_DEBUG_MODE_ID] = 1'b1;

        bidir_out_int[C0_RST_N_ID] = rst_n;
        bidir_oe_int[C0_RST_N_ID] = 1'b1;

        bidir_out_int[C0_TRAP_O_ID] = bidir_in[C0_TRAP_I_ID];
        bidir_oe_int[C0_TRAP_O_ID] = 1'b1;

        bidir_out_int[C1_REQ_O_ID] = c1_req_tx;
        bidir_oe_int[C1_REQ_O_ID] = 1'b1;

        bidir_out_int[C1_SERIAL_O_START_ID +: SER_PINS] = c1_serial_tx;
        bidir_oe_int[C1_SERIAL_O_START_ID +: SER_PINS] = {SER_PINS{1'b1}};

        bidir_out_int[C1_BOOT_DONE] = boot_done;
        bidir_oe_int[C1_BOOT_DONE] = 1'b1;

        bidir_out_int[C1_DEBUG_MODE_ID] = debug_mode_i[2];
        bidir_oe_int[C1_DEBUG_MODE_ID] = 1'b1;

        bidir_out_int[C1_RST_N_ID] = rst_n;
        bidir_oe_int[C1_RST_N_ID] = 1'b1;

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
        .whoami_pulse_o (whoami_pulse),
        .mem_clear_start_o (rg_start),
        .mem_clear_done_i  (rg_ready),
        .scan_en_i      (debug_mode_i[0]),
        .scan_in_i      (scan_in[0]),
        .scan_out_o     (scan_out[0])
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

	.req_i_branches     (c0_req_i_branches),
  	.serial_i           (c0_serial_rx),
  	.req_o              (c0_req_tx),
	.serial_o           (c0_serial_tx),
    .scan_en_i          (debug_mode_i[1]),
    .scan_in_i          (scan_in[1]),
    .scan_out_o         (scan_out[1])
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

	.req_i_branches     (c1_req_i_branches),
  	.serial_i           (c1_serial_rx),
  	.req_o              (c1_req_tx),
	.serial_o           (c1_serial_tx),
    .scan_en_i          (debug_mode_i[2]),
    .scan_in_i          (scan_in[2]),
    .scan_out_o         (scan_out[2])
    );

    // Reset generator start (rg_start) and completion (rg_ready) form a clear
    // handshake with housekeeping: housekeeping asserts the start out of reset
    // and holds the boot FSM/SPI in reset until rg_ready, so the boot process
    // cannot begin until both memories are fully cleared.

    // ---- Memory port muxing (all outside the controller) -------------------
    // Directory metadata: the reset generator owns the mem2048x3 port (in clear
    // mode) while it is sweeping; otherwise the controller does.
    // Main memory: reset generator > boot loader > controller, selected by the
    // boot stage. rg_busy wins during the clear sweep; after it, core_mem_select
    // (debug_mode_i[3] | boot_done) hands the bus from the boot loader to the
    // controller. The reset generator (one word/cycle) clears each address well
    // ahead of the SPI-paced boot loader reaching it.
    always_comb begin
        if (rg_busy) begin
            md_enable_n = rg_md_enable_n;
            md_we       = rg_md_we;
            md_clear    = rg_md_clear;
            md_addr     = rg_md_addr;
            md_wdata    = rg_md_wdata;
        end else begin
            md_enable_n = ctrl_md_enable_n;
            md_we       = ctrl_md_we;
            md_clear    = 1'b0;
            md_addr     = ctrl_md_addr;
            md_wdata    = ctrl_md_wdata;
        end

        if (rg_busy) begin
            mm_valid = rg_mm_valid;
            mm_instr = rg_mm_instr;
            mm_addr  = rg_mm_addr;
            mm_wstrb = rg_mm_wstrb;
            mm_wdata = rg_mm_wdata;
        end else if (core_mem_select) begin
            mm_valid = ctrl_mm_valid;
            mm_instr = ctrl_mm_instr;
            mm_addr  = ctrl_mm_addr;
            mm_wstrb = ctrl_mm_wstrb;
            mm_wdata = ctrl_mm_wdata;
        end else begin
            mm_valid = boot_mem_valid;
            mm_instr = boot_mem_instr;
            mm_addr  = boot_mem_addr;
            mm_wstrb = boot_mem_wstrb;
            mm_wdata = boot_mem_wdata;
        end
    end

    directory_controller_full i_directory_controller (
        .clk_i                (clk),
        .rst_ni               (core_rst_n),

        .c0_bus_valid_i       (c0_bus_valid),
        .c0_bus_addr_i        (c0_bus_addr),
        .c0_bus_wdata_i       (c0_bus_wdata),
        .c0_bus_cache_cmd_i   (c0_bus_cache_cmd),
        .c0_bus_ready_o       (c0_bus_ready),

        .c0_snoop_valid_i     (c0_snoop_valid),
        .c0_snoop_data_i      (c0_snoop_data),
        .c0_snoop_cache_cmd_i (c0_snoop_cache_cmd),
        .c0_snoop_ready_o     (c0_snoop_ready),

        .c0_dir_valid_o       (c0_dir_valid),
        .c0_dir_data_o        (c0_dir_data),
        .c0_dir_addr_o        (c0_dir_addr),
        .c0_dir_cmd_o         (c0_dir_cmd),
        .c0_dir_ready_i       (c0_tser_ready),

        .c1_bus_valid_i       (c1_bus_valid),
        .c1_bus_addr_i        (c1_bus_addr),
        .c1_bus_wdata_i       (c1_bus_wdata),
        .c1_bus_cache_cmd_i   (c1_bus_cache_cmd),
        .c1_bus_ready_o       (c1_bus_ready),

        .c1_snoop_valid_i     (c1_snoop_valid),
        .c1_snoop_data_i      (c1_snoop_data),
        .c1_snoop_cache_cmd_i (c1_snoop_cache_cmd),
        .c1_snoop_ready_o     (c1_snoop_ready),

        .c1_dir_valid_o       (c1_dir_valid),
        .c1_dir_data_o        (c1_dir_data),
        .c1_dir_addr_o        (c1_dir_addr),
        .c1_dir_cmd_o         (c1_dir_cmd),
        .c1_dir_ready_i       (c1_tser_ready),

        // Directory metadata memory port (muxed to mem2048x3).
        .md_enable_n_o        (ctrl_md_enable_n),
        .md_we_o              (ctrl_md_we),
        .md_addr_o            (ctrl_md_addr),
        .md_wdata_o           (ctrl_md_wdata),
        .md_rdata_i           (md_rdata),

        // Main memory port (muxed to mem_ctrl_2048x32).
        .mm_valid_o           (ctrl_mm_valid),
        .mm_instr_o           (ctrl_mm_instr),
        .mm_addr_o            (ctrl_mm_addr),
        .mm_wstrb_o           (ctrl_mm_wstrb),
        .mm_wdata_o           (ctrl_mm_wdata),
        .mm_rdata_i           (mm_rdata),
        .mm_ready_i           (mm_ready)
    );

    memory_reset_generator i_memory_reset_generator (
        .clk_i         (clk),
        .rst_ni        (rst_n),
        .start_i       (rg_start),
        .busy_o        (rg_busy),
        .ready_o       (rg_ready),

        .md_enable_n_o (rg_md_enable_n),
        .md_we_o       (rg_md_we),
        .md_clear_o    (rg_md_clear),
        .md_addr_o     (rg_md_addr),
        .md_wdata_o    (rg_md_wdata),

        .mm_valid_o    (rg_mm_valid),
        .mm_instr_o    (rg_mm_instr),
        .mm_addr_o     (rg_mm_addr),
        .mm_wstrb_o    (rg_mm_wstrb),
        .mm_wdata_o    (rg_mm_wdata),
        .mm_ready_i    (mm_ready)
    );

    mem2048x3 i_dir_metadata (
        .clk_i      (clk),
        .enable_n_i (md_enable_n),
        .we_i       (md_we),
        .clear_i    (md_clear),
        .addr_i     (md_addr),
        .wdata_i    (md_wdata),
        .rdata_o    (md_rdata)
        `ifdef USE_POWER_PINS
          ,.VDD     (VDD)
          ,.VSS     (VSS)
        `endif
    );

    mem_ctrl_2048x32 i_main_memory (
        .clk_i       (clk),
        .rst_ni      (rst_n),
        .mem_valid_i (mm_valid),
        .mem_instr_i (mm_instr),
        .mem_addr_i  (mm_addr),
        .mem_wdata_i (mm_wdata),
        .mem_wstrb_i (mm_wstrb),
        .mem_rdata_o (mm_rdata),
        .mem_ready_o (mm_ready)
        `ifdef USE_POWER_PINS
          ,.VDD      (VDD)
          ,.VSS      (VSS)
        `endif
    );

    // Scan/DFT re-stitch for the new directory subsystem is deferred; bypass
    // its scan-chain slot for now so the chain stays continuous.
    assign scan_out[3] = scan_in[3];

    logic _unused;
    assign _unused = &{bidir_in, c0_reset_done, c1_reset_done};

endmodule

`default_nettype wire
