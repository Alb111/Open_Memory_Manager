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
    // assign input_pu = '0;
    // assign input_pd = '0;

    // // Set the bidir as output
    // assign bidir_oe = '1;
    // assign bidir_cs = '0;
    // assign bidir_sl = '0;
    // assign bidir_ie = ~bidir_oe;
    // assign bidir_pu = '0;
    // assign bidir_pd = '0;
    
    // logic _unused;
    // assign _unused = &bidir_in;

    logic [NUM_INPUT_PADS-1:0] input_pu_r, input_pd_r;
    logic [NUM_BIDIR_PADS-1:0] bidir_out_r, bidir_oe_r, bidir_cs_r;
    logic [NUM_BIDIR_PADS-1:0] bidir_sl_r, bidir_ie_r, bidir_pu_r, bidir_pd_r;

    assign input_pu  = input_pu_r;
    assign input_pd  = input_pd_r;
    assign bidir_out = bidir_out_r;
    assign bidir_oe  = bidir_oe_r;
    assign bidir_cs  = bidir_cs_r;
    assign bidir_sl  = bidir_sl_r;
    assign bidir_ie  = bidir_ie_r;
    assign bidir_pu  = bidir_pu_r;
    assign bidir_pd  = bidir_pd_r;

    // =========================================================================
    // pad index definitions
    // update when we finalize pins
    localparam PAD_PASS_THRU_EN = 0;   // input_in[0]  — pass_thru_en from PCB
    localparam PAD_MISO = 1;   // input_in[1]  — flash MISO (always input)
 
    localparam PAD_SCK = 8;   // bidir[8]  — flash SCK
    localparam PAD_MOSI = 9;   // bidir[9]  — flash MOSI
    localparam PAD_CSB = 10;  // bidir[10] — flash CSB


    // =========================================================================
    // boot controller signals
    wire pass_thru_en;
    wire boot_sck;
    wire boot_mosi;
    wire boot_miso;
    wire boot_csb;
    wire boot_mem_valid;
    wire [31:0] boot_mem_addr;
    wire [31:0] boot_mem_wdata;
    wire [3:0] boot_mem_wstrb;
    wire boot_mem_instr;
    wire boot_done;
    wire cores_en;
 
    assign pass_thru_en = input_in[PAD_PASS_THRU_EN];
    assign boot_miso = input_in[PAD_MISO];

    // =========================================================================
    // housekeeping_top instantiation
    housekeeping_top #(
        .BOOT_SIZE      (512),
        .SRAM_BASE_ADDR (32'h0000_0000)
    ) i_housekeeping (
        .clk_i          (clk),
        .reset_ni       (rst_n),
        .pass_thru_en_i (pass_thru_en),
        .spi_sck_o      (boot_sck),
        .spi_mosi_o     (boot_mosi),
        .spi_miso_i     (boot_miso),
        .flash_csb_o    (boot_csb),
        .mem_valid_o    (boot_mem_valid),
        .mem_addr_o     (boot_mem_addr),
        .mem_wdata_o    (boot_mem_wdata),
        .mem_wstrb_o    (boot_mem_wstrb),
        .mem_instr_o    (boot_mem_instr),
        .cores_en_o     (cores_en),
        .boot_done_o    (boot_done)
    );


    // =========================================================================
    // cpu reset gating
    // connect cpu_resetn to picorv32 resetn ports once instantiated
    wire cpu_resetn;
    assign cpu_resetn = rst_n && cores_en;



    // =========================================================================
    // boot mux — memory controller bus arbitration
    // during boot (boot_done=0): boot controller owns memory bus.
    // after boot (boot_done=1): CPU/cache path owns memory bus.
    // cpu_mem_* wires left undriven
    wire cpu_mem_valid;
    wire [31:0] cpu_mem_addr;
    wire [31:0] cpu_mem_wdata;
    wire [3:0] cpu_mem_wstrb;
    wire cpu_mem_instr;
    wire [31:0] mem_rdata;
    wire mem_ready;
 
    wire muxed_mem_valid;
    wire [31:0] muxed_mem_addr;
    wire [31:0] muxed_mem_wdata;
    wire [3:0] muxed_mem_wstrb;
    wire muxed_mem_instr;
 
    assign muxed_mem_valid = boot_done ? cpu_mem_valid : boot_mem_valid;
    assign muxed_mem_addr = boot_done ? cpu_mem_addr : boot_mem_addr;
    assign muxed_mem_wdata = boot_done ? cpu_mem_wdata : boot_mem_wdata;
    assign muxed_mem_wstrb = boot_done ? cpu_mem_wstrb : boot_mem_wstrb;
    assign muxed_mem_instr = boot_done ? cpu_mem_instr : boot_mem_instr;

    // Instantiate mmio module
    mmio
    i_mmio (
        .clk_i      (clk),
        .rst_ni     (rst_n),
        .addr_i     (),
        .wr_data_i  (),
        .wr_en_i    (),
        .rd_data_o  (),
        .gpio_pins_o(),
        .gpio_pins_i(),
        .gpio_dir_o ()
    );

    // Instantiate wrr_arbiter module
    wrr_arbiter #(
        .NUM_REQ   	(),
        .WEIGHT_W  	()
    ) i_wrr_arbiter (
        .clk_i      (clk),
        .rst_ni     (rst_n),
        .req_i      (),
        .grant_o   	(),
        .req_o     	()
    );

    // Instantiate directory_interface module
    directory_interface #(
        .NUM_TPINS  (),
        .NUM_RPINS  ()
    ) i_directory_interface (
        .clk_i          (clk),
        .rst_ni         (rst_n),
        .bus_valid_o    (),
        .bus_addr_o     (),
        .bus_wdata_o    (),
        .bus_cache_cmd_o(),
        .bus_ready_i    (),
        .snoop_valid_o  (),
        .snoop_data_o   (),
        .snoop_cache_cmd_o(),
        .snoop_ready_i  (),
        .dir_valid_i    (),
        .dir_data_i     (),
        .dir_addr_i     (),
        .dir_cmd_i      (),
        .dir_ready_o    (),
        .rbusy_o        (),
        .send_WhoAmI_i  (),
        .cpu_id_i       (),
        .reset_done_o   (),
        .req_i          (),
        .serial_i       (),
        .req_o          (),
        .serial_o       ()
    );

    // Instantiate tserializer module
    tserializer #(
        .NUM_PINS   (),
        .MAX_MSG_LEN(),
        .MSG_LEN_0 	(),
        .MSG_LEN_1 	(),
        .MSG_LEN_2 	(),
        .MSG_LEN_3 	()
    ) i_tserializer (
        .clk_i     	(clk),
        .rst_ni    	(rst_n),
        .valid_i  	(),
        .data_in  	(),
        .msg_type	(),
        .ready_o 	(),
        .req_o   	(),
        .serial_o	()
    );

    // Instantiate rserializer module
    rserializer #(
        .NUM_PINS   (),
        .MAX_MSG_LEN()
    ) i_rserializer (
        .clk_i      (clk),
        .rst_ni     (rst_n),
        .serial_i  	(),
        .req_i     	(),
        .valid_o   	(),
        .data_o    	(),
        .ready_i   	()
    );

    // Instantiate mem_ctrl_2048x32 module
    (* keep *) mem_ctrl_2048x32
    i_mem_ctrl_2048x32 (
        .clk_i        	(clk),
        .rst_ni       	(rst_n),
        .mem_valid_i 	(muxed_mem_valid),
        .mem_instr_i 	(muxed_mem_instr),
        .mem_addr_i  	(muxed_mem_addr),
        .mem_wdata_i 	(muxed_mem_wdata),
        .mem_wstrb_i 	(muxed_mem_wstrb),
        .mem_rdata_o 	(mem_rdata),
        .mem_ready_o 	(mem_ready)
    );

    //assign bidir_out = '0;

    // =========================================================================
    // pad ring assignments 
    // input pads: no pull-up or pull-down on any pin
    always_comb begin
        input_pu_r = '0;
        input_pd_r = '0;
    end
 
    // bidir pad defaults: all driven low, output enabled, no pull
    // induv pins override these below
    always_comb begin
        bidir_out_r = '0;
        bidir_oe_r = '1;   // default all bidir to output
        bidir_cs_r = '0;
        bidir_sl_r = '0;
        bidir_pu_r = '0;
        bidir_pd_r = '0;
 
        // input enable is inverse of output enable
        bidir_ie_r = ~bidir_oe_r;
 
        // flash SPI pins
        // drive SCK, MOSI, CSB from boot controller
        // tri-state all three when pass_thru_en=1 so programmer can drive them
        bidir_out_r[PAD_SCK] = boot_sck;
        bidir_out_r[PAD_MOSI] = boot_mosi;
        bidir_out_r[PAD_CSB] = boot_csb;
 
        bidir_oe_r[PAD_SCK] = ~pass_thru_en;
        bidir_oe_r[PAD_MOSI] = ~pass_thru_en;
        bidir_oe_r[PAD_CSB] = ~pass_thru_en;
 
        // input enable follows output enable inversion for flash pins
        bidir_ie_r[PAD_SCK] = pass_thru_en;
        bidir_ie_r[PAD_MOSI] = pass_thru_en;
        bidir_ie_r[PAD_CSB] = pass_thru_en;
    end
 
    // =========================================================================
    // suppress unused signal warnings
    // remove as connections get filled
    logic _unused;
    assign _unused = &{bidir_in, analog, mem_rdata, mem_ready, cpu_resetn,
                       cpu_mem_valid, cpu_mem_addr, cpu_mem_wdata,
                       cpu_mem_wstrb, cpu_mem_instr};
 

endmodule

`default_nettype wire
