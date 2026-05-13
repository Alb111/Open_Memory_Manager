// SPDX-FileCopyrightText: © 2025 Albert Felix
// SPDX-License-Identifier: Apache-2.0
//
// apply_wstrb
// Merges CPU write data onto a base word using byte-enable strobes.
// Equivalent to Python util.apply_wstrb(base, wdata, wstrb).
//
//   result[7:0]   = wstrb[0] ? wdata[7:0]   : base_data[7:0]
//   result[15:8]  = wstrb[1] ? wdata[15:8]  : base_data[15:8]
//   result[23:16] = wstrb[2] ? wdata[23:16] : base_data[23:16]
//   result[31:24] = wstrb[3] ? wdata[31:24] : base_data[31:24]

`timescale 1ns/1ps
`default_nettype none

module apply_wstrb
(
  input  logic [31:0] base_data_i,
  input  logic [31:0] wdata_i,
  input  logic [3:0]  wstrb_i,
  output logic [31:0] result_o
);

  assign result_o[7:0]   = wstrb_i[0] ? wdata_i[7:0]   : base_data_i[7:0];
  assign result_o[15:8]  = wstrb_i[1] ? wdata_i[15:8]  : base_data_i[15:8];
  assign result_o[23:16] = wstrb_i[2] ? wdata_i[23:16] : base_data_i[23:16];
  assign result_o[31:24] = wstrb_i[3] ? wdata_i[31:24] : base_data_i[31:24];

endmodule

`default_nettype wire
