`timescale 1ns/1ps

module directory_interface #(
    parameter int NUM_PINS = 1,
    parameter int MAX_MSG_LEN = 68
)
(
    input  logic                clk_i
    input  logic                rst_ni

    // axi packet
    output logic                mem_valid,
    input  logic                mem_ready,

    output logic [31:0]         mem_addr,
    output logic [31:0]         mem_wdata,
    output logic [31:0]         mem_wstrb,
    input  logic [31:0]         mem_rdata,

    // coherence commands
    output logic [7:0]          cache_cmd,
    input  logic [7:0]          directory_cmd,

    // other signals
    output logic                rst_done,
    input  logic [7:0]          cpu_id,


    // wrapped serializer IO
    input  logic                req_i,
    input  logic [NUM_PINS-1:0] serial_i,
    output logic                req_o,
    output logic [NUM_PINS-1:0] serial_o
);

endmodule
