// SPDX-FileCopyrightText: © 2025 XXX Authors
// SPDX-License-Identifier: Apache-2.0
//
// Standalone bit-sliced 2048-entry x 3-bit memory.
//
// Storage is three gf180mcu 256x8 single-port SRAMs, one per bit plane. A line
// index selects a row from the high address bits and a bit lane from the low
// three bits:
//
//   row lane = addr_i[10:3]  (256 rows)
//   bit lane = addr_i[2:0]   (1 of 8 lines packed per byte)
//
// Plane k stores bit k of every line, so one byte in plane k holds the same bit
// for eight consecutive lines. A single-line write uses the SRAM per-bit write
// mask (WEN) to update only the addressed bit lane, leaving the other seven
// lines that share the byte untouched. A whole-byte clear mode zeroes the eight
// lines in a row at once, so a full clear touches only 256 rows.
//
// This is a pure combinational wrapper around three synchronous SRAMs; it holds
// no state of its own. Access timing follows the underlying macros:
//
//   * enable_n_i is the active-low access enable (low on any read or write).
//   * we_i selects write (1) vs read (0); clear_i selects whole-byte clear.
//   * Read data appears the cycle after the access, from the SRAM registered Q.
//     The consumer must keep addr_i[2:0] stable from the access cycle into the
//     capture cycle so the bit-lane select matches the byte presented on Q.

`default_nettype none

module mem2048x3 (
  input  wire        clk_i,
  input  wire        enable_n_i,   // active-low access enable (CEN), low on any access
  input  wire        we_i,         // 1 = write, 0 = read
  input  wire        clear_i,      // with we_i: zero all 3 bits of the 8 lines in the row
  input  wire [10:0] addr_i,       // line index, 0..2047
  input  wire [2:0]  wdata_i,      // bits to write for the selected line
  output wire [2:0]  rdata_o       // bits read for the selected line

  `ifdef USE_POWER_PINS
    ,inout wire VDD,
    inout wire VSS
  `endif
);

  wire [7:0] row_addr;
  wire [2:0] bit_lane;

  wire [7:0] onehot;
  wire [7:0] wen;
  wire       gwen;

  wire [7:0] d0, d1, d2;
  wire [7:0] q0, q1, q2;

  assign row_addr = addr_i[10:3];
  assign bit_lane = addr_i[2:0];

  // Active-low per-bit write mask: enable only the addressed bit lane, unless
  // clearing, which enables all eight lanes in the row.
  assign onehot = 8'b1 << bit_lane;
  assign wen    = clear_i ? 8'h00 : ~onehot;

  // Global write enable is active-low; assert (0) only on writes.
  assign gwen = ~we_i;

  // On a normal write the selected bit is replicated across the byte; only the
  // masked lane commits. On a clear the whole byte is driven to zero.
  assign d0 = clear_i ? 8'h00 : {8{wdata_i[0]}};
  assign d1 = clear_i ? 8'h00 : {8{wdata_i[1]}};
  assign d2 = clear_i ? 8'h00 : {8{wdata_i[2]}};

  (* keep *) gf180mcu_fd_ip_sram__sram256x8m8wm1 plane0 (
    .CLK  (clk_i),
    .CEN  (enable_n_i),
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

  (* keep *) gf180mcu_fd_ip_sram__sram256x8m8wm1 plane1 (
    .CLK  (clk_i),
    .CEN  (enable_n_i),
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

  (* keep *) gf180mcu_fd_ip_sram__sram256x8m8wm1 plane2 (
    .CLK  (clk_i),
    .CEN  (enable_n_i),
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
