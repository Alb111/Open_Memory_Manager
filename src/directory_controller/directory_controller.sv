// SPDX-License-Identifier: Apache-2.0
//
// Directory controller for a two-core MSI directory.
//
// The controller accepts decoded requests from two directory_interface
// instances, arbitrates between them with wrr_arbiter, applies MSI metadata
// updates, and sends decoded responses back to the interfaces.
//
// All directory storage is accessed through the directory_mem abstraction. The
// directory_mem block is responsible for routing metadata accesses to the
// 128x6 metadata SRAM and backup data accesses to main memory.
//
// Address map used by this controller:
//   0 to 127     : metadata entries in directory_mem
//   1792 to 1919 : cache 0 backup data words
//   1920 to 2047 : cache 1 backup data words

`timescale 1ns/1ps
`default_nettype none

module directory_controller (
  input  logic        clk_i,
  input  logic        rst_ni,

  // Cache 0 request path from directory_interface.
  input  logic        c0_bus_valid_i,
  input  logic [31:0] c0_bus_addr_i,
  input  logic [31:0] c0_bus_wdata_i,
  input  logic [4:0]  c0_bus_cache_cmd_i,
  output logic        c0_bus_ready_o,

  // Cache 0 snoop acknowledgement path from directory_interface.
  input  logic        c0_snoop_valid_i,
  input  logic [31:0] c0_snoop_data_i,
  input  logic [2:0]  c0_snoop_cache_cmd_i,
  output logic        c0_snoop_ready_o,

  // Cache 0 directory response path to directory_interface.
  output logic        c0_dir_valid_o,
  output logic [31:0] c0_dir_data_o,
  output logic [31:0] c0_dir_addr_o,
  output logic [5:0]  c0_dir_cmd_o,
  input  logic        c0_dir_ready_i,

  // Cache 1 request path from directory_interface.
  input  logic        c1_bus_valid_i,
  input  logic [31:0] c1_bus_addr_i,
  input  logic [31:0] c1_bus_wdata_i,
  input  logic [4:0]  c1_bus_cache_cmd_i,
  output logic        c1_bus_ready_o,

  // Cache 1 snoop acknowledgement path from directory_interface.
  input  logic        c1_snoop_valid_i,
  input  logic [31:0] c1_snoop_data_i,
  input  logic [2:0]  c1_snoop_cache_cmd_i,
  output logic        c1_snoop_ready_o,

  // Cache 1 directory response path to directory_interface.
  output logic        c1_dir_valid_o,
  output logic [31:0] c1_dir_data_o,
  output logic [31:0] c1_dir_addr_o,
  output logic [5:0]  c1_dir_cmd_o,
  input  logic        c1_dir_ready_i,

  // Unified directory_mem request interface.
  output logic        dir_mem_valid_o,
  input  logic        dir_mem_ready_i,
  output logic [31:0] dir_mem_addr_o,
  output logic [3:0]  dir_mem_wstrb_o,
  output logic [31:0] dir_mem_w_data_o,
  output logic [1:0]  dir_mem_w_state_o,
  output logic [1:0]  dir_mem_w_sharers_o,
  output logic        dir_mem_w_owner_o,
  output logic        dir_mem_w_valid_data_o,

  // Unified directory_mem read response interface.
  input  logic [31:0] dir_mem_r_data_i,
  input  logic [1:0]  dir_mem_r_state_i,
  input  logic [1:0]  dir_mem_r_sharers_i,
  input  logic [1:0]  dir_mem_r_owner_i,
  input  logic [1:0]  dir_mem_r_valid_data_i,
  output logic        dir_mem_resp_ready_o,

  // Asserted after reset-time metadata invalidation has completed.
  output logic        dir_state_invalidated_o
);

  localparam logic [4:0] CACHE_CMD_NONE        = 5'b00000;
  localparam logic [4:0] CACHE_CMD_BUS_RD      = 5'b00001;
  localparam logic [4:0] CACHE_CMD_BUS_RDX     = 5'b00010;
  localparam logic [4:0] CACHE_CMD_BUS_UPGR    = 5'b00100;
  localparam logic [4:0] CACHE_CMD_EVICT_CLEAN = 5'b01000;
  localparam logic [4:0] CACHE_CMD_EVICT_DIRTY = 5'b10000;

  localparam logic [2:0] SNOOP_ACK_NONE = 3'b000;

  localparam logic [5:0] DIR_CMD_NONE           = 6'b000000;
  localparam logic [5:0] DIR_CMD_BUS_RD_ACK     = 6'b000001;
  localparam logic [5:0] DIR_CMD_BUS_RDX_ACK    = 6'b000010;
  localparam logic [5:0] DIR_CMD_BUS_UPGR_ACK   = 6'b000100;
  localparam logic [5:0] DIR_CMD_SNOOP_BUS_RD   = 6'b001000;
  localparam logic [5:0] DIR_CMD_SNOOP_BUS_RDX  = 6'b010000;
  localparam logic [5:0] DIR_CMD_SNOOP_BUS_UPGR = 6'b100000;

  localparam logic [1:0] LINE_INVALID  = 2'b00;
  localparam logic [1:0] LINE_SHARED   = 2'b01;
  localparam logic [1:0] LINE_MODIFIED = 2'b10;

  localparam logic [6:0]  LAST_INDEX              = 7'd127;
  localparam logic [31:0] CACHE0_BACKUP_BASE_WORD = 32'd1792;
  localparam logic [31:0] CACHE1_BACKUP_BASE_WORD = 32'd1920;

  typedef enum logic [4:0] {
    StInitMetaReq,
    StInitMetaResp,
    StIdle,
    StReadMetaReq,
    StReadMetaResp,
    StLookup,
    StReadBackupReq,
    StReadBackupResp,
    StSendSnoop,
    StWaitSnoop,
    StSendAck,
    StWriteBackup0Req,
    StWriteBackup0Resp,
    StWriteBackup1Req,
    StWriteBackup1Resp,
    StWriteMetaReq,
    StWriteMetaResp,
    StDone
  } dir_state_e;

  dir_state_e state_d;
  dir_state_e state_q;

  logic [6:0] init_index_d;
  logic [6:0] init_index_q;

  logic dir_state_invalidated_d;
  logic dir_state_invalidated_q;

  logic        request_cache_d;
  logic        request_cache_q;
  logic [31:0] request_addr_d;
  logic [31:0] request_addr_q;
  logic [31:0] request_data_d;
  logic [31:0] request_data_q;
  logic [4:0]  request_cmd_d;
  logic [4:0]  request_cmd_q;

  logic [1:0] line_state_d;
  logic [1:0] line_state_q;
  logic [1:0] line_sharers_d;
  logic [1:0] line_sharers_q;
  logic       line_owner_d;
  logic       line_owner_q;
  logic       line_valid_d;
  logic       line_valid_q;

  logic        pending_ack_cache_d;
  logic        pending_ack_cache_q;
  logic [5:0]  pending_ack_cmd_d;
  logic [5:0]  pending_ack_cmd_q;
  logic [31:0] pending_ack_data_d;
  logic [31:0] pending_ack_data_q;

  logic       pending_snoop_cache_d;
  logic       pending_snoop_cache_q;
  logic [5:0] pending_snoop_cmd_d;
  logic [5:0] pending_snoop_cmd_q;

  logic       pending_write_d;
  logic       pending_write_q;
  logic [1:0] pending_write_state_d;
  logic [1:0] pending_write_state_q;
  logic [1:0] pending_write_sharers_d;
  logic [1:0] pending_write_sharers_q;
  logic       pending_write_owner_d;
  logic       pending_write_owner_q;
  logic       pending_write_valid_d;
  logic       pending_write_valid_q;

  logic        pending_backup_write_d;
  logic        pending_backup_write_q;
  logic [31:0] pending_backup_data_d;
  logic [31:0] pending_backup_data_q;

  logic backup_read_then_snoop_d;
  logic backup_read_then_snoop_q;

  logic        flush_seen_d;
  logic        flush_seen_q;
  logic [31:0] flush_data_d;
  logic [31:0] flush_data_q;

  logic [1:0] arb_req;
  logic [1:0] arb_grant;
  logic [1:0] arb_req_passthrough;

  logic selected_valid;
  logic selected_cache;

  logic requester_bit;
  logic other_bit;
  logic other_is_sharer;
  logic remote_modified_owner;

  logic [6:0]  request_index;
  logic [31:0] request_index_ext;
  logic [31:0] metadata_addr;
  logic [31:0] cache0_backup_addr;
  logic [31:0] cache1_backup_addr;
  logic [31:0] request_backup_addr;

  logic snoop_send_ready;
  logic ack_send_ready;
  logic dirty_flush_accept;
  logic snoop_ack_accept;
  logic [31:0] dirty_flush_data;
  logic [31:0] snoop_ack_data;
  logic [31:0] snoop_latest_data;

  assign arb_req = {c1_bus_valid_i, c0_bus_valid_i};

  wrr_arbiter #(
    .NUM_REQ  (2),
    .WEIGHT_W (3),
    .WEIGHTS  ({3'd1, 3'd1})
  ) u_wrr_arbiter (
    .clk_i  (clk_i),
    .rst_ni (rst_ni),
    .req_i  (arb_req),
    .grant_o(arb_grant),
    .req_o  (arb_req_passthrough)
  );

  assign selected_valid = (arb_grant != 2'b00);
  assign selected_cache = arb_grant[1];

  assign request_index = request_addr_q[6:0];
  assign request_index_ext = {25'b0, request_index};
  assign metadata_addr = {25'b0, request_index};
  assign cache0_backup_addr = CACHE0_BACKUP_BASE_WORD + request_index_ext;
  assign cache1_backup_addr = CACHE1_BACKUP_BASE_WORD + request_index_ext;
  assign request_backup_addr = request_cache_q ? cache1_backup_addr : cache0_backup_addr;

  assign requester_bit = request_cache_q;
  assign other_bit = !request_cache_q;
  assign other_is_sharer = line_sharers_q[other_bit];

  assign remote_modified_owner =
      (line_state_q == LINE_MODIFIED) && (line_owner_q != request_cache_q);

  assign snoop_send_ready = pending_snoop_cache_q ? c1_dir_ready_i : c0_dir_ready_i;
  assign ack_send_ready = pending_ack_cache_q ? c1_dir_ready_i : c0_dir_ready_i;

  assign dirty_flush_accept =
      (state_q == StWaitSnoop) &&
      (pending_snoop_cache_q ? c1_bus_valid_i : c0_bus_valid_i) &&
      ((pending_snoop_cache_q ? c1_bus_cache_cmd_i : c0_bus_cache_cmd_i) ==
       CACHE_CMD_EVICT_DIRTY);

  assign snoop_ack_accept =
      (state_q == StWaitSnoop) &&
      (pending_snoop_cache_q ? c1_snoop_valid_i : c0_snoop_valid_i) &&
      ((pending_snoop_cache_q ? c1_snoop_cache_cmd_i : c0_snoop_cache_cmd_i) !=
       SNOOP_ACK_NONE);

  assign dirty_flush_data = pending_snoop_cache_q ? c1_bus_wdata_i : c0_bus_wdata_i;
  assign snoop_ack_data = pending_snoop_cache_q ? c1_snoop_data_i : c0_snoop_data_i;

  assign snoop_latest_data = dirty_flush_accept ? dirty_flush_data :
                             flush_seen_q       ? flush_data_q : snoop_ack_data;

  assign dir_state_invalidated_o = dir_state_invalidated_q;

  // This controller always has room for the single outstanding response because
  // it issues only one directory_mem transaction at a time.
  assign dir_mem_resp_ready_o = 1'b1;

  always_comb begin
    dir_mem_valid_o = 1'b0;
    dir_mem_addr_o = 32'b0;
    dir_mem_wstrb_o = 4'b0000;
    dir_mem_w_data_o = 32'b0;
    dir_mem_w_state_o = LINE_INVALID;
    dir_mem_w_sharers_o = 2'b00;
    dir_mem_w_owner_o = 1'b0;
    dir_mem_w_valid_data_o = 1'b0;

    unique case (state_q)
      // StInitMetaReq/StInitMetaResp: invalidate each metadata SRAM entry.
      StInitMetaReq, StInitMetaResp: begin
        dir_mem_valid_o = 1'b1;
        dir_mem_addr_o = {25'b0, init_index_q};
        dir_mem_wstrb_o = 4'b1111;
      end

      // StReadMetaReq/StReadMetaResp: read metadata for the selected line.
      StReadMetaReq, StReadMetaResp: begin
        dir_mem_valid_o = 1'b1;
        dir_mem_addr_o = metadata_addr;
      end

      // StReadBackupReq/StReadBackupResp: read requester backup data word.
      StReadBackupReq, StReadBackupResp: begin
        dir_mem_valid_o = 1'b1;
        dir_mem_addr_o = request_backup_addr;
      end

      // StWriteBackup0Req/StWriteBackup0Resp: update cache 0 backup word.
      StWriteBackup0Req, StWriteBackup0Resp: begin
        dir_mem_valid_o = 1'b1;
        dir_mem_addr_o = cache0_backup_addr;
        dir_mem_wstrb_o = 4'b1111;
        dir_mem_w_data_o = pending_backup_data_q;
      end

      // StWriteBackup1Req/StWriteBackup1Resp: update cache 1 backup word.
      StWriteBackup1Req, StWriteBackup1Resp: begin
        dir_mem_valid_o = 1'b1;
        dir_mem_addr_o = cache1_backup_addr;
        dir_mem_wstrb_o = 4'b1111;
        dir_mem_w_data_o = pending_backup_data_q;
      end

      // StWriteMetaReq/StWriteMetaResp: write updated metadata fields.
      StWriteMetaReq, StWriteMetaResp: begin
        dir_mem_valid_o = 1'b1;
        dir_mem_addr_o = metadata_addr;
        dir_mem_wstrb_o = 4'b1111;
        dir_mem_w_state_o = pending_write_state_q;
        dir_mem_w_sharers_o = pending_write_sharers_q;
        dir_mem_w_owner_o = pending_write_owner_q;
        dir_mem_w_valid_data_o = pending_write_valid_q;
      end

      default: begin
        dir_mem_valid_o = 1'b0;
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
    c0_dir_cmd_o = DIR_CMD_NONE;

    c1_dir_valid_o = 1'b0;
    c1_dir_data_o = 32'b0;
    c1_dir_addr_o = 32'b0;
    c1_dir_cmd_o = DIR_CMD_NONE;

    if ((state_q == StIdle) && selected_valid) begin
      if (selected_cache) begin
        c1_bus_ready_o = 1'b1;
      end else begin
        c0_bus_ready_o = 1'b1;
      end
    end

    if ((state_q == StSendSnoop) || (state_q == StWaitSnoop)) begin
      if (pending_snoop_cache_q) begin
        c1_dir_valid_o = 1'b1;
        c1_dir_addr_o = request_addr_q;
        c1_dir_cmd_o = pending_snoop_cmd_q;
      end else begin
        c0_dir_valid_o = 1'b1;
        c0_dir_addr_o = request_addr_q;
        c0_dir_cmd_o = pending_snoop_cmd_q;
      end
    end

    if (state_q == StSendAck) begin
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

    pending_backup_write_d = pending_backup_write_q;
    pending_backup_data_d = pending_backup_data_q;

    backup_read_then_snoop_d = backup_read_then_snoop_q;

    flush_seen_d = flush_seen_q;
    flush_data_d = flush_data_q;

    unique case (state_q)
      // StInitMetaReq: start one reset-time metadata invalidation write.
      StInitMetaReq: begin
        if (dir_mem_ready_i) begin
          state_d = StInitMetaResp;
        end
      end

      // StInitMetaResp: hold invalidation write stable for the second phase.
      StInitMetaResp: begin
        if (dir_mem_ready_i) begin
          if (init_index_q == LAST_INDEX) begin
            dir_state_invalidated_d = 1'b1;
            state_d = StIdle;
          end else begin
            init_index_d = init_index_q + 7'd1;
            state_d = StInitMetaReq;
          end
        end
      end

      // StIdle: accept one request selected by the weighted round-robin arbiter.
      StIdle: begin
        pending_write_d = 1'b0;
        pending_backup_write_d = 1'b0;
        pending_ack_cmd_d = DIR_CMD_NONE;
        pending_ack_data_d = 32'b0;
        pending_snoop_cmd_d = DIR_CMD_NONE;
        backup_read_then_snoop_d = 1'b0;
        flush_seen_d = 1'b0;
        flush_data_d = 32'b0;

        if (selected_valid) begin
          request_cache_d = selected_cache;
          request_addr_d = selected_cache ? c1_bus_addr_i : c0_bus_addr_i;
          request_data_d = selected_cache ? c1_bus_wdata_i : c0_bus_wdata_i;
          request_cmd_d = selected_cache ? c1_bus_cache_cmd_i : c0_bus_cache_cmd_i;
          state_d = StReadMetaReq;
        end
      end

      // StReadMetaReq: start metadata read for the accepted request.
      StReadMetaReq: begin
        if (dir_mem_ready_i) begin
          state_d = StReadMetaResp;
        end
      end

      // StReadMetaResp: capture metadata returned by directory_mem.
      StReadMetaResp: begin
        if (dir_mem_ready_i) begin
          line_state_d = dir_mem_r_state_i;
          line_sharers_d = dir_mem_r_sharers_i;
          line_owner_d = dir_mem_r_owner_i[0];
          line_valid_d = dir_mem_r_valid_data_i[0];
          state_d = StLookup;
        end
      end

      // StLookup: decide whether to read backup data, snoop, ack, or write.
      StLookup: begin
        pending_ack_cache_d = request_cache_q;
        pending_ack_cmd_d = DIR_CMD_NONE;
        pending_ack_data_d = 32'b0;

        pending_snoop_cache_d = other_bit;
        pending_snoop_cmd_d = DIR_CMD_NONE;

        pending_write_d = 1'b0;
        pending_write_state_d = line_state_q;
        pending_write_sharers_d = line_sharers_q;
        pending_write_owner_d = line_owner_q;
        pending_write_valid_d = line_valid_q;

        pending_backup_write_d = 1'b0;
        pending_backup_data_d = 32'b0;
        backup_read_then_snoop_d = 1'b0;
        flush_seen_d = 1'b0;
        flush_data_d = 32'b0;

        unique case (request_cmd_q)
          CACHE_CMD_BUS_RD: begin
            if (remote_modified_owner) begin
              pending_snoop_cache_d = line_owner_q;
              pending_snoop_cmd_d = DIR_CMD_SNOOP_BUS_RD;
              state_d = StSendSnoop;
            end else begin
              pending_ack_cmd_d = DIR_CMD_BUS_RD_ACK;
              pending_write_d = 1'b1;
              pending_write_state_d = LINE_SHARED;
              pending_write_sharers_d =
                  line_sharers_q | (request_cache_q ? 2'b10 : 2'b01);
              pending_write_owner_d = 1'b0;
              pending_write_valid_d = 1'b1;
              state_d = StReadBackupReq;
            end
          end

          CACHE_CMD_BUS_RDX: begin
            if (remote_modified_owner) begin
              pending_snoop_cache_d = line_owner_q;
              pending_snoop_cmd_d = DIR_CMD_SNOOP_BUS_RDX;
              state_d = StSendSnoop;
            end else if ((line_state_q == LINE_SHARED) && other_is_sharer) begin
              pending_ack_cmd_d = DIR_CMD_BUS_RDX_ACK;
              pending_snoop_cache_d = other_bit;
              pending_snoop_cmd_d = DIR_CMD_SNOOP_BUS_UPGR;
              pending_write_d = 1'b1;
              pending_write_state_d = LINE_MODIFIED;
              pending_write_sharers_d = 2'b00;
              pending_write_owner_d = request_cache_q;
              pending_write_valid_d = 1'b1;
              backup_read_then_snoop_d = 1'b1;
              state_d = StReadBackupReq;
            end else begin
              pending_ack_cmd_d = DIR_CMD_BUS_RDX_ACK;
              pending_write_d = 1'b1;
              pending_write_state_d = LINE_MODIFIED;
              pending_write_sharers_d = 2'b00;
              pending_write_owner_d = request_cache_q;
              pending_write_valid_d = 1'b1;
              state_d = StReadBackupReq;
            end
          end

          CACHE_CMD_BUS_UPGR: begin
            if ((line_state_q == LINE_SHARED) && other_is_sharer) begin
              pending_snoop_cache_d = other_bit;
              pending_snoop_cmd_d = DIR_CMD_SNOOP_BUS_UPGR;
              state_d = StSendSnoop;
            end else begin
              pending_ack_cmd_d = DIR_CMD_BUS_UPGR_ACK;
              pending_write_d = 1'b1;
              pending_write_state_d = LINE_MODIFIED;
              pending_write_sharers_d = 2'b00;
              pending_write_owner_d = request_cache_q;
              pending_write_valid_d = 1'b1;
              state_d = StSendAck;
            end
          end

          CACHE_CMD_EVICT_CLEAN: begin
            pending_write_d = 1'b1;
            pending_write_sharers_d =
                line_sharers_q & ~(request_cache_q ? 2'b10 : 2'b01);
            pending_write_owner_d = 1'b0;

            if (pending_write_sharers_d == 2'b00) begin
              pending_write_state_d = LINE_INVALID;
              pending_write_valid_d = 1'b0;
            end else begin
              pending_write_state_d = LINE_SHARED;
              pending_write_valid_d = 1'b1;
            end

            state_d = StWriteMetaReq;
          end

          CACHE_CMD_EVICT_DIRTY: begin
            pending_write_d = 1'b1;
            pending_write_state_d = LINE_INVALID;
            pending_write_sharers_d = 2'b00;
            pending_write_owner_d = 1'b0;
            pending_write_valid_d = 1'b0;
            pending_backup_write_d = 1'b1;
            pending_backup_data_d = request_data_q;
            state_d = StWriteBackup0Req;
          end

          default: begin
            state_d = StIdle;
          end
        endcase
      end

      // StReadBackupReq: start backup data read from directory_mem.
      StReadBackupReq: begin
        if (dir_mem_ready_i) begin
          state_d = StReadBackupResp;
        end
      end

      // StReadBackupResp: capture backup data for the requester response.
      StReadBackupResp: begin
        if (dir_mem_ready_i) begin
          pending_ack_data_d = dir_mem_r_data_i;
          pending_backup_write_d = 1'b1;
          pending_backup_data_d = dir_mem_r_data_i;

          if (backup_read_then_snoop_q) begin
            state_d = StSendSnoop;
          end else begin
            state_d = StSendAck;
          end
        end
      end

      // StSendSnoop: send snoop command to the conflicting cache.
      StSendSnoop: begin
        if (snoop_send_ready) begin
          state_d = StWaitSnoop;
        end
      end

      // StWaitSnoop: accept dirty flush data and wait for snoop ack.
      StWaitSnoop: begin
        if (dirty_flush_accept) begin
          flush_seen_d = 1'b1;
          flush_data_d = dirty_flush_data;
        end

        if (snoop_ack_accept) begin
          pending_ack_cache_d = request_cache_q;

          unique case (request_cmd_q)
            CACHE_CMD_BUS_RD: begin
              pending_ack_cmd_d = DIR_CMD_BUS_RD_ACK;
              pending_ack_data_d = snoop_latest_data;
              pending_write_d = 1'b1;
              pending_write_state_d = LINE_SHARED;
              pending_write_sharers_d =
                  (request_cache_q ? 2'b10 : 2'b01) |
                  (pending_snoop_cache_q ? 2'b10 : 2'b01);
              pending_write_owner_d = 1'b0;
              pending_write_valid_d = 1'b1;
              pending_backup_write_d = 1'b1;
              pending_backup_data_d = snoop_latest_data;
            end

            CACHE_CMD_BUS_RDX: begin
              pending_ack_cmd_d = DIR_CMD_BUS_RDX_ACK;
              pending_write_d = 1'b1;
              pending_write_state_d = LINE_MODIFIED;
              pending_write_sharers_d = 2'b00;
              pending_write_owner_d = request_cache_q;
              pending_write_valid_d = 1'b1;

              if (pending_snoop_cmd_q == DIR_CMD_SNOOP_BUS_RDX) begin
                pending_ack_data_d = snoop_latest_data;
                pending_backup_write_d = 1'b1;
                pending_backup_data_d = snoop_latest_data;
              end
            end

            CACHE_CMD_BUS_UPGR: begin
              pending_ack_cmd_d = DIR_CMD_BUS_UPGR_ACK;
              pending_ack_data_d = 32'b0;
              pending_write_d = 1'b1;
              pending_write_state_d = LINE_MODIFIED;
              pending_write_sharers_d = 2'b00;
              pending_write_owner_d = request_cache_q;
              pending_write_valid_d = 1'b1;
            end

            default: begin
              pending_ack_cmd_d = DIR_CMD_NONE;
              pending_ack_data_d = 32'b0;
              pending_write_d = 1'b0;
            end
          endcase

          state_d = StSendAck;
        end
      end

      // StSendAck: deliver final response, then commit backup or metadata.
      StSendAck: begin
        if (ack_send_ready) begin
          if (pending_backup_write_q) begin
            state_d = StWriteBackup0Req;
          end else if (pending_write_q) begin
            state_d = StWriteMetaReq;
          end else begin
            state_d = StIdle;
          end
        end
      end

      // StWriteBackup0Req: start cache 0 backup write.
      StWriteBackup0Req: begin
        if (dir_mem_ready_i) begin
          state_d = StWriteBackup0Resp;
        end
      end

      // StWriteBackup0Resp: finish cache 0 backup write.
      StWriteBackup0Resp: begin
        if (dir_mem_ready_i) begin
          state_d = StWriteBackup1Req;
        end
      end

      // StWriteBackup1Req: start cache 1 backup write.
      StWriteBackup1Req: begin
        if (dir_mem_ready_i) begin
          state_d = StWriteBackup1Resp;
        end
      end

      // StWriteBackup1Resp: finish cache 1 backup write.
      StWriteBackup1Resp: begin
        if (dir_mem_ready_i) begin
          if (pending_write_q) begin
            state_d = StWriteMetaReq;
          end else begin
            state_d = StDone;
          end
        end
      end

      // StWriteMetaReq: start metadata write.
      StWriteMetaReq: begin
        if (dir_mem_ready_i) begin
          state_d = StWriteMetaResp;
        end
      end

      // StWriteMetaResp: finish metadata write.
      StWriteMetaResp: begin
        if (dir_mem_ready_i) begin
          state_d = StDone;
        end
      end

      // StDone: single-cycle cleanup before accepting another request.
      StDone: begin
        state_d = StIdle;
      end

      default: begin
        state_d = StIdle;
      end
    endcase
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= StInitMetaReq;
      init_index_q <= 7'd0;
      dir_state_invalidated_q <= 1'b0;

      request_cache_q <= 1'b0;
      request_addr_q <= 32'b0;
      request_data_q <= 32'b0;
      request_cmd_q <= CACHE_CMD_NONE;

      line_state_q <= LINE_INVALID;
      line_sharers_q <= 2'b00;
      line_owner_q <= 1'b0;
      line_valid_q <= 1'b0;

      pending_ack_cache_q <= 1'b0;
      pending_ack_cmd_q <= DIR_CMD_NONE;
      pending_ack_data_q <= 32'b0;

      pending_snoop_cache_q <= 1'b0;
      pending_snoop_cmd_q <= DIR_CMD_NONE;

      pending_write_q <= 1'b0;
      pending_write_state_q <= LINE_INVALID;
      pending_write_sharers_q <= 2'b00;
      pending_write_owner_q <= 1'b0;
      pending_write_valid_q <= 1'b0;

      pending_backup_write_q <= 1'b0;
      pending_backup_data_q <= 32'b0;

      backup_read_then_snoop_q <= 1'b0;

      flush_seen_q <= 1'b0;
      flush_data_q <= 32'b0;
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

      pending_backup_write_q <= pending_backup_write_d;
      pending_backup_data_q <= pending_backup_data_d;

      backup_read_then_snoop_q <= backup_read_then_snoop_d;

      flush_seen_q <= flush_seen_d;
      flush_data_q <= flush_data_d;
    end
  end

endmodule : directory_controller

`default_nettype wire

