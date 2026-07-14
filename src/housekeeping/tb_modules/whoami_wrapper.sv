`timescale 1ns/1ps

module whoami_wrapper #(
    parameter BOOT_SIZE      = 32,    // small boot for fast test
    parameter SRAM_BASE_ADDR = 32'h0000_0000,
    parameter SER_PINS       = 9
)(
    input  logic clk_i,
    input  logic rst_ni,
    input  logic pass_thru_en_i,

    // boot status
    output logic boot_done_o,
    output logic cores_en_o,
    output logic whoami_pulse_o,

    // serial outputs from both directory interfaces
    output logic                  req_o_0,
    output logic [SER_PINS-1:0]   serial_o_0,
    output logic                  req_o_1,
    output logic [SER_PINS-1:0]   serial_o_1
);

    // SPI wires: housekeeping_top <-> flash model
    wire spi_sck;
    wire spi_mosi;
    wire flash_csb;
    wire flash_si;
    wire flash_so;
    assign flash_si = spi_mosi;

    wire wp_tie;
    wire io3_tie;
    assign wp_tie  = 1'b1;
    assign io3_tie = 1'b1;

    // housekeeping_top outputs
    wire        boot_mem_valid;
    wire [31:0] boot_mem_addr;
    wire [31:0] boot_mem_wdata;
    wire [3:0]  boot_mem_wstrb;
    wire        boot_mem_instr;

    // WhoAmI handshake wires
    wire whoami_pulse;
    wire c0_tser_ready;
    wire c1_tser_ready;
    wire whoami_ready;

    assign whoami_ready   = c0_tser_ready && c1_tser_ready;
    assign whoami_pulse_o = whoami_pulse;

    // housekeeping_top
    housekeeping_top #(
        .BOOT_SIZE      (BOOT_SIZE),
        .SRAM_BASE_ADDR (SRAM_BASE_ADDR)
    ) u_housekeeping (
        .clk_i          (clk_i),
        .reset_ni       (rst_ni),
        .pass_thru_en_i (pass_thru_en_i),
        .spi_sck_o      (spi_sck),
        .spi_mosi_o     (spi_mosi),
        .spi_miso_i     (flash_so),
        .flash_csb_o    (flash_csb),
        .whoami_ready_i (whoami_ready),
        .mem_valid_o    (boot_mem_valid),
        .mem_addr_o     (boot_mem_addr),
        .mem_wdata_o    (boot_mem_wdata),
        .mem_wstrb_o    (boot_mem_wstrb),
        .mem_instr_o    (boot_mem_instr),
        .cores_en_o     (cores_en_o),
        .boot_done_o    (boot_done_o),
        .whoami_pulse_o (whoami_pulse),
        // Reset generator modelled as already done; boot is not clear-gated here.
        .mem_clear_start_o (),
        .mem_clear_done_i  (1'b1),
        .scan_en_i      (1'b0),
        .scan_in_i      (1'b0),
        .scan_out_o     ()
    );

    // S25FL128L flash model
    s25fl128l #(
        .UserPreload   (1),
        .mem_file_name ("boot_image.mem"),
        .TimingModel   ("S25fl128LAGMFI010")
    ) u_flash (
        .SI           (flash_si),
        .SO           (flash_so),
        .SCK          (spi_sck),
        .CSNeg        (flash_csb),
        .RESETNeg     (1'b1),
        .WPNeg        (wp_tie),
        .IO3_RESETNeg (io3_tie)
    );

    // directory_interface_0 — cpu_id = 0x00
    directory_interface #(
        .NUM_TPINS (SER_PINS),
        .NUM_RPINS (SER_PINS)
    ) u_dir_interface_0 (
        .clk_i             (clk_i),
        .rst_ni            (rst_ni),
        // upstream — tied off, we only care about WhoAmI transmission
        .bus_valid_o       (),
        .bus_addr_o        (),
        .bus_wdata_o       (),
        .bus_cache_cmd_o   (),
        .bus_ready_i       (1'b1),
        .snoop_valid_o     (),
        .snoop_data_o      (),
        .snoop_cache_cmd_o (),
        .snoop_ready_i     (1'b1),
        .dir_valid_i       (1'b0),
        .dir_data_i        (32'h0),
        .dir_addr_i        (32'h0),
        .dir_cmd_i         (6'h0),
        .dir_ready_o       (c0_tser_ready),   // feeds back to whoami_ready
        .rbusy_o           (),
        // WhoAmI inputs
        .send_WhoAmI_i     (whoami_pulse),
        .cpu_id_i          (8'h00),
        .reset_done_o      (),
        // serial — exposed to testbench
        .req_i_branches    (5'b0),
        .serial_i          ({SER_PINS{1'b0}}),
        .req_o             (req_o_0),
        .serial_o          (serial_o_0),
        .scan_en_i         (1'b0),
        .scan_in_i         (1'b0),
        .scan_out_o        ()
    );

    // directory_interface_1 — cpu_id = 0x01
    directory_interface #(
        .NUM_TPINS (SER_PINS),
        .NUM_RPINS (SER_PINS)
    ) u_dir_interface_1 (
        .clk_i             (clk_i),
        .rst_ni            (rst_ni),
        // upstream — tied off
        .bus_valid_o       (),
        .bus_addr_o        (),
        .bus_wdata_o       (),
        .bus_cache_cmd_o   (),
        .bus_ready_i       (1'b1),
        .snoop_valid_o     (),
        .snoop_data_o      (),
        .snoop_cache_cmd_o (),
        .snoop_ready_i     (1'b1),
        .dir_valid_i       (1'b0),
        .dir_data_i        (32'h0),
        .dir_addr_i        (32'h0),
        .dir_cmd_i         (6'h0),
        .dir_ready_o       (c1_tser_ready),   // feeds back to whoami_ready
        .rbusy_o           (),
        // WhoAmI inputs
        .send_WhoAmI_i     (whoami_pulse),
        .cpu_id_i          (8'h01),
        .reset_done_o      (),
        // serial — exposed to testbench
        .req_i_branches    (5'b0),
        .serial_i          ({SER_PINS{1'b0}}),
        .req_o             (req_o_1),
        .serial_o          (serial_o_1),
        .scan_en_i         (1'b0),
        .scan_in_i         (1'b0),
        .scan_out_o        ()
    );

endmodule
