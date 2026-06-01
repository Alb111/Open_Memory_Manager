// SPDX-FileCopyrightText: © 2025 XXX Authors
// SPDX-License-Identifier: Apache-2.0

`default_nettype none

`timescale 1ns/1ps

module chip_core #(
    parameter NUM_INPUT_PADS,
    parameter NUM_BIDIR_PADS,
    parameter NUM_ANALOG_PADS
    )(

    `ifdef USE_POWER_PINS
    inout  wire VDD,
    inout  wire VSS,
    `endif

    input  wire clk,
    input  wire rst_n,

    input  wire [NUM_INPUT_PADS-1:0] input_in,
    output wire [NUM_INPUT_PADS-1:0] input_pu,
    output wire [NUM_INPUT_PADS-1:0] input_pd,

    input  wire [NUM_BIDIR_PADS-1:0] bidir_in,
    output wire [NUM_BIDIR_PADS-1:0] bidir_out,
    output wire [NUM_BIDIR_PADS-1:0] bidir_oe,
    output wire [NUM_BIDIR_PADS-1:0] bidir_cs,
    output wire [NUM_BIDIR_PADS-1:0] bidir_sl,
    output wire [NUM_BIDIR_PADS-1:0] bidir_ie,
    output wire [NUM_BIDIR_PADS-1:0] bidir_pu,
    output wire [NUM_BIDIR_PADS-1:0] bidir_pd,

    inout  wire [NUM_ANALOG_PADS-1:0] analog
);

    localparam int SER_PINS = 9;
    localparam int PIN_BOOT_MISO = 0;
    localparam int PIN_DEBUG_MODE = 1;
    localparam int PIN_DFT_IN = 2;
    localparam int PIN_TRAP_LED = 0;
    localparam int PIN_BOOT_SCLK = 1;
    localparam int PIN_BOOT_MOSI = 2;
    localparam int PIN_BOOT_CS = 3;
    localparam int PIN_DFT_OUT = 4;

    assign input_pu = '0;
    assign input_pd = '0;

    assign bidir_cs = '0;
    assign bidir_sl = '0;
    assign bidir_ie = ~bidir_oe;
    assign bidir_pu = '0;
    assign bidir_pd = '0;

    logic [1:0] arb_req;
    logic [1:0] arb_grant;
    logic [1:0] arb_req_passthrough;

    logic        c0_bus_valid;
    logic [31:0] c0_bus_addr;
    logic [31:0] c0_bus_wdata;
    logic [4:0]  c0_bus_cache_cmd;
    logic        c0_bus_ready;

    logic        c0_snoop_valid;
    logic [31:0] c0_snoop_data;
    logic [2:0]  c0_snoop_cache_cmd;
    logic        c0_snoop_ready;

    logic        c0_dir_valid;
    logic [31:0] c0_dir_data;
    logic [31:0] c0_dir_addr;
    logic [5:0]  c0_dir_cmd;
    logic        c0_dir_ready;
    logic        c0_reset_done;

    logic        c1_bus_valid;
    logic [31:0] c1_bus_addr;
    logic [31:0] c1_bus_wdata;
    logic [4:0]  c1_bus_cache_cmd;
    logic        c1_bus_ready;

    logic        c1_snoop_valid;
    logic [31:0] c1_snoop_data;
    logic [2:0]  c1_snoop_cache_cmd;
    logic        c1_snoop_ready;

    logic        c1_dir_valid;
    logic [31:0] c1_dir_data;
    logic [31:0] c1_dir_addr;
    logic [5:0]  c1_dir_cmd;
    logic        c1_dir_ready;
    logic        c1_reset_done;

    logic        dir_mem_valid;
    logic        dir_mem_ready;
    logic [31:0] dir_mem_addr;
    logic [3:0]  dir_mem_wstrb;

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
    
    logic [0:0]  mem_valid_i;
    logic [0:0]  mem_instr_i;
    logic [0:0]  mem_ready_o;
    logic [31:0] mem_addr_i;
    logic [31:0] mem_wdata_i;
    logic [3:0]  mem_wstrb_i;

    logic [0:0]  dir_main_mem_valid;
    logic [0:0]  dir_main_mem_instr;
    logic [31:0] dir_main_mem_addr;
    logic [31:0] dir_main_mem_wdata;
    logic [3:0]  dir_main_mem_wstrb;
    logic [31:0] dir_main_mem_rdata;
    logic [0:0]  dir_main_mem_ready;

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

    logic        ts_ready;
    logic        ts_req;
    logic [SER_PINS-1:0] ts_serial;
    logic        rs_valid;
    logic [71:0] rs_data;

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

    assign debug_mode = input_in[PIN_DEBUG_MODE];
    assign dft_in = input_in[PIN_DFT_IN];
    assign dft_out = dft_in;
    assign trap_led = 1'b0;
    assign core_mem_select = debug_mode | boot_done;
    assign core_rst_n = rst_n & (debug_mode | cores_en);

    assign arb_req = {c1_bus_valid, c0_bus_valid};
    assign c0_serial_rx = c1_serial_tx;
    assign c1_serial_rx = c0_serial_tx;
    assign c0_req_rx = c1_req_tx;
    assign c1_req_rx = c0_req_tx;
    
    /*
    assign mem_valid_i = core_mem_select ? dir_mem_valid : boot_mem_valid;
    assign mem_instr_i = core_mem_select ? 1'b0 : boot_mem_instr;
    assign mem_addr_i = core_mem_select ? dir_mem_addr : boot_mem_addr;
    assign mem_wdata_i = core_mem_select ? dir_mem_w_data : boot_mem_wdata;
    assign mem_wstrb_i = core_mem_select ? dir_mem_wstrb : boot_mem_wstrb;
    assign dir_mem_ready = core_mem_select ? mem_ready_o[0] : 1'b0;
    */
    
    assign mem_valid_i = core_mem_select ? dir_main_mem_valid : boot_mem_valid;
    assign mem_instr_i = core_mem_select ? dir_main_mem_instr : boot_mem_instr;
    assign mem_addr_i  = core_mem_select ? dir_main_mem_addr  : boot_mem_addr;
    assign mem_wdata_i = core_mem_select ? dir_main_mem_wdata : boot_mem_wdata;
    assign mem_wstrb_i = core_mem_select ? dir_main_mem_wstrb : boot_mem_wstrb;
    assign dir_main_mem_ready = core_mem_select ? mem_ready_o : 1'b0;

    always_comb begin
        bidir_out_int = '0;
        bidir_oe_int = '0;

        bidir_out_int[PIN_TRAP_LED] = trap_led;
        bidir_oe_int[PIN_TRAP_LED] = 1'b1;

        bidir_out_int[PIN_BOOT_SCLK] = boot_spi_sck;
        bidir_oe_int[PIN_BOOT_SCLK] = 1'b1;

        bidir_out_int[PIN_BOOT_MOSI] = boot_spi_mosi;
        bidir_oe_int[PIN_BOOT_MOSI] = 1'b1;

        bidir_out_int[PIN_BOOT_CS] = boot_flash_csb;
        bidir_oe_int[PIN_BOOT_CS] = 1'b1;

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
        .spi_miso_i     (input_in[PIN_BOOT_MISO]),
        .flash_csb_o    (boot_flash_csb),
        .pass_thru_en_i (debug_mode),
        .mem_valid_o    (boot_mem_valid),
        .mem_addr_o     (boot_mem_addr),
        .mem_wdata_o    (boot_mem_wdata),
        .mem_wstrb_o    (boot_mem_wstrb),
        .mem_instr_o    (boot_mem_instr),
        .cores_en_o     (cores_en),
        .boot_done_o    (boot_done)
    );

    //Not sure if arbiter is needed here since its instantiated in directory
    //controller but best to double check
    wrr_arbiter #(
        .NUM_REQ    (2),
        .WEIGHT_W   (3),
        .WEIGHTS    ({3'd1, 3'd1})
    ) i_wrr_arbiter (
        .clk_i      (clk),
        .rst_ni     (core_rst_n),
        .req_i      (arb_req),
        .grant_o    (arb_grant),
        .req_o      (arb_req_passthrough)
    );

    directory_interface #(
  	.NUM_TPINS(SER_PINS),
  	.NUM_RPINS(SER_PINS)
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
  	.dir_ready_o        (c0_dir_ready),

  	.rbusy_o            (),
  	.send_WhoAmI_i      (1'b0),
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
  	.dir_ready_o        (c1_dir_ready),

  	.rbusy_o            (),
  	.send_WhoAmI_i      (1'b0),
  	.cpu_id_i           (8'h01),
  	.reset_done_o       (c1_reset_done),

  	.req_i              (c1_req_rx),
  	.serial_i           (c1_serial_rx),
  	.req_o              (c1_req_tx),
  	.serial_o           (c1_serial_tx)
    );

    tserializer #(
        .NUM_PINS   (SER_PINS),
        .MAX_MSG_LEN(68),
        .MSG_LEN_0  (4),
        .MSG_LEN_1  (12),
        .MSG_LEN_2  (36),
        .MSG_LEN_3  (68)
    ) i_t_serializer (
        .clk_i      (clk),
        .rst_ni     (core_rst_n),
        .valid_i    (1'b0),
        .data_in    (72'h0),
        .msg_type   (2'b00),
        .ready_o    (ts_ready),
        .req_o      (ts_req),
        .serial_o   (ts_serial)
    );

    rserializer #(
        .NUM_PINS   (SER_PINS),
        .MAX_MSG_LEN(68)
    ) i_r_serializer (
        .clk_i      (clk),
        .rst_ni     (core_rst_n),
        .serial_i   (ts_serial),
        .req_i      (ts_req),
        .valid_o    (rs_valid),
        .data_o     (rs_data),
        .ready_i    (1'b1)
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
  	.c0_dir_ready_i         (c0_dir_ready),

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
  	.c1_dir_ready_i         (c1_dir_ready),
	
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

  	//Add these outputs to connect to the main memory
	// Main memory side, set main_mem_instr_o = 1'b0 since no instr
	// fetches are actually needed
  	.main_mem_valid_o  (dir_main_mem_valid),
  	.main_mem_instr_o  (dir_main_mem_instr),
  	.main_mem_addr_o   (dir_main_mem_addr),
  	.main_mem_wdata_o  (dir_main_mem_wdata),
  	.main_mem_wstrb_o  (dir_main_mem_wstrb),
  	.main_mem_rdata_i  (dir_main_mem_rdata),
  	.main_mem_ready_i  (dir_main_mem_ready)
    );
    
    mem_ctrl_2048x32 i_mem_ctrl_2048x32 (
  	.clk_i       (clk),
  	.rst_ni      (rst_n),
  	.mem_valid_i (mem_valid_i),
  	.mem_instr_i (mem_instr_i),
  	.mem_addr_i  (mem_addr_i),
  	.mem_wdata_i (mem_wdata_i),
  	.mem_wstrb_i (mem_wstrb_i),
  	.mem_rdata_o (dir_main_mem_rdata),
  	.mem_ready_o (mem_ready_o)
	`ifdef USE_POWER_PINS
  	,.VDD        (VDD)
  	,.VSS        (VSS)
	`endif
    );

    metadata_sram64x8_array i_metadata_sram64x8_array (
        `ifdef USE_POWER_PINS
        .VDD (VDD),
        .VSS (VSS)
        `endif
    );

    logic _unused;
    assign _unused = &{input_in, analog, bidir_in, arb_grant, arb_req_passthrough,
                       ts_ready, rs_valid, rs_data[0], c0_reset_done, c1_reset_done};

endmodule

`default_nettype wire
