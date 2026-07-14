// SPDX-License-Identifier: Apache-2.0
//
// Memory reset generator for the full-directory MSI subsystem.
//
// directory_controller_full owns only the coherence protocol; it explicitly
// leaves the *contents* reset of its two backing memories to an external block.
// This is that block. On a start request it sweeps both memories to a known
// zero state and raises a readiness output once the sweep completes:
//
//   * directory metadata  -> mem2048x3        (2048 lines x 3 bits)
//   * main memory          -> mem_ctrl_2048x32 (2048 words x 32 bits)
//
// The two memories sit on independent ports, so they are cleared concurrently
// and the generator finishes when the slower of the two sweeps is done.
//
//   * Metadata uses the mem2048x3 whole-row clear (clear_i): one write zeroes
//     all eight lines packed into a row, so 256 row-writes cover all 2048
//     lines (row index = addr[10:3]).
//   * Main memory has no bulk-clear mode, so all 2048 words are written zero
//     one per cycle, advancing on the memory's ready handshake.
//
// Intended integration: mux this block's metadata/main-memory ports ahead of
// directory_controller_full's identical ports, selecting the generator while
// busy_o is high and handing the buses to the controller once ready_o asserts.
// The controller should be held in reset (or idle) until ready_o is seen.

`timescale 1ns/1ps
`default_nettype none

module memory_reset_generator (
  input  logic        clk_i,
  input  logic        rst_ni,

  // Rising edge requests a full clear of both memories. May be a single-cycle
  // pulse or a level; only the 0->1 transition starts a sweep, so holding it
  // high does not continuously re-clear.
  input  logic        start_i,

  // High while a clear sweep is in progress.
  output logic        busy_o,
  // High once both memories have been fully cleared. Cleared at the start of a
  // new sweep and re-asserted when that sweep completes; low out of reset until
  // the first sweep finishes.
  output logic        ready_o,

  // Directory metadata memory port (mem2048x3), driven in whole-row clear mode.
  output logic        md_enable_n_o,  // active-low access enable
  output logic        md_we_o,        // 1 = write
  output logic        md_clear_o,     // with md_we_o: zero all lines in the row
  output logic [10:0] md_addr_o,      // line index; [10:3] selects the row
  output logic [2:0]  md_wdata_o,     // unused during clear, held at zero

  // Main memory port (mem_ctrl_2048x32).
  output logic        mm_valid_o,
  output logic        mm_instr_o,
  output logic [31:0] mm_addr_o,
  output logic [3:0]  mm_wstrb_o,     // per-byte write enable, 0 = read
  output logic [31:0] mm_wdata_o,
  input  logic        mm_ready_i,

  // DFT scan chain (debug_mode_i is the scan/functional select).
  input  logic        debug_mode_i,
  input  logic        scan_in_i,
  output logic        scan_out_o
);

  // Metadata rows: addr[10:3] indexes 256 rows, each holding eight lines.
  localparam logic [7:0]  MD_LAST_ROW  = 8'd255;
  // Main memory: 2048 words addressed by [10:0].
  localparam logic [10:0] MM_LAST_WORD = 11'd2047;

  typedef enum logic [0:0] {
    StIdle,
    StClear
  } rst_state_e;

  rst_state_e state_d, state_q;

  logic [7:0]  md_row_d,  md_row_q;
  logic        md_done_d, md_done_q;

  logic [10:0] mm_word_d,  mm_word_q;
  logic        mm_done_d,  mm_done_q;

  logic ready_d, ready_q;

  // Rising-edge detect on start_i.
  logic start_q;
  logic start_pulse;
  assign start_pulse = start_i && !start_q;

  // DFT scan chain: concat of all functional registers. scan_in enters state_q
  // (LSB); scan_out is the MSB. debug_mode_i selects scan vs functional below.
  localparam int RG_SCAN_N = 24;
  logic [RG_SCAN_N-1:0] scan_state;
  assign scan_state = {start_q, ready_q, mm_done_q, mm_word_q,
                       md_done_q, md_row_q, state_q};
  assign scan_out_o = scan_state[RG_SCAN_N-1];

  // ---------------------------------------------------------------------------
  // Memory port outputs.
  // ---------------------------------------------------------------------------
  always_comb begin
    md_enable_n_o = 1'b1;
    md_we_o       = 1'b0;
    md_clear_o    = 1'b0;
    md_addr_o     = {md_row_q, 3'b000};
    md_wdata_o    = 3'b000;

    mm_valid_o    = 1'b0;
    mm_instr_o    = 1'b0;
    mm_addr_o     = {21'b0, mm_word_q};
    mm_wstrb_o    = 4'b0000;
    mm_wdata_o    = 32'b0;

    if (state_q == StClear) begin
      // Issue the metadata row clear until every row has been swept.
      if (!md_done_q) begin
        md_enable_n_o = 1'b0;
        md_we_o       = 1'b1;
        md_clear_o    = 1'b1;
      end
      // Issue the main-memory zero write until every word has been swept.
      if (!mm_done_q) begin
        mm_valid_o    = 1'b1;
        mm_wstrb_o    = 4'b1111;
      end
    end
  end

  assign busy_o  = (state_q == StClear);
  assign ready_o = ready_q;

  // ---------------------------------------------------------------------------
  // Next-state / counter logic.
  // ---------------------------------------------------------------------------
  always_comb begin
    state_d   = state_q;
    md_row_d  = md_row_q;
    md_done_d = md_done_q;
    mm_word_d = mm_word_q;
    mm_done_d = mm_done_q;
    ready_d   = ready_q;

    unique case (state_q)
      StIdle: begin
        if (start_pulse) begin
          ready_d   = 1'b0;
          md_row_d  = 8'd0;
          md_done_d = 1'b0;
          mm_word_d = 11'd0;
          mm_done_d = 1'b0;
          state_d   = StClear;
        end
      end

      StClear: begin
        // Advance the metadata sweep; one row is cleared per cycle.
        if (!md_done_q) begin
          if (md_row_q == MD_LAST_ROW) md_done_d = 1'b1;
          md_row_d = md_row_q + 8'd1;
        end

        // Advance the main-memory sweep on the memory's ready handshake.
        if (!mm_done_q && mm_ready_i) begin
          if (mm_word_q == MM_LAST_WORD) mm_done_d = 1'b1;
          mm_word_d = mm_word_q + 11'd1;
        end

        // The writes issued this cycle commit on the coming edge, so completion
        // is detected on the just-computed done flags.
        if (md_done_d && mm_done_d) begin
          ready_d = 1'b1;
          state_d = StIdle;
        end
      end

      default: begin
        state_d = StIdle;
      end
    endcase
  end

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      state_q   <= StIdle;
      md_row_q  <= 8'd0;
      md_done_q <= 1'b0;
      mm_word_q <= 11'd0;
      mm_done_q <= 1'b0;
      ready_q   <= 1'b0;
      start_q   <= 1'b0;
    end else if (debug_mode_i) begin
      {start_q, ready_q, mm_done_q, mm_word_q,
       md_done_q, md_row_q, state_q} <= {scan_state[RG_SCAN_N-2:0], scan_in_i};
    end else begin
      state_q   <= state_d;
      md_row_q  <= md_row_d;
      md_done_q <= md_done_d;
      mm_word_q <= mm_word_d;
      mm_done_q <= mm_done_d;
      ready_q   <= ready_d;
      start_q   <= start_i;
    end
  end

endmodule : memory_reset_generator

`default_nettype wire
