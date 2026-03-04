`timescale 1ns/1ps
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

    // -------------------------------------------------------------------------
    // Combinational: MSI transition logic
    // Reads CS (registered state), writes NS and outputs.
    // NS is only ever driven here — no multiple-driver conflict.
    // -------------------------------------------------------------------------
    always @(*) begin : msi_transitions

        // Safe defaults — hold state, no command, no flush
        cmd_valid = 1'b0;
        issue_cmd = `CMD_BUS_RD;   // don't-care when cmd_valid=0
        flush     = 1'b0;
        next_state = current_state;


        // -------------------------------------------------------
        // Snoop events (directory -> MSI module)
        // -------------------------------------------------------
        if (snoop_valid) begin
            case (current_state)

                `I: begin
                    // No copy of this line, ignore all snoops
                    next_state = `I;
                    flush = 1'b0;
                end

                `S: begin
                    case (snoop_event)
                        `BUS_RD: begin
                            // Another cache reading, stay SHARED
                            next_state = `S;
                            flush = 1'b0;
                        end
                        `BUS_RDX: begin
                            // Another cache writing, invalidate our copy
                            next_state = `I;
                            flush = 1'b0;
                        end
                        `BUS_UPGR: begin
                            // Another cache upgrading, invalidate our copy
                            next_state = `I;
                            flush = 1'b0;
                        end
                        default: next_state = `I;
                    endcase
                end

                `M: begin
                    case (snoop_event)
                        `BUS_RD: begin
                            // Another cache reading: flush dirty data, downgrade
                            next_state = `S;
                            flush = 1'b1;
                        end
                        `BUS_RDX: begin
                            // Another cache writing: flush dirty data, invalidate
                            next_state = `I;
                            flush = 1'b1;
                        end
                        `BUS_UPGR: begin
                            // Protocol violation: BUS_UPGR only issued from SHARED
                            // Handle gracefully — stay MODIFIED, no flush
                            next_state = `M;
                            flush = 1'b0;
                        end
                        default: next_state = `M;
                    endcase
                end

                default: next_state = `I;

            endcase
        end

        // -------------------------------------------------------
        // Processor events (cache controller -> MSI module)
        // -------------------------------------------------------
        else if (proc_valid) begin
            case (current_state)

                `I: begin
                    if (proc_event == `PR_RD) begin
                        // Read miss: fetch from memory, go SHARED
                        next_state = `S;
                        cmd_valid = 1'b1;
                        issue_cmd = `CMD_BUS_RD;
                    end else begin
                        // Write miss: get exclusive access, go MODIFIED
                        next_state = `M;
                        cmd_valid = 1'b1;
                        issue_cmd = `CMD_BUS_RDX;
                    end
                end

                `S: begin
                    if (proc_event == `PR_RD) begin
                        // Read hit: already have data, stay SHARED
                        next_state = `S;
                        cmd_valid = 1'b0;
                    end else begin
                        // Write upgrade: already have data, invalidate others
                        next_state = `M;
                        cmd_valid = 1'b1;
                        issue_cmd = `CMD_BUS_UPGR;
                    end
                end

                `M: begin
                    // Read or write hit: already exclusive, no action needed
                    next_state = `M;
                    cmd_valid = 1'b0;
                end

                default: next_state = `I;

            endcase

        end
    end
  endmodule
