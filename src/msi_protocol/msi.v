// ============================================================================
// MSI State and Event Definitions
// ============================================================================

// MSI States
`define I 2'b00
`define S 2'b01
`define M 2'b10

// Processor Events
`define PR_RD 1'b0
`define PR_WR 1'b1

// Snoop Events
`define BUS_RD   2'b00
`define BUS_RDX  2'b01
`define BUS_UPGR 2'b10

// Coherence Commands
`define CMD_BUS_RD         3'd0
`define CMD_BUS_RDX        3'd1
`define CMD_BUS_UPGR       3'd2
`define CMD_EVICT_CLEAN    3'd3
`define CMD_EVICT_DIRTY    3'd4
`define CMD_SNOOP_BUS_RD   3'd5
`define CMD_SNOOP_BUS_RDX  3'd6
`define CMD_SNOOP_BUS_UPGR 3'd7


// ============================================================================
// MSI Protocol Module
// ============================================================================

module msi_protocol (
    input  wire        clk_i,
    input  wire        reset_i,
    input  wire [1:0]  current_state,   // owned by cache controller/directory
    input  wire        proc_valid,
    input  wire        proc_event,
    input  wire        snoop_valid,
    input  wire [1:0]  snoop_event,
    output reg  [1:0]  next_state,
    output reg         cmd_valid,
    output reg  [2:0]  issue_cmd,
    output reg         flush
);

    // CS is the registered current state — advances to NS each clock edge
    // NS is purely combinational — computed from CS + events each cycle
    reg [1:0] CS;
    reg [1:0] NS;

    // -------------------------------------------------------------------------
    // Sequential: CS register
    // Resets to INVALID, advances to NS each clock edge.
    // NS is computed combinationally below — no conflict.
    // -------------------------------------------------------------------------
    always @(posedge clk_i or posedge reset_i) begin
        if (reset_i)
            CS <= `I;
        else
            CS <= NS;   // advance registered state to combinational next state
    end

    // -------------------------------------------------------------------------
    // Combinational: MSI transition logic
    // Reads CS (registered state), writes NS and outputs.
    // NS is only ever driven here — no multiple-driver conflict.
    // -------------------------------------------------------------------------
    always @(*) begin : msi_transitions

        // Safe defaults — hold state, no command, no flush
        NS        = CS;
        cmd_valid = 1'b0;
        issue_cmd = `CMD_BUS_RD;   // don't-care when cmd_valid=0
        flush     = 1'b0;

        // -------------------------------------------------------
        // Processor events (cache controller -> MSI module)
        // -------------------------------------------------------
        if (proc_valid) begin
            case (CS)

                `I: begin
                    if (proc_event == `PR_RD) begin
                        // Read miss: fetch from memory, go SHARED
                        NS        = `S;
                        cmd_valid = 1'b1;
                        issue_cmd = `CMD_BUS_RD;
                    end else begin
                        // Write miss: get exclusive access, go MODIFIED
                        NS        = `M;
                        cmd_valid = 1'b1;
                        issue_cmd = `CMD_BUS_RDX;
                    end
                end

                `S: begin
                    if (proc_event == `PR_RD) begin
                        // Read hit: already have data, stay SHARED
                        NS        = `S;
                        cmd_valid = 1'b0;
                    end else begin
                        // Write upgrade: already have data, invalidate others
                        NS        = `M;
                        cmd_valid = 1'b1;
                        issue_cmd = `CMD_BUS_UPGR;
                    end
                end

                `M: begin
                    // Read or write hit: already exclusive, no action needed
                    NS        = `M;
                    cmd_valid = 1'b0;
                end

                default: NS = `I;

            endcase

        // -------------------------------------------------------
        // Snoop events (directory -> MSI module)
        // -------------------------------------------------------
        end else if (snoop_valid) begin
            case (CS)

                `I: begin
                    // No copy of this line, ignore all snoops
                    NS    = `I;
                    flush = 1'b0;
                end

                `S: begin
                    case (snoop_event)
                        `BUS_RD: begin
                            // Another cache reading, stay SHARED
                            NS    = `S;
                            flush = 1'b0;
                        end
                        `BUS_RDX: begin
                            // Another cache writing, invalidate our copy
                            NS    = `I;
                            flush = 1'b0;
                        end
                        `BUS_UPGR: begin
                            // Another cache upgrading, invalidate our copy
                            NS    = `I;
                            flush = 1'b0;
                        end
                        default: NS = `I;
                    endcase
                end

                `M: begin
                    case (snoop_event)
                        `BUS_RD: begin
                            // Another cache reading: flush dirty data, downgrade
                            NS    = `S;
                            flush = 1'b1;
                        end
                        `BUS_RDX: begin
                            // Another cache writing: flush dirty data, invalidate
                            NS    = `I;
                            flush = 1'b1;
                        end
                        `BUS_UPGR: begin
                            // Protocol violation: BUS_UPGR only issued from SHARED
                            // Handle gracefully — stay MODIFIED, no flush
                            NS    = `M;
                            flush = 1'b0;
                        end
                        default: NS = `M;
                    endcase
                end

                default: NS = `I;

            endcase
        end
    end

    // next_state output reflects the combinational NS
    always @(*) begin
        next_state = NS;
    end

endmodule
