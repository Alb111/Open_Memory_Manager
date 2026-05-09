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
    
    input  wire clk,       // clock
    input  wire rst_n,     // reset (active low)
    
    input  wire [NUM_INPUT_PADS-1:0] input_in,   // Input value
    output wire [NUM_INPUT_PADS-1:0] input_pu,   // Pull-up
    output wire [NUM_INPUT_PADS-1:0] input_pd,   // Pull-down

    input  wire [NUM_BIDIR_PADS-1:0] bidir_in,   // Input value
    output wire [NUM_BIDIR_PADS-1:0] bidir_out,  // Output value
    output wire [NUM_BIDIR_PADS-1:0] bidir_oe,   // Output enable
    output wire [NUM_BIDIR_PADS-1:0] bidir_cs,   // Input type (0=CMOS Buffer, 1=Schmitt Trigger)
    output wire [NUM_BIDIR_PADS-1:0] bidir_sl,   // Slew rate (0=fast, 1=slow)
    output wire [NUM_BIDIR_PADS-1:0] bidir_ie,   // Input enable
    output wire [NUM_BIDIR_PADS-1:0] bidir_pu,   // Pull-up
    output wire [NUM_BIDIR_PADS-1:0] bidir_pd,   // Pull-down

    inout  wire [NUM_ANALOG_PADS-1:0] analog  // Analog
);

    // See here for usage: https://gf180mcu-pdk.readthedocs.io/en/latest/IPs/IO/gf180mcu_fd_io/digital.html
    
    // Disable pull-up and pull-down for input
    assign input_pu = '0;
    assign input_pd = '0;

    // Set the bidir as output
    assign bidir_oe = '1;
    assign bidir_cs = '0;
    assign bidir_sl = '0;
    assign bidir_ie = ~bidir_oe;
    assign bidir_pu = '0;
    assign bidir_pd = '0;
    
    logic _unused;
    assign _unused = &bidir_in;

    // Instantiate mmio module
    mmio i_mmio (
        .clk_i     (),
        .rst_in    (),
        .addr_i   (),
        .wr_data_i(),
        .wr_en_i  (),
        .rd_data_o(),
        .gpio_pins_o(),
        .gpio_pins_i(),
        .gpio_dir_o()
    );

    // Instantiate wrr_arbiter module
    wrr_arbiter #(
        .NUM_REQ   (),
        .WEIGHT_W ()
    ) i_wrr_arbiter (
        .clk_i       (),
        .rst_ni     (),
        .req_i      (),
        .weights_i  (),
        .weight_en_i(),
        .grant_o   (),
        .req_o     ()
    );

    // Instantiate cache_interface module
    cache_interface #(
        .NUM_PINS   (),
        .MAX_MSG_LEN()
    ) i_cache_interface (
        .mem_valid      (),
        .mem_ready     (),
        .mem_addr      (),
        .mem_wdata     (),
        .mem_wstrb     (),
        .mem_rdata     (),
        .cache_cmd     (),
        .directory_cmd(),
        .rst_done     (),
        .cpu_id       (),
        .req_i       (),
        .serial_i    (),
        .req_o       (),
        .serial_o    ()
    );

    // Instantiate directory_interface module
    directory_interface #(
        .NUM_PINS   (),
        .MAX_MSG_LEN()
    ) i_directory_interface (
        .mem_valid      (),
        .mem_ready     (),
        .mem_addr      (),
        .mem_wdata     (),
        .mem_wstrb     (),
        .mem_rdata     (),
        .cache_cmd     (),
        .directory_cmd(),
        .rst_done     (),
        .cpu_id       (),
        .req_i       (),
        .serial_i    (),
        .req_o       (),
        .serial_o    ()
    );

    // Instantiate tserializer module
    tserializer #(
        .NUM_PINS   (),
        .MAX_MSG_LEN(),
        .MSG_LEN_0 (),
        .MSG_LEN_1 (),
        .MSG_LEN_2 (),
        .MSG_LEN_3 ()
    ) i_tserializer (
        .clk_i     (),
        .rst_n    (),
        .valid_i  (),
        .data_in  (),
        .msg_type(),
        .ready_o (),
        .req_o   (),
        .serial_o()
    );

    // Instantiate rserializer module
    rserializer #(
        .NUM_PINS   (),
        .MAX_MSG_LEN()
    ) i_rserializer (
        .clk_i      (),
        .rst_n     (),
        .serial_i  (),
        .req_i     (),
        .valid_o   (),
        .data_o    (),
        .ready_i   ()
    );

    // Instantiate mem_ctrl_512x32 module
    mem_ctrl_512x32 i_mem_ctrl_512x32 (
        .clk_i        (),
        .rst_ni       (),
        .mem_valid_i (),
        .mem_instr_i (),
        .mem_addr_i  (),
        .mem_wdata_i (),
        .mem_wstrb_i (),
        .mem_rdata_o (),
        .mem_ready_o ()
    );

    // Instantiate mem_ctrl_2048x32 module
    mem_ctrl_2048x32 i_mem_ctrl_2048x32 (
        .clk_i        (),
        .rst_ni       (),
        .mem_valid_i (),
        .mem_instr_i (),
        .mem_addr_i  (),
        .mem_wdata_i (),
        .mem_wstrb_i (),
        .mem_rdata_o (),
        .mem_ready_o ()
    );

    assign bidir_out = '0;

endmodule

`default_nettype wire
