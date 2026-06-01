// SPDX-FileCopyrightText: © 2025 XXX Authors
// SPDX-License-Identifier: Apache-2.0

`default_nettype none

module metadata_sram64x8_array (
  `ifdef USE_POWER_PINS
    inout wire VDD,
    inout wire VSS
  `endif
);

    wire [7:0] spare_q0;
    wire [7:0] spare_q1;
    wire [7:0] spare_q2;

    (* keep *) gf180mcu_fd_ip_sram__sram64x8m8wm1 sram0 (
        .CLK  (1'b0),
        .CEN  (1'b1),
        .GWEN (1'b1),
        .WEN  (8'hff),
        .A    (6'h00),
        .D    (8'h00),
        .Q    (spare_q0)
        `ifdef USE_POWER_PINS
        ,.VDD (VDD)
        ,.VSS (VSS)
        `endif
    );

    (* keep *) gf180mcu_fd_ip_sram__sram64x8m8wm1 sram1 (
        .CLK  (1'b0),
        .CEN  (1'b1),
        .GWEN (1'b1),
        .WEN  (8'hff),
        .A    (6'h00),
        .D    (8'h00),
        .Q    (spare_q1)
        `ifdef USE_POWER_PINS
        ,.VDD (VDD)
        ,.VSS (VSS)
        `endif
    );

    (* keep *) gf180mcu_fd_ip_sram__sram64x8m8wm1 sram2 (
        .CLK  (1'b0),
        .CEN  (1'b1),
        .GWEN (1'b1),
        .WEN  (8'hff),
        .A    (6'h00),
        .D    (8'h00),
        .Q    (spare_q2)
        `ifdef USE_POWER_PINS
        ,.VDD (VDD)
        ,.VSS (VSS)
        `endif
    );

    wire _unused;
    assign _unused = &{spare_q0, spare_q1, spare_q2};

endmodule

`default_nettype wire
