`timescale 1ns/1ps

module cache_interface #(
    parameter int NUM_TPINS = 1,
    parameter int NUM_RPINS = 1
)
(
    input  logic                clk_i,
    input  logic                rst_ni,

    // axi packet
    input  logic                mem_valid,
    output logic                mem_ready,

    input  logic [31:0]         mem_addr,
    input  logic [31:0]         mem_wdata,
    input  logic [31:0]         mem_wstrb,
    output logic [31:0]         mem_rdata,

    // coherence commands
    input  logic [6:0]          cache_cmd,
    output logic [5:0]          directory_cmd,

    // other signals
    output logic [7:0]          cpu_id,


    // wrapped serializer IO
    input  logic                 req_i,
    input  logic [NUM_RPINS-1:0] serial_i,
    output logic                 req_o,
    output logic [NUM_TPINS-1:0] serial_o
);

    typedef enum logic [3:0] { 
        NULL            = 4'b0000,
        BusRD           = 4'b0001,
        BusRDX          = 4'b0010,
        BusUPGR         = 4'b0011,
        EvictClean      = 4'b0100,
        BusRD_Ack       = 4'b0101,
        BusRDX_Ack      = 4'b0110,
        BusUPGR_Ack     = 4'b0111,
        EvictDirty      = 4'b1000,
        SnoopBusRD      = 4'b1001,
        SnoopBusRDX     = 4'b1010,
        SnoopBusUPGR    = 4'b1011,

        SnoopBusRD_Ack  = 4'b1101,
        WhoAmI          = 4'b1110,
        ResetDone       = 4'b1111
    } metadata;

    typedef enum logic [6:0] { 
        NULLcc1h            = 7'b0,
        BusRD_1h            = 7'b1,
        BusRDX_1h           = 7'b10,
        BusUPGR_1h          = 7'b100,
        EvictClean_1h       = 7'b1000,
        EvictDirty_1h       = 7'b10000,
        SnoopBusRD_Ack_1h   = 7'b100000,
        ResetDone_1h        = 7'b1000000
    } ccmd_1hot;

    typedef enum logic [6:0] { 
        NULLdc1h            = 7'b0,
        BusRD_Ack_1h        = 7'b1,
        BusRDX_Ack_1h       = 7'b10,
        BusUPGR_Ack_1h      = 7'b100,
        SnoopBusRD_1h       = 7'b1000,
        SnoopBusRDX_1h      = 7'b10000,
        SnoopBusUPGR_1h     = 7'b100000,
        WhoAmI_1h           = 7'b1000000
    } dcmd_1hot;

    typedef enum logic [1:0] {
        CMDONLY = 2'b00,
        SHORT   = 2'b01,
        MEDIUM  = 2'b10,
        LARGE   = 2'b11
    } msg_types;

    // TRANSMISSION
    logic [69:0] t_packet;
    always_comb begin : build_packet
         case (cache_cmd)
            BusRD_1h            : t_packet = {MEDIUM,  32'b0,     mem_addr, BusRD};
            BusRDX_1h           : t_packet = {MEDIUM,  32'b0,     mem_addr, BusRDX};
            BusUPGR_1h          : t_packet = {MEDIUM,  32'b0,     mem_addr, BusUPGR};
            EvictClean_1h       : t_packet = {MEDIUM,  32'b0,     mem_addr, EvictClean};
            EvictDirty_1h       : t_packet = {LARGE,   mem_wdata, mem_addr, EvictDirty};
            SnoopBusRD_Ack_1h   : t_packet = {MEDIUM,  32'b0,     mem_wdata, SnoopBusRD_Ack};
            ResetDone_1h        : t_packet = {CMDONLY, 32'b0,     32'b0,    ResetDone};
            default             : t_packet = '0;
        endcase
    end

    localparam int empty = (int'($ceil(real'(68) / NUM_TPINS)) * NUM_TPINS)-68;
    wire tready_o;
    tserializer #(
        .NUM_PINS    (NUM_TPINS),
        .MAX_MSG_LEN (68),
        .MSG_LEN_0   (4),
        .MSG_LEN_1   (12),
        .MSG_LEN_2   (36),
        .MSG_LEN_3   (68)
    ) u_tserializer (
        .clk_i    (clk_i),
        .rst_ni   (rst_ni),

        .req_o    (req_o),
        .serial_o (serial_o),

        .valid_i  (mem_valid),
        .data_in  (t_packet[67:0]),
        .msg_type (t_packet[69:68]),
        .ready_o  (tready_o)
    );

    // RECEIVING
    wire [(int'($ceil(real'(36) / NUM_RPINS)) * NUM_RPINS)-1:0] rpacket_full;
    wire rvalid_o;
    rserializer #(
        .NUM_PINS    (NUM_RPINS),
        .MAX_MSG_LEN (36)
    ) u_rserializer (
        .clk_i    (clk_i),
        .rst_ni   (rst_ni),
        
        .serial_i (serial_i),
        .req_i    (req_i),

        .valid_o  (rvalid_o),
        .data_o   (rpacket_full),
        .ready_i  (1'b1)
    );

    logic [3:0] rmetadata;
    dcmd_1hot dcmd_1h;
    assign rmetadata = rpacket_full[3:0];
    assign mem_rdata = rpacket_full[35:4];
    assign directory_cmd = dcmd_1h[5:0];

always_comb begin : decode_packet
        case (rmetadata)
            BusRD_Ack    : begin
                mem_ready = rvalid_o;
                dcmd_1h = BusRD_Ack_1h;
            end
            BusRDX_Ack   : begin
                mem_ready = rvalid_o;
                dcmd_1h = BusRDX_Ack_1h;
            end
            BusUPGR_Ack  : begin
                mem_ready = rvalid_o;
                dcmd_1h = BusUPGR_Ack_1h;
            end
            SnoopBusRD   : begin
                mem_ready = rvalid_o;
                dcmd_1h = SnoopBusRD_1h;
            end
            SnoopBusRDX  : begin
                mem_ready = rvalid_o;
                dcmd_1h = SnoopBusRDX_1h;
            end
            SnoopBusUPGR : begin
                mem_ready = rvalid_o;
                dcmd_1h = SnoopBusUPGR_1h;
            end
            WhoAmI       : begin
                mem_ready = '0;
                dcmd_1h = WhoAmI_1h;
            end
            default      : begin
                mem_ready = '0;
                dcmd_1h = NULLdc1h;
            end
        endcase
    end
    
    logic [7:0] cpu_id_r;
    always_ff @( posedge clk_i or negedge rst_ni ) begin : cpuid_reg
        if (!rst_ni) begin
            cpu_id_r <= '0;
        end else if ((rmetadata == WhoAmI) & (rvalid_o == 1)) begin
            cpu_id_r <= rpacket_full[11:4];
        end
    end
    assign cpu_id = cpu_id_r;

endmodule
