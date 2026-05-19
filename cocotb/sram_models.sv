
`timescale 1ns/1ps
`default_nettype none

module gf180mcu_fd_ip_sram__sram512x8m8wm1 (
  input  wire       CLK,
  input  wire       CEN,
  input  wire       GWEN,
  input  wire [7:0] WEN,
  input  wire [8:0] A,
  input  wire [7:0] D,
  output reg  [7:0] Q,
  inout  wire       VDD,
  inout  wire       VSS
);
  reg [7:0] mem[0:511];
  integer i;

  initial begin
    Q = 8'h00;
    for (i = 0; i < 512; i = i + 1) begin
      mem[i] = 8'h00;
    end
  end

  always @(posedge CLK) begin
    if (!CEN) begin
      if (!GWEN) begin
        for (i = 0; i < 8; i = i + 1) begin
          if (!WEN[i]) begin
            mem[A][i] <= D[i];
          end
        end
      end
      Q <= mem[A];
    end
  end
endmodule

module gf180mcu_fd_ip_sram__sram64x8m8wm1 (
  input  wire       CLK,
  input  wire       CEN,
  input  wire       GWEN,
  input  wire [7:0] WEN,
  input  wire [5:0] A,
  input  wire [7:0] D,
  output reg  [7:0] Q,
  inout  wire       VDD,
  inout  wire       VSS
);
  reg [7:0] mem[0:63];
  integer i;

  initial begin
    Q = 8'h00;
    for (i = 0; i < 64; i = i + 1) begin
      mem[i] = 8'h00;
    end
  end

  always @(posedge CLK) begin
    if (!CEN) begin
      if (!GWEN) begin
        for (i = 0; i < 8; i = i + 1) begin
          if (!WEN[i]) begin
            mem[A][i] <= D[i];
          end
        end
      end
      Q <= mem[A];
    end
  end
endmodule

`default_nettype wire
