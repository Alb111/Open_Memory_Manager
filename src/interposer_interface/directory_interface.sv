`timescale 1ns/1ps

module directory_interface #(
    parameter int NUM_TPINS = 9,
    parameter int NUM_RPINS = 9
)
(
    input  logic                clk_i,
    input  logic                rst_ni,

    // DOWNSTREAM ------------------------------------
    // Bus Req Ports
    output logic                bus_valid_o,
    output logic [31:0]         bus_addr_o,
    output logic [31:0]         bus_wdata_o,
    output logic [3:0]          bus_cache_cmd_o,
    input  logic                bus_ready_i,

    // Snoop Ack Ports
    output logic                snoop_valid_o,
    output logic [31:0]         snoop_data_o,
    output logic [3:0]          snoop_cache_cmd_o,
    input  logic                snoop_ready_i,

    // Directory Send Ports
    input  logic                dir_valid_i,
    input  logic [31:0]         dir_data_i,
    input  logic [31:0]         dir_addr_i,
    input  logic [3:0]          dir_cmd_i,  // 4-bit binary metadata code; does not include WhoAmI
    output logic                dir_ready_o,

    // busy
    output logic                rbusy_o,

    // WhoAmI
    input  logic                send_WhoAmI_i,
    input  logic [7:0]          cpu_id_i,

    // Reset Done
    output logic                reset_done_o, // should pulse when reset done command is received
    // -----------------------------------------------

    // UPSTREAM --------------------------------------
    // wrapped serializer IO
    input  logic [4:0]          req_i_branches,
    input  logic [NUM_RPINS-1:0] serial_i,
    output logic                req_o,
    output logic [NUM_TPINS-1:0] serial_o,

    input  logic                scan_en_i,
    input  logic                scan_in_i,
    output logic                scan_out_o
    // -----------------------------------------------
);

    typedef enum logic [3:0] { 
        NULL            = 4'b0000,
        BusRD           = 4'b0001,
        BusRDX          = 4'b0010,
        BusUPGR         = 4'b0011,

        EvictClean      = 4'b0101,
        EvictDirty      = 4'b0110,


        SnoopBusRD      = 4'b1001,
        SnoopBusRDX     = 4'b1010,
        SnoopBusUPGR    = 4'b1011,

        
        WhoAmI          = 4'b1110,
        ResetDone       = 4'b1111
    } metadata;

    typedef enum logic [1:0] {
        CMDONLY = 2'b00,
        SHORT   = 2'b01,
        MEDIUM  = 2'b10,
        LARGE   = 2'b11
    } msg_types;

    // TRANSMISSION ----------------------------------
    logic [37:0] t_packet;
    // dir_cmd_i is already the 4-bit binary `metadata` code, so the packet's
    // metadata field is just dir_cmd_i; the case only selects msg length + payload.
    // Acks echo the request's metadata code (EvictDirty = dirty writeback persisted).
    always_comb begin : build_packet
        if (send_WhoAmI_i) begin
            t_packet = {SHORT, 24'b0, cpu_id_i, WhoAmI};
        end else begin
            case (dir_cmd_i)
                BusRD          : t_packet = {MEDIUM,  dir_data_i, dir_cmd_i};
                BusRDX         : t_packet = {MEDIUM,  dir_data_i, dir_cmd_i};
                BusUPGR        : t_packet = {CMDONLY, 32'b0,      dir_cmd_i};
                EvictDirty     : t_packet = {CMDONLY, 32'b0,      dir_cmd_i};
                SnoopBusRD     : t_packet = {MEDIUM,  dir_addr_i, dir_cmd_i};
                SnoopBusRDX    : t_packet = {MEDIUM,  dir_addr_i, dir_cmd_i};
                SnoopBusUPGR   : t_packet = {MEDIUM,  dir_addr_i, dir_cmd_i};
                default        : t_packet = '0;
            endcase
        end
    end

    logic tserial_valid;
    logic tserializer_scan_out;
    logic rserializer_scan_out;
    logic bus_pipe_scan_out;
    assign tserial_valid = dir_valid_i | send_WhoAmI_i;

    tserializer #(
        .NUM_PINS    (NUM_TPINS),
        .MAX_MSG_LEN (36),
        .MSG_LEN_0   (4),
        .MSG_LEN_1   (12),
        .MSG_LEN_2   (36),
        .MSG_LEN_3   (68)
    ) u_tserializer (
        .clk_i    (clk_i),
        .rst_ni   (rst_ni),
        .debug_mode_i(scan_en_i),
        .scan_in_i(scan_in_i),
        .scan_out_o(tserializer_scan_out),

        .req_o    (req_o),
        .serial_o (serial_o),

        .valid_i  (tserial_valid),
        .data_in  (t_packet[35:0]),
        .msg_type (t_packet[37:36]),
        .ready_o  (dir_ready_o)

    );
    // -----------------------------------------------

    // RECEIVING -------------------------------------
    wire [(int'($ceil(real'(68) / NUM_RPINS)) * NUM_RPINS)-1:0] rpacket_full;
    wire rvalid_o;
    assign rbusy_o = req_i_branches[0];
    rserializer #(
        .NUM_PINS    (NUM_RPINS),
        .MAX_MSG_LEN (68)
    ) u_rserializer (
        .clk_i    (clk_i),
        .rst_ni   (rst_ni),
        .debug_mode_i(scan_en_i),
        .scan_in_i(tserializer_scan_out),
        .scan_out_o(rserializer_scan_out),
        
        .serial_i (serial_i),
        .req_i_branches(req_i_branches),

        .valid_o  (rvalid_o),
        .data_o   (rpacket_full),
        .ready_i  (1'b1)
    );

    logic [3:0] rmetadata;
    assign rmetadata = rpacket_full[3:0];

    logic           bus_valid_d;
    logic           snoop_valid_d;

    // No one-hot conversion: rmetadata IS the command code passed downstream.
    // Just route it to the bus vs snoop pipe (or pulse reset_done).
    always_comb begin : decode_packet
        bus_valid_d   = 1'b0;
        snoop_valid_d = 1'b0;
        reset_done_o  = 1'b0;

        case (rmetadata)
            BusRD, BusRDX, BusUPGR,
            EvictClean, EvictDirty                : bus_valid_d   = rvalid_o;
            SnoopBusRD, SnoopBusRDX, SnoopBusUPGR : snoop_valid_d = rvalid_o;
            ResetDone                             : reset_done_o  = rvalid_o;
            default                               : ;
        endcase
    end

    logic [31:0]    receive_data0_d;
    logic [31:0]    receive_data1_d;
    assign receive_data0_d = rpacket_full[35:4];
    assign receive_data1_d = rpacket_full[67:36];

    // bus ack data interface
    wire bus_ack_rready_i;
    lossy_pipe_stage #(
        .WIDTH(68)
    ) bus_ack_pipe (
        .clk_i   (clk_i),
        .rst_ni  (rst_ni),
        .debug_mode_i(scan_en_i),
        .scan_in_i(rserializer_scan_out),
        .scan_out_o(bus_pipe_scan_out),

        // Upstream Interface
        .valid_i (bus_valid_d),
        .data_i  ({rmetadata, receive_data1_d, receive_data0_d}),
        .ready_o (bus_ack_rready_i),    // tied to one because it's lossy

        // Downstream Interface
        .valid_o (bus_valid_o),
        .data_o  ({bus_cache_cmd_o, bus_wdata_o, bus_addr_o}),
        .ready_i (bus_ready_i)
    );

    // snoop data interface
    wire snoop_rready_i;
    lossy_pipe_stage #(
        .WIDTH(36)
    ) snoop_pipe (
        .clk_i   (clk_i),
        .rst_ni  (rst_ni),
        .debug_mode_i(scan_en_i),
        .scan_in_i(bus_pipe_scan_out),
        .scan_out_o(scan_out_o),

        // Upstream Interface
        .valid_i (snoop_valid_d),
        .data_i  ({rmetadata, receive_data0_d}),
        .ready_o (snoop_rready_i),    // tied to one because it's lossy

        // Downstream Interface
        .valid_o (snoop_valid_o),
        .data_o  ({snoop_cache_cmd_o, snoop_data_o}),
        .ready_i (snoop_ready_i)
    );
    // -----------------------------------------------
endmodule
