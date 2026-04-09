`timescale 1ns/1ps

module cache_interface #(
    parameter int NUM_PINS = 1,
    parameter int MAX_MSG_LEN = 68
)
(
    // axi packet
    input  logic                mem_valid,
    output logic                mem_ready,

    input  logic [31:0]         mem_addr,
    input  logic [31:0]         mem_wdata,
    input  logic [31:0]         mem_wstrb,
    output logic [31:0]         mem_rdata,

    // coherence commands
    input  logic [7:0]          cache_cmd,
    output logic [7:0]          directory_cmd,

    // other signals
    input  logic                rst_done,
    output logic [7:0]          cpu_id,


    // wrapped serializer IO
    input  logic                req_i,
    input  logic [NUM_PINS-1:0] serial_i,
    output logic                req_o,
    output logic [NUM_PINS-1:0] serial_o
);

endmodule