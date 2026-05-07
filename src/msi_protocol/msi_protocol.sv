// SPDX-FileCopyrightText: © 2025 Albert Felix
// SPDX-License-Identifier: Apache-2.0
//
// msi_protocol.sv
// ─────────────────────────────────────────────────────────────────────────────
// Purely combinational MSI coherence state-machine.
//
// The module does NOT hold any state register – it is a Mealy output-logic
// block whose outputs are only a function of the current inputs.  The
// surrounding cache controller holds current_state in its own registers and
// latches next_state on the appropriate clock edge.
//
// Priority: proc_valid takes precedence over snoop_valid when both are
// asserted simultaneously (the cache controller must never generate this
// condition in normal operation).
//
// Processor transitions (proc_valid=1, snoop_valid=0)
// ────────────────────────────────────────────────────
//  State  proc_event  next_state  cmd_valid  issue_cmd    flush
//  I      PR_RD       S           1          CMD_BUS_RD   0
//  I      PR_WR       M           1          CMD_BUS_RDX  0
//  S      PR_RD       S           0          –            0   (hit)
//  S      PR_WR       M           1          CMD_BUS_UPGR 0
//  M      PR_RD       M           0          –            0   (hit)
//  M      PR_WR       M           0          –            0   (hit)
//
// Snoop transitions (snoop_valid=1, proc_valid=0)
// ────────────────────────────────────────────────────
//  State  snoop_event  next_state  cmd_valid  issue_cmd           flush
//  I      BUS_RD       I           0          –                   0
//  I      BUS_RDX      I           0          –                   0
//  I      BUS_UPGR     I           0          –                   0
//  S      BUS_RD       S           0          –                   0
//  S      BUS_RDX      I           0          –                   0
//  S      BUS_UPGR     I           0          –                   0
//  M      BUS_RD       S           1          CMD_SNOOP_BUS_RD    1
//  M      BUS_RDX      I           1          CMD_SNOOP_BUS_RDX   1
//  M      BUS_UPGR     I           0          –                   1  (* illegal)
//
// * M+BUS_UPGR is illegal in a correct protocol.  The RTL silently flushes
//   and invalidates rather than locking up or asserting an error output.
// ─────────────────────────────────────────────────────────────────────────────

`timescale 1ns/1ps

`default_nettype none

module msi_protocol (
    // clk_i / reset_i are present so the module can be instantiated in a
    // synchronous wrapper without interface changes.  The combinational logic
    // inside does not register its outputs.
    input  wire        clk_i,
    input  wire        reset_i,

    // Current MSI state of the cache line (held by the cache controller)
    input  wire [1:0]  current_state,   // I=2'b00  S=2'b01  M=2'b10

    // Processor-side event
    input  wire        proc_valid,      // 1 = processor access is active
    input  wire        proc_event,      // PR_RD=0  PR_WR=1

    // Snoop-side event (from directory / bus)
    input  wire        snoop_valid,     // 1 = snoop is active
    input  wire [1:0]  snoop_event,     // BUS_RD=2'b00  BUS_RDX=2'b01  BUS_UPGR=2'b10

    // Outputs
    output reg  [1:0]  next_state,      // recommended next MSI state
    output reg         cmd_valid,       // 1 = issue_cmd carries a valid command
    output reg  [2:0]  issue_cmd,       // coherence command to issue on the bus
    output reg         flush            // 1 = cache line must be written back
);

// ─── Local constants ──────────────────────────────────────────────────────────

// MSI States
localparam [1:0] ST_I = 2'b00;
localparam [1:0] ST_S = 2'b01;
localparam [1:0] ST_M = 2'b10;

// Processor Events
localparam PR_RD = 1'b0;
localparam PR_WR = 1'b1;

// Snoop Events
localparam [1:0] BUS_RD   = 2'b00;
localparam [1:0] BUS_RDX  = 2'b01;
localparam [1:0] BUS_UPGR = 2'b10;

// Coherence Commands (match Python CoherenceCmd enum / interposer metadata)
localparam [2:0] CMD_BUS_RD         = 3'd0;
localparam [2:0] CMD_BUS_RDX        = 3'd1;
localparam [2:0] CMD_BUS_UPGR       = 3'd2;
localparam [2:0] CMD_EVICT_CLEAN    = 3'd3;
localparam [2:0] CMD_EVICT_DIRTY    = 3'd4;
localparam [2:0] CMD_SNOOP_BUS_RD   = 3'd5;
localparam [2:0] CMD_SNOOP_BUS_RDX  = 3'd6;
localparam [2:0] CMD_SNOOP_BUS_UPGR = 3'd7;

