// SPDX-FileCopyrightText: © 2025 XXX Authors
// SPDX-License-Identifier: Apache-2.0
//
// Bit-sliced 8192-entry x 3-bit directory metadata (3.3V/8192-line replacement
// for mem2048x3).
//
// Storage is three gf180mcu 1024x8 single-port SRAMs (OCD / 3.3V library), one
// per bit plane. A line index selects a row from the high address bits and a
// bit lane from the low three bits:
//
//   row lane = addr_i[12:3]  (1024 rows)
//   bit lane = addr_i[2:0]   (1 of 8 lines packed per byte)
//
// Plane k stores bit k of every line, so one byte in plane k holds the same bit
// for eight consecutive lines. A single-line write uses the SRAM per-bit write
// mask (WEN) to update only the addressed bit lane, leaving the other seven
// lines that share the byte untouched.
//
// CONTENTS CLEAR: an internal counter sweeps the 1024 rows and, via the
// whole-row clear (all eight lane bits in a row to zero per write), clears the
// full 8192-line metadata in 1024 cycles. This is the metadata half of the
// distributed self-clear that replaces the external memory_reset_generator; it
// is NOT on any scan chain. Read timing is unchanged: Q is registered, so the
// consumer must hold addr_i[2:0] from the access cycle into the capture cycle.

`default_nettype none

module mem8192x3 (
  input  wire        clk_i,
  input  wire        rst_ni,
  input  wire        enable_n_i,   // active-low access enable (CEN), low on any access
  input  wire        we_i,         // 1 = write, 0 = read
  input  wire [12:0] addr_i,       // line index, 0..8191
  input  wire [2:0]  wdata_i,      // bits to write for the selected line
  output wire [2:0]  rdata_o,      // bits read for the selected line

  // Contents-clear handshake (see header). clear_start_i high (held) requests a
  // full zero sweep; clear_done_o rises when done and stays high until re-asked.
  input  wire        clear_start_i,
  output wire        clear_done_o,

  // DFT scan chain for the clear FSM (debug_mode_i selects scan vs functional).
  input  wire        debug_mode_i,
  input  wire        scan_in_i,
  output wire        scan_out_o

  `ifdef USE_POWER_PINS
    ,inout wire VDD,
    inout wire VSS
  `endif
);

  // -------------------------------------------------------------------------
  // Clear FSM: one 10-bit row counter, whole-row clear -> 1024 cycles.
  // -------------------------------------------------------------------------
  localparam logic [9:0] CLR_LAST = 10'd1023;

  logic        clr_state_q, clr_state_d;   // 0 = idle, 1 = clearing
  logic [9:0]  clr_row_q,   clr_row_d;
  logic        clr_done_q,  clr_done_d;
  logic        start_q;

  wire start_pulse = clear_start_i & ~start_q;
  wire clearing    = clr_state_q;

  always_comb begin
    clr_state_d = clr_state_q;
    clr_row_d   = clr_row_q;
    clr_done_d  = clr_done_q;

    if (!clr_state_q) begin
      if (start_pulse) begin
        clr_done_d  = 1'b0;
        clr_row_d   = 10'd0;
        clr_state_d = 1'b1;
      end
    end else begin
      if (clr_row_q == CLR_LAST) begin
        clr_done_d  = 1'b1;
        clr_state_d = 1'b0;
      end
      clr_row_d = clr_row_q + 10'd1;
    end
  end

  // DFT scan chain: concat of the clear-FSM registers. scan_in enters
  // clr_state_q (LSB); the MSB (start_q) drives scan_out.
  localparam int CLR_SCAN_N = 13;
  wire [CLR_SCAN_N-1:0] scan_state = {start_q, clr_done_q, clr_row_q, clr_state_q};
  assign scan_out_o = scan_state[CLR_SCAN_N-1];

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      clr_state_q <= 1'b0;
      clr_row_q   <= 10'd0;
      clr_done_q  <= 1'b0;
      start_q     <= 1'b0;
    end else if (debug_mode_i) begin
      {start_q, clr_done_q, clr_row_q, clr_state_q} <= {scan_state[CLR_SCAN_N-2:0], scan_in_i};
    end else begin
      clr_state_q <= clr_state_d;
      clr_row_q   <= clr_row_d;
      clr_done_q  <= clr_done_d;
      start_q     <= clear_start_i;
    end
  end

  assign clear_done_o = clr_done_q;

  // -------------------------------------------------------------------------
  // SRAM drive: functional access, or the clear sweep.
  // -------------------------------------------------------------------------
  wire [9:0] func_row  = addr_i[12:3];
  wire [2:0] bit_lane  = addr_i[2:0];
  wire [7:0] onehot    = 8'b1 << bit_lane;

  // Address: clear counter sweeps the rows; otherwise the functional row.
  wire [9:0] row_addr  = clearing ? clr_row_q : func_row;

  // Access enable (active low): asserted on functional access or during clear.
  wire       cen       = clearing ? 1'b0 : enable_n_i;
  // Global write enable (active low): write on functional write or during clear.
  wire       gwen      = clearing ? 1'b0 : ~we_i;
  // Per-bit mask (active low): clear enables all eight lanes; a functional write
  // enables only the addressed lane.
  wire [7:0] wen       = clearing ? 8'h00 : ~onehot;

  // Write data replicated across the byte on a functional write; zero on clear.
  wire [7:0] d0 = clearing ? 8'h00 : {8{wdata_i[0]}};
  wire [7:0] d1 = clearing ? 8'h00 : {8{wdata_i[1]}};
  wire [7:0] d2 = clearing ? 8'h00 : {8{wdata_i[2]}};

  wire [7:0] q0, q1, q2;

  (* keep *) gf180mcu_ocd_ip_sram__sram1024x8m8wm1 plane0 (
    .CLK  (clk_i),
    .CEN  (cen),
    .GWEN (gwen),
    .WEN  (wen),
    .A    (row_addr),
    .D    (d0),
    .Q    (q0)
    `ifdef USE_POWER_PINS
      ,.VDD (VDD)
      ,.VSS (VSS)
    `endif
  );

  (* keep *) gf180mcu_ocd_ip_sram__sram1024x8m8wm1 plane1 (
    .CLK  (clk_i),
    .CEN  (cen),
    .GWEN (gwen),
    .WEN  (wen),
    .A    (row_addr),
    .D    (d1),
    .Q    (q1)
    `ifdef USE_POWER_PINS
      ,.VDD (VDD)
      ,.VSS (VSS)
    `endif
  );

  (* keep *) gf180mcu_ocd_ip_sram__sram1024x8m8wm1 plane2 (
    .CLK  (clk_i),
    .CEN  (cen),
    .GWEN (gwen),
    .WEN  (wen),
    .A    (row_addr),
    .D    (d2),
    .Q    (q2)
    `ifdef USE_POWER_PINS
      ,.VDD (VDD)
      ,.VSS (VSS)
    `endif
  );

  // Select the addressed line's bit from each plane byte.
  assign rdata_o = {q2[bit_lane], q1[bit_lane], q0[bit_lane]};

endmodule

`default_nettype wire
