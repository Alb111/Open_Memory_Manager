// SPDX-License-Identifier: Apache-2.0
//
// Metadata only MSI directory controller.
//
// This controller accepts decoded cache side coherence requests from two
// directory_interface blocks, tracks MSI metadata for 128 coherent line
// indices, sends decoded snoop and acknowledgement commands, and updates a
// separate 128 by 6 metadata RAM.
//
// The controller does not connect to main memory. It does not read, write,
// store, or forward 32 bit cache line data. The data fields on directory
// responses are kept for interface compatibility and are driven with zero.

`timescale 1ns/1ps
`default_nettype none

module directory_controller (
  input  logic        clk_i,
  input  logic        rst_ni,

  input  logic        c0_bus_valid_i,
  input  logic [31:0] c0_bus_addr_i,
  input  logic [31:0] c0_bus_wdata_i,
  input  logic [4:0]  c0_bus_cache_cmd_i,
  output logic        c0_bus_ready_o,

  input  logic        c0_snoop_valid_i,
  input  logic [31:0] c0_snoop_data_i,
  input  logic [2:0]  c0_snoop_cache_cmd_i,
  output logic        c0_snoop_ready_o,

  output logic        c0_dir_valid_o,
  output logic [31:0] c0_dir_data_o,
  output logic [31:0] c0_dir_addr_o,
  output logic [5:0]  c0_dir_cmd_o,
  input  logic        c0_dir_ready_i,

  input  logic        c1_bus_valid_i,
  input  logic [31:0] c1_bus_addr_i,
  input  logic [31:0] c1_bus_wdata_i,
  input  logic [4:0]  c1_bus_cache_cmd_i,
  output logic        c1_bus_ready_o,

  input  logic        c1_snoop_valid_i,
  input  logic [31:0] c1_snoop_data_i,
  input  logic [2:0]  c1_snoop_cache_cmd_i,
  output logic        c1_snoop_ready_o,

  output logic        c1_dir_valid_o,
  output logic [31:0] c1_dir_data_o,
  output logic [31:0] c1_dir_addr_o,
  output logic [5:0]  c1_dir_cmd_o,
  input  logic        c1_dir_ready_i,

  output logic        meta_ram_valid_o,
  output logic        meta_ram_instr_o,
  output logic [6:0]  meta_ram_addr_o,
  output logic [5:0]  meta_ram_wdata_o,
  output logic        meta_ram_wstrb_o,
  input  logic [5:0]  meta_ram_rdata_i,
  input  logic        meta_ram_ready_i,

  output logic        dir_state_invalidated_o
);

  localparam logic [4:0] cache_cmd_none_c        = 5'b00000;
  localparam logic [4:0] cache_cmd_bus_rd_c      = 5'b00001;
  localparam logic [4:0] cache_cmd_bus_rdx_c     = 5'b00010;
  localparam logic [4:0] cache_cmd_bus_upgr_c    = 5'b00100;
  localparam logic [4:0] cache_cmd_evict_clean_c = 5'b01000;
  localparam logic [4:0] cache_cmd_evict_dirty_c = 5'b10000;

  localparam logic [2:0] snoop_ack_none_c     = 3'b000;
  localparam logic [2:0] snoop_ack_bus_rd_c   = 3'b001;
  localparam logic [2:0] snoop_ack_bus_rdx_c  = 3'b010;
  localparam logic [2:0] snoop_ack_bus_upgr_c = 3'b100;

  localparam logic [5:0] dir_cmd_none_c          = 6'b000000;
  localparam logic [5:0] dir_cmd_bus_rd_ack_c    = 6'b000001;
  localparam logic [5:0] dir_cmd_bus_rdx_ack_c   = 6'b000010;
  localparam logic [5:0] dir_cmd_bus_upgr_ack_c  = 6'b000100;
  localparam logic [5:0] dir_cmd_snoop_bus_rd_c  = 6'b001000;
  localparam logic [5:0] dir_cmd_snoop_bus_rdx_c = 6'b010000;
  localparam logic [5:0] dir_cmd_snoop_bus_upgr_c = 6'b100000;

  localparam logic [1:0] line_invalid_c  = 2'b00;
  localparam logic [1:0] line_shared_c   = 2'b01;
  localparam logic [1:0] line_modified_c = 2'b10;

  localparam logic [6:0] last_index_c = 7'd127;

  typedef enum logic [3:0] {
    st_init_meta_req,
    st_init_meta_resp,
    st_idle,
    st_read_meta_req,
    st_read_meta_resp,
    st_lookup,
    st_send_snoop,
    st_wait_snoop,
    st_send_ack,
    st_write_meta_req,
    st_write_meta_resp,
    st_done
  } dir_state_e;

  dir_state_e state_q;
  dir_state_e state_d;

  logic [6:0] init_index_q;
  logic [6:0] init_index_d;

  logic dir_state_invalidated_q;
  logic dir_state_invalidated_d;

  logic request_cache_q;
  logic request_cache_d;
  logic [31:0] request_addr_q;
  logic [31:0] request_addr_d;
  logic [31:0] request_data_q;
  logic [31:0] request_data_d;
  logic [4:0] request_cmd_q;
  logic [4:0] request_cmd_d;

  logic [1:0] line_state_q;
  logic [1:0] line_state_d;
  logic [1:0] line_sharers_q;
  logic [1:0] line_sharers_d;
  logic line_owner_q;
  logic line_owner_d;
  logic line_valid_q;
  logic line_valid_d;

  logic pending_ack_cache_q;
  logic pending_ack_cache_d;
  logic [5:0] pending_ack_cmd_q;
  logic [5:0] pending_ack_cmd_d;
  logic [31:0] pending_ack_data_q;
  logic [31:0] pending_ack_data_d;

  logic pending_snoop_cache_q;
  logic pending_snoop_cache_d;
  logic [5:0] pending_snoop_cmd_q;
  logic [5:0] pending_snoop_cmd_d;

  logic pending_write_q;
  logic pending_write_d;
  logic [1:0] pending_write_state_q;
  logic [1:0] pending_write_state_d;
  logic [1:0] pending_write_sharers_q;
  logic [1:0] pending_write_sharers_d;
  logic pending_write_owner_q;
  logic pending_write_owner_d;
  logic pending_write_valid_q;
  logic pending_write_valid_d;

  logic [1:0] arb_req;
  logic [1:0] arb_grant;
  logic [1:0] arb_req_passthrough;
  logic selected_cache;
  logic selected_valid;

  logic requester_bit;
  logic other_bit;
  logic other_is_sharer;
  logic remote_modified_owner;

  logic [6:0] request_index;
  logic [5:0] packed_metadata;

  logic snoop_send_ready;
  logic ack_send_ready;
  logic dirty_flush_accept;
  logic snoop_ack_accept;

  assign arb_req = {c1_bus_valid_i, c0_bus_valid_i};

  wrr_arbiter #(
    .NUM_REQ(2),
    .WEIGHT_W(3),
    .WEIGHTS({3'd1, 3'd1})
  ) u_wrr_arbiter (
    .clk_i(clk_i),
    .rst_ni(rst_ni),
    .req_i(arb_req),
    .grant_o(arb_grant),
    .req_o(arb_req_passthrough)
  );

  assign selected_valid = |arb_grant;
  assign selected_cache = arb_grant[1];

  assign request_index = request_addr_q[6:0];

  assign requester_bit = request_cache_q;
  assign other_bit = !request_cache_q;
  assign other_is_sharer = line_sharers_q[other_bit];

  assign remote_modified_owner =
      (line_state_q == line_modified_c) && (line_owner_q != request_cache_q);

  assign packed_metadata = {
    pending_write_valid_q,
    pending_write_owner_q,
    pending_write_sharers_q,
    pending_write_state_q
  };

  assign snoop_send_ready =
      pending_snoop_cache_q ? c1_dir_ready_i : c0_dir_ready_i;

  assign ack_send_ready =
      pending_ack_cache_q ? c1_dir_ready_i : c0_dir_ready_i;

  assign dirty_flush_accept =
      (state_q == st_wait_snoop) &&
      (pending_snoop_cache_q ? c1_bus_valid_i : c0_bus_valid_i) &&
      ((pending_snoop_cache_q ? c1_bus_cache_cmd_i : c0_bus_cache_cmd_i) ==
       cache_cmd_evict_dirty_c);

  assign snoop_ack_accept =
      (state_q == st_wait_snoop) &&
      (pending_snoop_cache_q ? c1_snoop_valid_i : c0_snoop_valid_i) &&
      ((pending_snoop_cache_q ? c1_snoop_cache_cmd_i : c0_snoop_cache_cmd_i) !=
       snoop_ack_none_c);

  assign dir_state_invalidated_o = dir_state_invalidated_q;

  always_comb begin
    meta_ram_valid_o = 1'b0;
    meta_ram_instr_o = 1'b0;
    meta_ram_addr_o = 7'b0;
    meta_ram_wdata_o = 6'b0;
    meta_ram_wstrb_o = 1'b0;

    unique case (state_q)
      st_init_meta_req, st_init_meta_resp: begin
        meta_ram_valid_o = 1'b1;
        meta_ram_addr_o = init_index_q;
        meta_ram_wdata_o = 6'b000000;
        meta_ram_wstrb_o = 1'b1;
      end

      st_read_meta_req, st_read_meta_resp: begin
        meta_ram_valid_o = 1'b1;
        meta_ram_addr_o = request_index;
        meta_ram_wstrb_o = 1'b0;
      end

      st_write_meta_req, st_write_meta_resp: begin
        meta_ram_valid_o = 1'b1;
        meta_ram_addr_o = request_index;
        meta_ram_wdata_o = packed_metadata;
        meta_ram_wstrb_o = 1'b1;
      end

      default: begin
        meta_ram_valid_o = 1'b0;
        meta_ram_instr_o = 1'b0;
        meta_ram_addr_o = 7'b0;
        meta_ram_wdata_o = 6'b0;
        meta_ram_wstrb_o = 1'b0;
      end
    endcase
  end

  always_comb begin
    c0_bus_ready_o = 1'b0;
    c1_bus_ready_o = 1'b0;

    c0_snoop_ready_o = 1'b0;
    c1_snoop_ready_o = 1'b0;

    c0_dir_valid_o = 1'b0;
    c0_dir_data_o = 32'b0;
    c0_dir_addr_o = 32'b0;
    c0_dir_cmd_o = dir_cmd_none_c;

    c1_dir_valid_o = 1'b0;
    c1_dir_data_o = 32'b0;
    c1_dir_addr_o = 32'b0;
    c1_dir_cmd_o = dir_cmd_none_c;

    if ((state_q == st_idle) && selected_valid) begin
      if (selected_cache) begin
        c1_bus_ready_o = 1'b1;
      end else begin
        c0_bus_ready_o = 1'b1;
      end
    end

    if ((state_q == st_send_snoop) || (state_q == st_wait_snoop)) begin
      if (pending_snoop_cache_q) begin
        c1_dir_valid_o = 1'b1;
        c1_dir_data_o = 32'b0;
        c1_dir_addr_o = request_addr_q;
        c1_dir_cmd_o = pending_snoop_cmd_q;
      end else begin
        c0_dir_valid_o = 1'b1;
        c0_dir_data_o = 32'b0;
        c0_dir_addr_o = request_addr_q;
        c0_dir_cmd_o = pending_snoop_cmd_q;
      end
    end

    if (state_q == st_send_ack) begin
      if (pending_ack_cache_q) begin
        c1_dir_valid_o = 1'b1;
        c1_dir_data_o = pending_ack_data_q;
        c1_dir_addr_o = request_addr_q;
        c1_dir_cmd_o = pending_ack_cmd_q;
      end else begin
        c0_dir_valid_o = 1'b1;
        c0_dir_data_o = pending_ack_data_q;
        c0_dir_addr_o = request_addr_q;
        c0_dir_cmd_o = pending_ack_cmd_q;
      end
    end

    if (dirty_flush_accept) begin
      if (pending_snoop_cache_q) begin
        c1_bus_ready_o = 1'b1;
      end else begin
        c0_bus_ready_o = 1'b1;
      end
    end

    if (snoop_ack_accept) begin
      if (pending_snoop_cache_q) begin
        c1_snoop_ready_o = 1'b1;
      end else begin
        c0_snoop_ready_o = 1'b1;
      end
    end
  end

  always_comb begin
    state_d = state_q;
    init_index_d = init_index_q;
    dir_state_invalidated_d = dir_state_invalidated_q;

    request_cache_d = request_cache_q;
    request_addr_d = request_addr_q;
    request_data_d = request_data_q;
    request_cmd_d = request_cmd_q;

    line_state_d = line_state_q;
    line_sharers_d = line_sharers_q;
    line_owner_d = line_owner_q;
    line_valid_d = line_valid_q;

    pending_ack_cache_d = pending_ack_cache_q;
    pending_ack_cmd_d = pending_ack_cmd_q;
    pending_ack_data_d = pending_ack_data_q;

    pending_snoop_cache_d = pending_snoop_cache_q;
    pending_snoop_cmd_d = pending_snoop_cmd_q;

    pending_write_d = pending_write_q;
    pending_write_state_d = pending_write_state_q;
    pending_write_sharers_d = pending_write_sharers_q;
    pending_write_owner_d = pending_write_owner_q;
    pending_write_valid_d = pending_write_valid_q;

    unique case (state_q)
      st_init_meta_req: begin
        if (meta_ram_ready_i) begin
          state_d = st_init_meta_resp;
        end
      end

      st_init_meta_resp: begin
        if (meta_ram_ready_i) begin
          if (init_index_q == last_index_c) begin
            dir_state_invalidated_d = 1'b1;
            state_d = st_idle;
          end else begin
            init_index_d = init_index_q + 7'd1;
            state_d = st_init_meta_req;
          end
        end
      end

      st_idle: begin
        pending_write_d = 1'b0;
        pending_ack_cmd_d = dir_cmd_none_c;
        pending_ack_data_d = 32'b0;
        pending_snoop_cmd_d = dir_cmd_none_c;

        if (selected_valid) begin
          request_cache_d = selected_cache;
          request_addr_d = selected_cache ? c1_bus_addr_i : c0_bus_addr_i;
          request_data_d = selected_cache ? c1_bus_wdata_i : c0_bus_wdata_i;
          request_cmd_d = selected_cache ? c1_bus_cache_cmd_i :
                                            c0_bus_cache_cmd_i;
          state_d = st_read_meta_req;
        end
      end

      st_read_meta_req: begin
        if (meta_ram_ready_i) begin
          state_d = st_read_meta_resp;
        end
      end

      st_read_meta_resp: begin
        if (meta_ram_ready_i) begin
          line_state_d = meta_ram_rdata_i[1:0];
          line_sharers_d = meta_ram_rdata_i[3:2];
          line_owner_d = meta_ram_rdata_i[4];
          line_valid_d = meta_ram_rdata_i[5];
          state_d = st_lookup;
        end
      end

      st_lookup: begin
        pending_ack_cache_d = request_cache_q;
        pending_ack_cmd_d = dir_cmd_none_c;
        pending_ack_data_d = 32'b0;

        pending_snoop_cache_d = other_bit;
        pending_snoop_cmd_d = dir_cmd_none_c;

        pending_write_d = 1'b0;
        pending_write_state_d = line_state_q;
        pending_write_sharers_d = line_sharers_q;
        pending_write_owner_d = line_owner_q;
        pending_write_valid_d = line_valid_q;

        unique case (request_cmd_q)
          cache_cmd_bus_rd_c: begin
            if (remote_modified_owner) begin
              pending_snoop_cache_d = line_owner_q;
              pending_snoop_cmd_d = dir_cmd_snoop_bus_rd_c;
              state_d = st_send_snoop;
            end else begin
              pending_ack_cmd_d = dir_cmd_bus_rd_ack_c;
              pending_ack_data_d = 32'b0;

              pending_write_d = 1'b1;
              pending_write_state_d = line_shared_c;
              pending_write_sharers_d =
                  line_sharers_q | (request_cache_q ? 2'b10 : 2'b01);
              pending_write_owner_d = 1'b0;
              pending_write_valid_d = 1'b1;
              state_d = st_send_ack;
            end
          end

          cache_cmd_bus_rdx_c: begin
            if (remote_modified_owner) begin
              pending_snoop_cache_d = line_owner_q;
              pending_snoop_cmd_d = dir_cmd_snoop_bus_rdx_c;
              state_d = st_send_snoop;
            end else if ((line_state_q == line_shared_c) && other_is_sharer) begin
              pending_snoop_cache_d = other_bit;
              pending_snoop_cmd_d = dir_cmd_snoop_bus_upgr_c;
              state_d = st_send_snoop;
            end else begin
              pending_ack_cmd_d = dir_cmd_bus_rdx_ack_c;
              pending_ack_data_d = 32'b0;

              pending_write_d = 1'b1;
              pending_write_state_d = line_modified_c;
              pending_write_sharers_d = 2'b00;
              pending_write_owner_d = request_cache_q;
              pending_write_valid_d = 1'b1;
              state_d = st_send_ack;
            end
          end

          cache_cmd_bus_upgr_c: begin
            if ((line_state_q == line_shared_c) && other_is_sharer) begin
              pending_snoop_cache_d = other_bit;
              pending_snoop_cmd_d = dir_cmd_snoop_bus_upgr_c;
              state_d = st_send_snoop;
            end else begin
              pending_ack_cmd_d = dir_cmd_bus_upgr_ack_c;
              pending_ack_data_d = 32'b0;

              pending_write_d = 1'b1;
              pending_write_state_d = line_modified_c;
              pending_write_sharers_d = 2'b00;
              pending_write_owner_d = request_cache_q;
              pending_write_valid_d = 1'b1;
              state_d = st_send_ack;
            end
          end

          cache_cmd_evict_clean_c: begin
            pending_write_d = 1'b1;
            pending_write_sharers_d =
                line_sharers_q & ~(request_cache_q ? 2'b10 : 2'b01);
            pending_write_owner_d = 1'b0;

            if (pending_write_sharers_d == 2'b00) begin
              pending_write_state_d = line_invalid_c;
              pending_write_valid_d = 1'b0;
            end else begin
              pending_write_state_d = line_shared_c;
              pending_write_valid_d = 1'b1;
            end

            state_d = st_write_meta_req;
          end

          cache_cmd_evict_dirty_c: begin
            pending_write_d = 1'b1;
            pending_write_state_d = line_invalid_c;
            pending_write_sharers_d = 2'b00;
            pending_write_owner_d = 1'b0;
            pending_write_valid_d = 1'b0;
            state_d = st_write_meta_req;
          end

          default: begin
            state_d = st_idle;
          end
        endcase
      end

      st_send_snoop: begin
        if (snoop_send_ready) begin
          state_d = st_wait_snoop;
        end
      end

      st_wait_snoop: begin
        if (snoop_ack_accept) begin
          pending_ack_cache_d = request_cache_q;
          pending_ack_data_d = 32'b0;

          unique case (request_cmd_q)
            cache_cmd_bus_rd_c: begin
              pending_ack_cmd_d = dir_cmd_bus_rd_ack_c;

              pending_write_d = 1'b1;
              pending_write_state_d = line_shared_c;
              pending_write_sharers_d =
                  (request_cache_q ? 2'b10 : 2'b01) |
                  (pending_snoop_cache_q ? 2'b10 : 2'b01);
              pending_write_owner_d = 1'b0;
              pending_write_valid_d = 1'b1;
            end

            cache_cmd_bus_rdx_c: begin
              pending_ack_cmd_d = dir_cmd_bus_rdx_ack_c;

              pending_write_d = 1'b1;
              pending_write_state_d = line_modified_c;
              pending_write_sharers_d = 2'b00;
              pending_write_owner_d = request_cache_q;
              pending_write_valid_d = 1'b1;
            end

            cache_cmd_bus_upgr_c: begin
              pending_ack_cmd_d = dir_cmd_bus_upgr_ack_c;

              pending_write_d = 1'b1;
              pending_write_state_d = line_modified_c;
              pending_write_sharers_d = 2'b00;
              pending_write_owner_d = request_cache_q;
              pending_write_valid_d = 1'b1;
            end

            default: begin
              pending_ack_cmd_d = dir_cmd_none_c;
              pending_write_d = 1'b0;
            end
          endcase

          state_d = st_send_ack;
        end
      end

      st_send_ack: begin
        if (ack_send_ready) begin
          if (pending_write_q) begin
            state_d = st_write_meta_req;
          end else begin
            state_d = st_idle;
          end
        end
      end

      st_write_meta_req: begin
        if (meta_ram_ready_i) begin
          state_d = st_write_meta_resp;
        end
      end

      st_write_meta_resp: begin
        if (meta_ram_ready_i) begin
          state_d = st_done;
        end
      end

      st_done: begin
        state_d = st_idle;
      end

      default: begin
        state_d = st_idle;
      end
    endcase
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= st_init_meta_req;
      init_index_q <= 7'd0;
      dir_state_invalidated_q <= 1'b0;

      request_cache_q <= 1'b0;
      request_addr_q <= 32'b0;
      request_data_q <= 32'b0;
      request_cmd_q <= cache_cmd_none_c;

      line_state_q <= line_invalid_c;
      line_sharers_q <= 2'b00;
      line_owner_q <= 1'b0;
      line_valid_q <= 1'b0;

      pending_ack_cache_q <= 1'b0;
      pending_ack_cmd_q <= dir_cmd_none_c;
      pending_ack_data_q <= 32'b0;

      pending_snoop_cache_q <= 1'b0;
      pending_snoop_cmd_q <= dir_cmd_none_c;

      pending_write_q <= 1'b0;
      pending_write_state_q <= line_invalid_c;
      pending_write_sharers_q <= 2'b00;
      pending_write_owner_q <= 1'b0;
      pending_write_valid_q <= 1'b0;
    end else begin
      state_q <= state_d;
      init_index_q <= init_index_d;
      dir_state_invalidated_q <= dir_state_invalidated_d;

      request_cache_q <= request_cache_d;
      request_addr_q <= request_addr_d;
      request_data_q <= request_data_d;
      request_cmd_q <= request_cmd_d;

      line_state_q <= line_state_d;
      line_sharers_q <= line_sharers_d;
      line_owner_q <= line_owner_d;
      line_valid_q <= line_valid_d;

      pending_ack_cache_q <= pending_ack_cache_d;
      pending_ack_cmd_q <= pending_ack_cmd_d;
      pending_ack_data_q <= pending_ack_data_d;

      pending_snoop_cache_q <= pending_snoop_cache_d;
      pending_snoop_cmd_q <= pending_snoop_cmd_d;

      pending_write_q <= pending_write_d;
      pending_write_state_q <= pending_write_state_d;
      pending_write_sharers_q <= pending_write_sharers_d;
      pending_write_owner_q <= pending_write_owner_d;
      pending_write_valid_q <= pending_write_valid_d;
    end
  end

endmodule : directory_controller

`default_nettype wire

