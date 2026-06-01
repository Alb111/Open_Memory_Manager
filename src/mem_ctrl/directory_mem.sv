// SPDX-FileCopyrightText: © 2025 XXX Authors
// SPDX-License-Identifier: Apache-2.0

`default_nettype none

module directory_mem
(
  input  wire        clk_i,
  input  wire        rst_ni,

  // Directory controller request interface.
  input  wire        valid_i,
  output logic       ready_o,
  input  wire [31:0] addr_i,
  input  wire [3:0]  wstrb_i,

  input  wire [31:0] w_data_i,
  input  wire [1:0]  w_state_i,
  input  wire [1:0]  w_sharers_i,
  input  wire [0:0]  w_owner_i,
  input  wire [0:0]  w_valid_data_i,

  output logic [31:0] r_data_o,
  output logic [1:0]  r_state_o,
  output logic [1:0]  r_tag_o,
  output logic [1:0]  r_owner_o,
  output logic [1:0]  r_valid_data_o,
  input  wire         ready_i,

  // Main-memory side for backup data lines.
  output logic [0:0]  main_mem_valid_o,
  output logic [0:0]  main_mem_instr_o,
  output logic [31:0] main_mem_addr_o,
  output logic [31:0] main_mem_wdata_o,
  output logic [3:0]  main_mem_wstrb_o,
  input  wire [31:0]  main_mem_rdata_i,
  input  wire [0:0]   main_mem_ready_i

  `ifdef USE_POWER_PINS
    ,inout wire VDD,
    inout wire VSS
  `endif
);

  typedef enum logic [1:0] {
    StIdle,
    StMetaResp,
    StMainReq,
    StMainResp
  } state_t;

  state_t state_q;
  state_t state_d;

  logic [31:0] addr_q;
  logic [31:0] w_data_q;
  logic [3:0]  wstrb_q;
  logic [1:0]  w_state_q;
  logic [1:0]  w_sharers_q;
  logic        w_owner_q;
  logic        w_valid_data_q;

  logic        accept_req;
  logic        metadata_access;
  logic        metadata_write;

  logic        sram_enable_n;
  logic [2:0]  sram_gwen;
  logic [23:0] sram_wen;
  logic [5:0]  sram_addr;
  logic [23:0] sram_wdata;
  logic [23:0] sram_rdata;

  logic [1:0]  metadata_state_read;
  logic [1:0]  metadata_sharers_read;
  logic [1:0]  metadata_owner_valid_read;

  function automatic logic [7:0] pack_lane(input logic [1:0] value, input logic lane);
    begin
      pack_lane = 8'h00;
      if (lane) begin
        pack_lane[3:2] = value;
      end else begin
        pack_lane[1:0] = value;
      end
    end
  endfunction

  function automatic logic [7:0] lane_wen(input logic lane);
    begin
      lane_wen = 8'hff;
      if (lane) begin
        lane_wen[3:2] = 2'b00;
      end else begin
        lane_wen[1:0] = 2'b00;
      end
    end
  endfunction

  function automatic logic [1:0] unpack_lane(input logic [7:0] word, input logic lane);
    begin
      if (lane) begin
        unpack_lane = word[3:2];
      end else begin
        unpack_lane = word[1:0];
      end
    end
  endfunction

  assign accept_req      = (state_q == StIdle) && valid_i;
  assign metadata_access = (addr_i[31:7] == 25'b0);
  assign metadata_write  = metadata_access && (wstrb_i != 4'b0000);

  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      state_q        <= StIdle;
      addr_q         <= 32'b0;
      w_data_q       <= 32'b0;
      wstrb_q        <= 4'b0000;
      w_state_q      <= 2'b00;
      w_sharers_q    <= 2'b00;
      w_owner_q      <= 1'b0;
      w_valid_data_q <= 1'b0;
    end else begin
      state_q <= state_d;

      if (accept_req) begin
        addr_q         <= addr_i;
        w_data_q       <= w_data_i;
        wstrb_q        <= wstrb_i;
        w_state_q      <= w_state_i;
        w_sharers_q    <= w_sharers_i;
        w_owner_q      <= w_owner_i[0];
        w_valid_data_q <= w_valid_data_i[0];
      end
    end
  end

  always_comb begin
    state_d = state_q;

    unique case (state_q)
      StIdle: begin
        if (valid_i) begin
          if (metadata_access) begin
            state_d = StMetaResp;
          end else if (main_mem_ready_i[0]) begin
            state_d = StMainResp;
          end else begin
            state_d = StMainReq;
          end
        end
      end

      StMainReq: begin
        if (main_mem_ready_i[0]) begin
          state_d = StMainResp;
        end
      end

      StMetaResp,
      StMainResp: begin
        if (ready_i) begin
          state_d = StIdle;
        end
      end

      default: begin
        state_d = StIdle;
      end
    endcase
  end

  assign ready_o = (state_q == StIdle) ||
                   (((state_q == StMetaResp) || (state_q == StMainResp)) && ready_i);

  // Keep the SRAM command asserted through the response state so the GF180
  // macro sees stable controls across its delayed internal clock path.
  always_comb begin
    sram_enable_n = 1'b1;
    sram_gwen     = 3'b111;
    sram_wen      = 24'hff_ffff;
    sram_addr     = addr_q[6:1];
    sram_wdata    = 24'b0;

    if (accept_req && metadata_access) begin
      sram_enable_n = 1'b0;
      sram_addr     = addr_i[6:1];

      if (metadata_write) begin
        sram_gwen  = 3'b000;
        sram_wen   = {lane_wen(addr_i[0]), lane_wen(addr_i[0]), lane_wen(addr_i[0])};
        sram_wdata = {
          pack_lane({w_valid_data_i[0], w_owner_i[0]}, addr_i[0]),
          pack_lane(w_sharers_i, addr_i[0]),
          pack_lane(w_state_i, addr_i[0])
        };
      end
    end else if (state_q == StMetaResp) begin
      sram_enable_n = 1'b0;

      if (wstrb_q != 4'b0000) begin
        sram_gwen  = 3'b000;
        sram_wen   = {lane_wen(addr_q[0]), lane_wen(addr_q[0]), lane_wen(addr_q[0])};
        sram_wdata = {
          pack_lane({w_valid_data_q, w_owner_q}, addr_q[0]),
          pack_lane(w_sharers_q, addr_q[0]),
          pack_lane(w_state_q, addr_q[0])
        };
      end
    end
  end

  metadata_sram64x8_array i_metadata_sram64x8_array (
    .clk_i        (clk_i),
    .enable_n_i   (sram_enable_n),
    .gwen_i       (sram_gwen),
    .wen_i        (sram_wen),
    .addr_i       (sram_addr),
    .wdata_i      (sram_wdata),
    .rdata_o      (sram_rdata)
    `ifdef USE_POWER_PINS
      ,.VDD       (VDD)
      ,.VSS       (VSS)
    `endif
  );

  assign metadata_state_read       = unpack_lane(sram_rdata[7:0],   addr_q[0]);
  assign metadata_sharers_read     = unpack_lane(sram_rdata[15:8],  addr_q[0]);
  assign metadata_owner_valid_read = unpack_lane(sram_rdata[23:16], addr_q[0]);

  always_comb begin
    r_data_o       = 32'b0;
    r_state_o      = 2'b00;
    r_tag_o        = 2'b00;
    r_owner_o      = 2'b00;
    r_valid_data_o = 2'b00;

    unique case (state_q)
      StMetaResp: begin
        if (wstrb_q != 4'b0000) begin
          r_state_o      = w_state_q;
          r_tag_o        = w_sharers_q;
          r_owner_o      = {1'b0, w_owner_q};
          r_valid_data_o = {1'b0, w_valid_data_q};
        end else begin
          r_state_o      = metadata_state_read;
          r_tag_o        = metadata_sharers_read;
          r_owner_o      = {1'b0, metadata_owner_valid_read[0]};
          r_valid_data_o = {1'b0, metadata_owner_valid_read[1]};
        end
      end

      StMainResp: begin
        r_data_o = main_mem_rdata_i;
      end

      default: begin
        r_data_o       = 32'b0;
        r_state_o      = 2'b00;
        r_tag_o        = 2'b00;
        r_owner_o      = 2'b00;
        r_valid_data_o = 2'b00;
      end
    endcase
  end

  always_comb begin
    main_mem_valid_o = 1'b0;
    main_mem_instr_o = 1'b0;
    main_mem_addr_o  = addr_q;
    main_mem_wdata_o = w_data_q;
    main_mem_wstrb_o = wstrb_q;

    if (accept_req && !metadata_access) begin
      main_mem_valid_o = 1'b1;
      main_mem_addr_o  = addr_i;
      main_mem_wdata_o = w_data_i;
      main_mem_wstrb_o = wstrb_i;
    end else if (state_q == StMainReq) begin
      main_mem_valid_o = 1'b1;
    end
  end

endmodule

`default_nettype wire
