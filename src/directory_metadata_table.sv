// SPDX-License-Identifier: Apache-2.0
//
// Memory backed directory metadata storage for a two-cache directory controller.

`timescale 1ns/1ps
`default_nettype none

module directory_metadata_table (
  input  logic        clk_i,
  input  logic        rst_ni,

  input  logic        read_valid_i,
  output logic        read_ready_o,
  input  logic [6:0]  read_index_i,
  output logic        read_valid_o,
  input  logic        read_ready_i,
  output logic [1:0]  read_state_o,
  output logic [1:0]  read_sharers_o,
  output logic        read_owner_o,
  output logic        read_data_valid_o,
  output logic [31:0] read_data_o,

  input  logic        write_valid_i,
  output logic        write_ready_o,
  input  logic [6:0]  write_index_i,
  input  logic [1:0]  write_state_i,
  input  logic [1:0]  write_sharers_i,
  input  logic        write_owner_i,
  input  logic        write_data_valid_i,
  input  logic [31:0] write_data_i,
  output logic        write_done_valid_o,
  input  logic        write_done_ready_i,

  input  logic        status_valid_i,
  output logic        status_ready_o,
  input  logic [6:0]  status_index_i,
  output logic        status_valid_o,
  input  logic        status_ready_i,
  output logic [1:0]  status_state_o,
  output logic [1:0]  status_sharers_o,
  output logic        status_owner_o,
  output logic        status_data_valid_o,
  output logic [31:0] status_data_o
);

  localparam logic [2:0] StIdle       = 3'd0;
  localparam logic [2:0] StReadResp   = 3'd1;
  localparam logic [2:0] StWriteResp  = 3'd2;
  localparam logic [2:0] StStatusResp = 3'd3;

  logic [2:0] state_q;
  logic [2:0] state_d;

  logic        metadata_mem_valid;
  logic        metadata_mem_ready;
  logic [31:0] metadata_mem_addr;
  logic [31:0] metadata_mem_wdata;
  logic [3:0]  metadata_mem_wstrb;
  logic [31:0] metadata_mem_rdata;
  logic        metadata_mem_resp_valid;
  logic        metadata_mem_resp_ready;

  logic        data_mem_valid;
  logic        data_mem_ready;
  logic [31:0] data_mem_addr;
  logic [31:0] data_mem_wdata;
  logic [3:0]  data_mem_wstrb;
  logic [31:0] data_mem_rdata;
  logic        data_mem_resp_valid;
  logic        data_mem_resp_ready;

  logic        memories_ready;
  logic        memories_resp_valid;
  logic [31:0] selected_addr;
  logic [31:0] packed_metadata;

  assign memories_ready = metadata_mem_ready && data_mem_ready;
  assign memories_resp_valid = metadata_mem_resp_valid && data_mem_resp_valid;

  always_comb begin
    selected_addr = {25'b0, read_index_i};

    if (write_valid_i) begin
      selected_addr = {25'b0, write_index_i};
    end else if (read_valid_i) begin
      selected_addr = {25'b0, read_index_i};
    end else if (status_valid_i) begin
      selected_addr = {25'b0, status_index_i};
    end
  end

  assign packed_metadata = {
      26'b0,
      write_data_valid_i,
      write_owner_i,
      write_sharers_i,
      write_state_i
  };

  assign read_ready_o = (state_q == StIdle) && memories_ready && !write_valid_i;
  assign write_ready_o = (state_q == StIdle) && memories_ready;
  assign status_ready_o = (state_q == StIdle) && memories_ready &&
                          !write_valid_i && !read_valid_i;

  assign read_valid_o = (state_q == StReadResp) && memories_resp_valid;
  assign write_done_valid_o = (state_q == StWriteResp) && memories_resp_valid;
  assign status_valid_o = (state_q == StStatusResp) && memories_resp_valid;

  assign read_state_o = metadata_mem_rdata[1:0];
  assign read_sharers_o = metadata_mem_rdata[3:2];
  assign read_owner_o = metadata_mem_rdata[4];
  assign read_data_valid_o = metadata_mem_rdata[5];
  assign read_data_o = data_mem_rdata;

  assign status_state_o = metadata_mem_rdata[1:0];
  assign status_sharers_o = metadata_mem_rdata[3:2];
  assign status_owner_o = metadata_mem_rdata[4];
  assign status_data_valid_o = metadata_mem_rdata[5];
  assign status_data_o = data_mem_rdata;

  always_comb begin
    state_d = state_q;

    unique case (state_q)
      StIdle: begin
        if (write_valid_i && write_ready_o) begin
          state_d = StWriteResp;
        end else if (read_valid_i && read_ready_o) begin
          state_d = StReadResp;
        end else if (status_valid_i && status_ready_o) begin
          state_d = StStatusResp;
        end
      end

      StReadResp: begin
        if (read_valid_o && read_ready_i) begin
          state_d = StIdle;
        end
      end

      StWriteResp: begin
        if (write_done_valid_o && write_done_ready_i) begin
          state_d = StIdle;
        end
      end

      StStatusResp: begin
        if (status_valid_o && status_ready_i) begin
          state_d = StIdle;
        end
      end

      default: begin
        state_d = StIdle;
      end
    endcase
  end

  always_comb begin
    metadata_mem_valid = 1'b0;
    metadata_mem_addr = selected_addr;
    metadata_mem_wdata = 32'b0;
    metadata_mem_wstrb = 4'b0000;

    data_mem_valid = 1'b0;
    data_mem_addr = selected_addr;
    data_mem_wdata = 32'b0;
    data_mem_wstrb = 4'b0000;

    if (state_q == StIdle) begin
      if (write_valid_i && memories_ready) begin
        metadata_mem_valid = 1'b1;
        metadata_mem_wdata = packed_metadata;
        metadata_mem_wstrb = 4'b1111;

        data_mem_valid = 1'b1;
        data_mem_wdata = write_data_i;
        data_mem_wstrb = 4'b1111;
      end else if (read_valid_i && memories_ready && !write_valid_i) begin
        metadata_mem_valid = 1'b1;
        data_mem_valid = 1'b1;
      end else if (status_valid_i && memories_ready && !write_valid_i && !read_valid_i) begin
        metadata_mem_valid = 1'b1;
        data_mem_valid = 1'b1;
      end
    end
  end

  always_comb begin
    metadata_mem_resp_ready = 1'b0;
    data_mem_resp_ready = 1'b0;

    unique case (state_q)
      StReadResp: begin
        metadata_mem_resp_ready = read_ready_i;
        data_mem_resp_ready = read_ready_i;
      end

      StWriteResp: begin
        metadata_mem_resp_ready = write_done_ready_i;
        data_mem_resp_ready = write_done_ready_i;
      end

      StStatusResp: begin
        metadata_mem_resp_ready = status_ready_i;
        data_mem_resp_ready = status_ready_i;
      end

      default: begin
        metadata_mem_resp_ready = 1'b0;
        data_mem_resp_ready = 1'b0;
      end
    endcase
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= StIdle;
    end else begin
      state_q <= state_d;
    end
  end

  mem_ctrl_128x32 u_metadata_mem (
    .clk_i,
    .rst_ni,

    .mem_valid_i(metadata_mem_valid),
    .mem_ready_o(metadata_mem_ready),
    .mem_addr_i (metadata_mem_addr),
    .mem_wdata_i(metadata_mem_wdata),
    .mem_wstrb_i(metadata_mem_wstrb),

    .mem_rdata_o(metadata_mem_rdata),
    .mem_valid_o(metadata_mem_resp_valid),
    .mem_ready_i(metadata_mem_resp_ready)
  );

  mem_ctrl_128x32 u_data_mem (
    .clk_i,
    .rst_ni,

    .mem_valid_i(data_mem_valid),
    .mem_ready_o(data_mem_ready),
    .mem_addr_i (data_mem_addr),
    .mem_wdata_i(data_mem_wdata),
    .mem_wstrb_i(data_mem_wstrb),

    .mem_rdata_o(data_mem_rdata),
    .mem_valid_o(data_mem_resp_valid),
    .mem_ready_i(data_mem_resp_ready)
  );

endmodule : directory_metadata_table

`default_nettype wire