// ─── Combinational MSI logic ──────────────────────────────────────────────────

always @(*) begin
    // ── Safe defaults: hold state, no command, no flush ────────────────────
    next_state = current_state;
    cmd_valid  = 1'b0;
    issue_cmd  = CMD_BUS_RD;   // arbitrary safe default (cmd_valid=0 gates it)
    flush      = 1'b0;

    // ── Reset override ─────────────────────────────────────────────────────
    if (reset_i) begin
        next_state = ST_I;
        cmd_valid  = 1'b0;
        issue_cmd  = CMD_BUS_RD;
        flush      = 1'b0;

    // ── Processor event (priority over snoop) ──────────────────────────────
    end else if (proc_valid) begin
        case (current_state)

            ST_I: begin
                case (proc_event)
                    PR_RD: begin
                        next_state = ST_S;
                        cmd_valid  = 1'b1;
                        issue_cmd  = CMD_BUS_RD;
                    end
                    PR_WR: begin
                        next_state = ST_M;
                        cmd_valid  = 1'b1;
                        issue_cmd  = CMD_BUS_RDX;
                    end
                    default: begin
                        // unreachable (1-bit event), safe default
                        next_state = ST_I;
                    end
                endcase
            end

            ST_S: begin
                case (proc_event)
                    PR_RD: begin
                        // Hit in Shared – no bus action
                        next_state = ST_S;
                        cmd_valid  = 1'b0;
                    end
                    PR_WR: begin
                        // Upgrade Shared→Modified
                        next_state = ST_M;
                        cmd_valid  = 1'b1;
                        issue_cmd  = CMD_BUS_UPGR;
                    end
                    default: begin
                        next_state = ST_S;
                    end
                endcase
            end

            ST_M: begin
                // Hit in Modified for both reads and writes – no bus action
                next_state = ST_M;
                cmd_valid  = 1'b0;
            end

            default: begin
                // Undefined state encoding – safe invalidate
                next_state = ST_I;
                cmd_valid  = 1'b0;
            end

        endcase

    // ── Snoop event ────────────────────────────────────────────────────────
    end else if (snoop_valid) begin
        case (current_state)

            ST_I: begin
                // We do not have the line – ignore all snoops
                next_state = ST_I;
                cmd_valid  = 1'b0;
            end

            ST_S: begin
                case (snoop_event)
                    BUS_RD: begin
                        // Another cache reads – stay shared, no action
                        next_state = ST_S;
                        cmd_valid  = 1'b0;
                    end
                    BUS_RDX: begin
                        // Another cache takes exclusive – invalidate
                        next_state = ST_I;
                        cmd_valid  = 1'b0;
                    end
                    BUS_UPGR: begin
                        // Another cache upgrades S→M – invalidate our copy
                        next_state = ST_I;
                        cmd_valid  = 1'b0;
                    end
                    default: begin
                        next_state = ST_I;
                        cmd_valid  = 1'b0;
                    end
                endcase
            end

            ST_M: begin
                case (snoop_event)
                    BUS_RD: begin
                        // Supply dirty data, downgrade to Shared
                        next_state = ST_S;
                        cmd_valid  = 1'b1;
                        issue_cmd  = CMD_SNOOP_BUS_RD;
                        flush      = 1'b1;
                    end
                    BUS_RDX: begin
                        // Supply dirty data, invalidate
                        next_state = ST_I;
                        cmd_valid  = 1'b1;
                        issue_cmd  = CMD_SNOOP_BUS_RDX;
                        flush      = 1'b1;
                    end
                    BUS_UPGR: begin
                        // Illegal: M cannot be upgraded by another cache.
                        // Flush and invalidate silently (no cmd to avoid
                        // protocol deadlock in case of a bug upstream).
                        next_state = ST_I;
                        cmd_valid  = 1'b0;
                        flush      = 1'b1;
                    end
                    default: begin
                        next_state = ST_M;
                        cmd_valid  = 1'b0;
                    end
                endcase
            end

            default: begin
                next_state = ST_I;
                cmd_valid  = 1'b0;
            end

        endcase

    end
    // If neither proc_valid nor snoop_valid: defaults hold (state unchanged).
end

endmodule

`default_nettype wire

