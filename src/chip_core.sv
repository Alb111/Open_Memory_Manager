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

    assign input_pu = '0;
    assign input_pd = '0;

    assign bidir_cs = '0;
    assign bidir_sl = '0;
    assign bidir_ie = ~bidir_oe;
    assign bidir_pu = '0;
    assign bidir_pd = '0;

    logic [31:0] mmio_rd_data;
    logic [7:0]  mmio_gpio_pins_o;
    logic [7:0]  mmio_gpio_pins_i;
    logic [7:0]  mmio_gpio_dir_o;

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
    logic        dir_mem_instr;
    logic [31:0] dir_mem_addr;
    logic [31:0] dir_mem_wdata;
    logic [3:0]  dir_mem_wstrb;
    logic [31:0] dir_mem_rdata;
    logic        dir_mem_ready;

    logic [0:0]  mem_valid_i;
    logic [0:0]  mem_instr_i;
    logic [0:0]  mem_ready_o;

    logic        sp_mem_ready;
    logic [31:0] sp_mem_rdata;
    logic        sp_pass_mem_valid;
    logic [31:0] sp_pass_mem_addr;
    logic [31:0] sp_pass_mem_wdata;
    logic [3:0]  sp_pass_mem_wstrb;
    logic [31:0] sp_flush_addr;
    logic        sp_flush_valid;

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

    always_comb begin
        mmio_gpio_pins_i = '0;
        for (int i = 0; i < 8; i++) begin
            if (i < NUM_BIDIR_PADS) begin
                mmio_gpio_pins_i[i] = bidir_in[i];
            end
        end
    end
    assign arb_req = {c1_bus_valid, c0_bus_valid};
    assign c0_serial_rx = c1_serial_tx;
    assign c1_serial_rx = c0_serial_tx;
    assign c0_req_rx = c1_req_tx;
    assign c1_req_rx = c0_req_tx;

    assign mem_valid_i = dir_mem_valid;
    assign mem_instr_i = dir_mem_instr;
    assign dir_mem_ready = mem_ready_o[0];

    always_comb begin
        bidir_out_int = '0;
        bidir_oe_int = '0;
        for (int i = 0; i < NUM_BIDIR_PADS; i++) begin
            if (i < 8) begin
                bidir_out_int[i] = mmio_gpio_pins_o[i];
                bidir_oe_int[i] = mmio_gpio_dir_o[i];
            end
        end
    end

    assign bidir_out = bidir_out_int;
    assign bidir_oe = bidir_oe_int;

    mmio i_mmio (
        .clk_i      (clk),
        .rst_ni     (rst_n),
        .addr_i     (32'h8000_0010),
        .wr_data_i  (32'h0),
        .wr_en_i    (1'b0),
        .rd_data_o  (mmio_rd_data),
        .gpio_pins_o(mmio_gpio_pins_o),
        .gpio_pins_i(mmio_gpio_pins_i),
        .gpio_dir_o (mmio_gpio_dir_o)
    );

    sp_addr_handler i_sp_addr_handler (
        .clk_i          (clk),
        .rst_ni         (rst_n),
        .mem_valid      (1'b0),
        .mem_ready      (sp_mem_ready),
        .mem_addr       (32'h0),
        .mem_wdata      (32'h0),
        .mem_wstrb      (4'h0),
        .mem_rdata      (sp_mem_rdata),
        .pass_mem_valid (sp_pass_mem_valid),
        .pass_mem_ready (1'b1),
        .pass_mem_addr  (sp_pass_mem_addr),
        .pass_mem_wdata (sp_pass_mem_wdata),
        .pass_mem_wstrb (sp_pass_mem_wstrb),
        .pass_mem_rdata (32'h0),
        .flush_ready_i  (1'b1),
        .flush_addr_o   (sp_flush_addr),
        .flush_valid_o  (sp_flush_valid),
        .gpio_pins_o    (),
        .gpio_pins_i    (8'h00),
        .gpio_dir_o     (),
        .cpu_id_i       (8'h00)
    );

    wrr_arbiter #(
        .NUM_REQ    (2),
        .WEIGHT_W   (3),
        .WEIGHTS    ({3'd1, 3'd1})
    ) i_wrr_arbiter (
        .clk_i      (clk),
        .rst_ni     (rst_n),
        .req_i      (arb_req),
        .grant_o    (arb_grant),
        .req_o      (arb_req_passthrough)
    );

    directory_interface #(
        .NUM_TPINS  (SER_PINS),
        .NUM_RPINS  (SER_PINS)
    ) i_directory_interface_0 (
        .clk_i          (clk),
        .rst_ni         (rst_n),
        .bus_valid_o    (c0_bus_valid),
        .bus_addr_o     (c0_bus_addr),
        .bus_wdata_o    (c0_bus_wdata),
        .bus_cache_cmd_o(c0_bus_cache_cmd),
        .bus_ready_i    (c0_bus_ready),
        .snoop_valid_o  (c0_snoop_valid),
        .snoop_data_o   (c0_snoop_data),
        .snoop_cache_cmd_o(c0_snoop_cache_cmd),
        .snoop_ready_i  (c0_snoop_ready),
        .dir_valid_i    (c0_dir_valid),
        .dir_data_i     (c0_dir_data),
        .dir_addr_i     (c0_dir_addr),
        .dir_cmd_i      (c0_dir_cmd),
        .dir_ready_o    (c0_dir_ready),
        .rbusy_o        (),
        .send_WhoAmI_i  (1'b0),
        .cpu_id_i       (8'h00),
        .reset_done_o   (c0_reset_done),
        .req_i          (c0_req_rx),
        .serial_i       (c0_serial_rx),
        .req_o          (c0_req_tx),
        .serial_o       (c0_serial_tx)
    );

    directory_interface #(
        .NUM_TPINS  (SER_PINS),
        .NUM_RPINS  (SER_PINS)
    ) i_directory_interface_1 (
        .clk_i          (clk),
        .rst_ni         (rst_n),
        .bus_valid_o    (c1_bus_valid),
        .bus_addr_o     (c1_bus_addr),
        .bus_wdata_o    (c1_bus_wdata),
        .bus_cache_cmd_o(c1_bus_cache_cmd),
        .bus_ready_i    (c1_bus_ready),
        .snoop_valid_o  (c1_snoop_valid),
        .snoop_data_o   (c1_snoop_data),
        .snoop_cache_cmd_o(c1_snoop_cache_cmd),
        .snoop_ready_i  (c1_snoop_ready),
        .dir_valid_i    (c1_dir_valid),
        .dir_data_i     (c1_dir_data),
        .dir_addr_i     (c1_dir_addr),
        .dir_cmd_i      (c1_dir_cmd),
        .dir_ready_o    (c1_dir_ready),
        .rbusy_o        (),
        .send_WhoAmI_i  (1'b0),
        .cpu_id_i       (8'h01),
        .reset_done_o   (c1_reset_done),
        .req_i          (c1_req_rx),
        .serial_i       (c1_serial_rx),
        .req_o          (c1_req_tx),
        .serial_o       (c1_serial_tx)
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
        .rst_ni     (rst_n),
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
        .rst_ni     (rst_n),
        .serial_i   (ts_serial),
        .req_i      (ts_req),
        .valid_o    (rs_valid),
        .data_o     (rs_data),
        .ready_i    (1'b1)
    );

    directory_controller i_directory_controller (
        .clk_i             (clk),
        .rst_ni            (rst_n),
        .c0_bus_valid_i    (c0_bus_valid),
        .c0_bus_addr_i     (c0_bus_addr),
        .c0_bus_wdata_i    (c0_bus_wdata),
        .c0_bus_cache_cmd_i(c0_bus_cache_cmd),
        .c0_bus_ready_o    (c0_bus_ready),
        .c0_snoop_valid_i  (c0_snoop_valid),
        .c0_snoop_data_i   (c0_snoop_data),
        .c0_snoop_cache_cmd_i(c0_snoop_cache_cmd),
        .c0_snoop_ready_o  (c0_snoop_ready),
        .c0_dir_valid_o    (c0_dir_valid),
        .c0_dir_data_o     (c0_dir_data),
        .c0_dir_addr_o     (c0_dir_addr),
        .c0_dir_cmd_o      (c0_dir_cmd),
        .c0_dir_ready_i    (c0_dir_ready),
        .c1_bus_valid_i    (c1_bus_valid),
        .c1_bus_addr_i     (c1_bus_addr),
        .c1_bus_wdata_i    (c1_bus_wdata),
        .c1_bus_cache_cmd_i(c1_bus_cache_cmd),
        .c1_bus_ready_o    (c1_bus_ready),
        .c1_snoop_valid_i  (c1_snoop_valid),
        .c1_snoop_data_i   (c1_snoop_data),
        .c1_snoop_cache_cmd_i(c1_snoop_cache_cmd),
        .c1_snoop_ready_o  (c1_snoop_ready),
        .c1_dir_valid_o    (c1_dir_valid),
        .c1_dir_data_o     (c1_dir_data),
        .c1_dir_addr_o     (c1_dir_addr),
        .c1_dir_cmd_o      (c1_dir_cmd),
        .c1_dir_ready_i    (c1_dir_ready),
        .dir_mem_valid_o   (dir_mem_valid),
        .dir_mem_instr_o   (dir_mem_instr),
        .dir_mem_addr_o    (dir_mem_addr),
        .dir_mem_wdata_o   (dir_mem_wdata),
        .dir_mem_wstrb_o   (dir_mem_wstrb),
        .dir_mem_rdata_i   (dir_mem_rdata),
        .dir_mem_ready_i   (dir_mem_ready)
    );

    mem_ctrl_2048x32 i_mem_ctrl_2048x32 (
        .clk_i        (clk),
        .rst_ni       (rst_n),
        .mem_valid_i  (mem_valid_i),
        .mem_instr_i  (mem_instr_i),
        .mem_addr_i   (dir_mem_addr),
        .mem_wdata_i  (dir_mem_wdata),
        .mem_wstrb_i  (dir_mem_wstrb),
        .mem_rdata_o  (dir_mem_rdata),
        .mem_ready_o  (mem_ready_o)
        `ifdef USE_POWER_PINS
 		,.VDD(VDD)
 		,.VSS(VSS)
 		`endif
    );

    logic _unused;
    assign _unused = &{input_in, analog, bidir_in, mmio_rd_data[0], arb_grant, arb_req_passthrough,
                       sp_mem_ready, sp_mem_rdata[0], sp_pass_mem_valid, sp_pass_mem_addr[0],
                       sp_pass_mem_wdata[0], sp_pass_mem_wstrb[0], sp_flush_addr[0], sp_flush_valid,
                       ts_ready, rs_valid, rs_data[0], c0_reset_done, c1_reset_done};

endmodule

`default_nettype wire
