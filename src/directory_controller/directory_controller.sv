// SPDX-License-Identifier: Apache-2.0
//
// Directory controller.
//
// Memory accesses are intentionally stretched for two accepted cycles so the
// GF180-backed memory path has time to present stable read data and commit writes.
//
// Production directory controller only.
//
// The controller accepts decoded cache-side coherence requests from two
// directory_interface instances, performs MSI directory actions, accesses
// reserved directory metadata/data memory, and returns decoded responses.
//
// This standalone version has no full-path test wrapper and no external arbiter
// dependency. A small internal two-request round-robin selector chooses between
// cache 0 and cache 1 requests when both arrive together.

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

  output logic        dir_mem_valid_o,
  output logic        dir_mem_instr_o,
  output logic [31:0] dir_mem_addr_o,
  output logic [31:0] dir_mem_wdata_o,
  output logic [3:0]  dir_mem_wstrb_o,
  input  logic [31:0] dir_mem_rdata_i,
  input  logic        dir_mem_ready_i
);

  localparam logic [4:0] CacheCmdNone       = 5'b00000;
  localparam logic [4:0] CacheCmdBusRd      = 5'b00001;
  localparam logic [4:0] CacheCmdBusRdx     = 5'b00010;
  localparam logic [4:0] CacheCmdBusUpgr    = 5'b00100;
  localparam logic [4:0] CacheCmdEvictClean = 5'b01000;
  localparam logic [4:0] CacheCmdEvictDirty = 5'b10000;

  localparam logic [2:0] SnoopAckNone    = 3'b000;
  localparam logic [2:0] SnoopAckBusRd   = 3'b001;
  localparam logic [2:0] SnoopAckBusRdx  = 3'b010;
  localparam logic [2:0] SnoopAckBusUpgr = 3'b100;

  localparam logic [5:0] DirCmdNone         = 6'b000000;
  localparam logic [5:0] DirCmdBusRdAck     = 6'b000001;
  localparam logic [5:0] DirCmdBusRdxAck    = 6'b000010;
  localparam logic [5:0] DirCmdBusUpgrAck   = 6'b000100;
  localparam logic [5:0] DirCmdSnoopBusRd   = 6'b001000;
  localparam logic [5:0] DirCmdSnoopBusRdx  = 6'b010000;
  localparam logic [5:0] DirCmdSnoopBusUpgr = 6'b100000;

  localparam logic [1:0] LineInvalid  = 2'b00;
  localparam logic [1:0] LineShared   = 2'b01;
  localparam logic [1:0] LineModified = 2'b10;

  localparam logic [10:0] DirMetaBaseWord = 11'd1792;
  localparam logic [10:0] DirDataBaseWord = 11'd1920;
  localparam logic [6:0]  LastIndex       = 7'd127;

  typedef enum logic [4:0] {
    StInitMetaReq,
    StInitMetaResp,
    StInitDataReq,
    StInitDataResp,
    StIdle,
    StReadMetaReq,
    StReadMetaResp,
    StReadDirDataReq,
    StReadDirDataResp,
    StReadBackingReq,
    StReadBackingResp,
    StLookup,
    StSendSnoop,
    StWaitSnoop,
    StSendAck,
    StWriteBackingReq,
    StWriteBackingResp,
    StWriteMetaReq,
    StWriteMetaResp,
    StWriteDirDataReq,
    StWriteDirDataResp,
    StDone
  } dir_state_e;

  dir_state_e state_q;
  dir_state_e state_d;

  logic [6:0] init_index_q;
  logic [6:0] init_index_d;

  logic request_cache_q;
  logic request_cache_d;

  logic [31:0] request_addr_q;
  logic [31:0] request_addr_d;
  logic [31:0] request_data_q;
  logic [31:0] request_data_d;
  logic [4:0]  request_cmd_q;
  logic [4:0]  request_cmd_d;

  logic [1:0]  line_state_q;
  logic [1:0]  line_state_d;
  logic [1:0]  line_sharers_q;
  logic [1:0]  line_sharers_d;
  logic        line_owner_q;
  logic        line_owner_d;
  logic        line_data_valid_q;
  logic        line_data_valid_d;
  logic [31:0] line_data_q;
  logic [31:0] line_data_d;

  logic        pending_ack_cache_q;
  logic        pending_ack_cache_d;
  logic [5:0]  pending_ack_cmd_q;
  logic [5:0]  pending_ack_cmd_d;
  logic [31:0] pending_ack_data_q;
  logic [31:0] pending_ack_data_d;

  logic        pending_snoop_cache_q;
  logic        pending_snoop_cache_d;
  logic [5:0]  pending_snoop_cmd_q;
  logic [5:0]  pending_snoop_cmd_d;

  logic        pending_write_q;
  logic        pending_write_d;
  logic [1:0]  pending_write_state_q;
  logic [1:0]  pending_write_state_d;
  logic [1:0]  pending_write_sharers_q;
  logic [1:0]  pending_write_sharers_d;
  logic        pending_write_owner_q;
  logic        pending_write_owner_d;
  logic        pending_write_data_valid_q;
  logic        pending_write_data_valid_d;
  logic [31:0] pending_write_data_q;
  logic [31:0] pending_write_data_d;
  logic        pending_write_backing_q;
  logic        pending_write_backing_d;
  logic [31:0] pending_write_backing_data_q;
  logic [31:0] pending_write_backing_data_d;

  logic        flush_seen_q;
  logic        flush_seen_d;
  logic [31:0] flush_data_q;
  logic [31:0] flush_data_d;

  logic request_priority_q;
  logic request_priority_d;

  logic selected_cache;
  logic selected_valid;

  logic requester_bit;
  logic other_bit;
  logic other_is_sharer;
  logic remote_modified_owner;

  logic [6:0]  request_index;
  logic [10:0] meta_addr;
  logic [10:0] data_addr;
  logic [10:0] backing_addr;
  logic [31:0] packed_metadata;

  logic snoop_send_ready;
  logic ack_send_ready;
  logic dirty_flush_accept;
  logic snoop_ack_accept;
  logic [31:0] snoop_ack_data;
  logic [31:0] finish_data;

  always_comb begin
    selected_valid = 1'b0;
    selected_cache = 1'b0;

    if (c0_bus_valid_i && c1_bus_valid_i) begin
      selected_valid = 1'b1;
      selected_cache = request_priority_q;
    end else if (c0_bus_valid_i) begin
      selected_valid = 1'b1;
      selected_cache = 1'b0;
    end else if (c1_bus_valid_i) begin
      selected_valid = 1'b1;
      selected_cache = 1'b1;
    end
  end

  assign request_index = request_addr_q[6:0];
  assign meta_addr = DirMetaBaseWord + {4'b0000, request_index};
  assign data_addr = DirDataBaseWord + {4'b0000, request_index};
  assign backing_addr = request_addr_q[10:0];

  assign requester_bit = request_cache_q;
  assign other_bit = !request_cache_q;

  assign other_is_sharer = line_sharers_q[other_bit];

  assign remote_modified_owner =
      (line_state_q == LineModified) && (line_owner_q != request_cache_q);

  assign packed_metadata = {
    26'b0,
    pending_write_data_valid_q,
    pending_write_owner_q,
    pending_write_sharers_q,
    pending_write_state_q
  };

  assign snoop_send_ready =
      pending_snoop_cache_q ? c1_dir_ready_i : c0_dir_ready_i;

  assign ack_send_ready =
      pending_ack_cache_q ? c1_dir_ready_i : c0_dir_ready_i;

  assign dirty_flush_accept =
      (state_q == StWaitSnoop) &&
      (pending_snoop_cache_q ? c1_bus_valid_i : c0_bus_valid_i) &&
      ((pending_snoop_cache_q ? c1_bus_cache_cmd_i : c0_bus_cache_cmd_i) ==
       CacheCmdEvictDirty);

  assign snoop_ack_accept =
      (state_q == StWaitSnoop) &&
      (pending_snoop_cache_q ? c1_snoop_valid_i : c0_snoop_valid_i) &&
      ((pending_snoop_cache_q ? c1_snoop_cache_cmd_i : c0_snoop_cache_cmd_i) !=
       SnoopAckNone);

  assign snoop_ack_data =
      pending_snoop_cache_q ? c1_snoop_data_i : c0_snoop_data_i;

  assign finish_data =
      dirty_flush_accept ? (pending_snoop_cache_q ? c1_bus_wdata_i :
                                                    c0_bus_wdata_i) :
      snoop_ack_accept   ? snoop_ack_data :
      flush_seen_q       ? flush_data_q :
                            line_data_q;

  always_comb begin
    dir_mem_valid_o = 1'b0;
    dir_mem_instr_o = 1'b0;
    dir_mem_addr_o = 32'b0;
    dir_mem_wdata_o = 32'b0;
    dir_mem_wstrb_o = 4'b0000;

    unique case (state_q)
      StInitMetaReq, StInitMetaResp: begin
        dir_mem_valid_o = 1'b1;
        dir_mem_addr_o = {21'b0, DirMetaBaseWord + {4'b0000, init_index_q}};
        dir_mem_wdata_o = 32'b0;
        dir_mem_wstrb_o = 4'b1111;
      end

      StInitDataReq, StInitDataResp: begin
        dir_mem_valid_o = 1'b1;
        dir_mem_addr_o = {21'b0, DirDataBaseWord + {4'b0000, init_index_q}};
        dir_mem_wdata_o = 32'b0;
        dir_mem_wstrb_o = 4'b1111;
      end

      StReadMetaReq, StReadMetaResp: begin
        dir_mem_valid_o = 1'b1;
        dir_mem_addr_o = {21'b0, meta_addr};
      end

      StReadDirDataReq, StReadDirDataResp: begin
        dir_mem_valid_o = 1'b1;
        dir_mem_addr_o = {21'b0, data_addr};
      end

      StReadBackingReq, StReadBackingResp: begin
        dir_mem_valid_o = 1'b1;
        dir_mem_addr_o = {21'b0, backing_addr};
      end

      StWriteBackingReq, StWriteBackingResp: begin
        dir_mem_valid_o = 1'b1;
        dir_mem_addr_o = {21'b0, backing_addr};
        dir_mem_wdata_o = pending_write_backing_data_q;
        dir_mem_wstrb_o = 4'b1111;
      end

      StWriteMetaReq, StWriteMetaResp: begin
        dir_mem_valid_o = 1'b1;
        dir_mem_addr_o = {21'b0, meta_addr};
        dir_mem_wdata_o = packed_metadata;
        dir_mem_wstrb_o = 4'b1111;
      end

      StWriteDirDataReq, StWriteDirDataResp: begin
        dir_mem_valid_o = 1'b1;
        dir_mem_addr_o = {21'b0, data_addr};
        dir_mem_wdata_o = pending_write_data_q;
        dir_mem_wstrb_o = 4'b1111;
      end

      default: begin
        dir_mem_valid_o = 1'b0;
        dir_mem_instr_o = 1'b0;
        dir_mem_addr_o = 32'b0;
        dir_mem_wdata_o = 32'b0;
        dir_mem_wstrb_o = 4'b0000;
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
    c0_dir_cmd_o = DirCmdNone;

    c1_dir_valid_o = 1'b0;
    c1_dir_data_o = 32'b0;
    c1_dir_addr_o = 32'b0;
    c1_dir_cmd_o = DirCmdNone;

    if (state_q == StIdle && selected_valid) begin
      if (selected_cache) begin
        c1_bus_ready_o = 1'b1;
      end else begin
        c0_bus_ready_o = 1'b1;
      end
    end

    if (state_q == StSendSnoop || state_q == StWaitSnoop) begin
      if (pending_snoop_cache_q) begin
        c1_dir_valid_o = 1'b1;
        c1_dir_data_o = line_data_q;
        c1_dir_addr_o = request_addr_q;
        c1_dir_cmd_o = pending_snoop_cmd_q;
      end else begin
        c0_dir_valid_o = 1'b1;
        c0_dir_data_o = line_data_q;
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
    request_priority_d = request_priority_q;

    request_cache_d = request_cache_q;
    request_addr_d = request_addr_q;
    request_data_d = request_data_q;
    request_cmd_d = request_cmd_q;

    line_state_d = line_state_q;
    line_sharers_d = line_sharers_q;
    line_owner_d = line_owner_q;
    line_data_valid_d = line_data_valid_q;
    line_data_d = line_data_q;

    pending_ack_cache_d = pending_ack_cache_q;
    pending_ack_cmd_d = pending_ack_cmd_q;
    pending_ack_data_d = pending_ack_data_q;

    pending_snoop_cache_d = pending_snoop_cache_q;
    pending_snoop_cmd_d = pending_snoop_cmd_q;

    pending_write_d = pending_write_q;
    pending_write_state_d = pending_write_state_q;
    pending_write_sharers_d = pending_write_sharers_q;
    pending_write_owner_d = pending_write_owner_q;
    pending_write_data_valid_d = pending_write_data_valid_q;
    pending_write_data_d = pending_write_data_q;
    pending_write_backing_d = pending_write_backing_q;
    pending_write_backing_data_d = pending_write_backing_data_q;

    flush_seen_d = flush_seen_q;
    flush_data_d = flush_data_q;

    unique case (state_q)
      StInitMetaReq: begin
        if (dir_mem_ready_i) begin
          state_d = StInitMetaResp;
        end
      end

      StInitMetaResp: begin
        if (dir_mem_ready_i) begin
          state_d = StInitDataReq;
        end
      end

      StInitDataReq: begin
        if (dir_mem_ready_i) begin
          state_d = StInitDataResp;
        end
      end

      StInitDataResp: begin
        if (dir_mem_ready_i) begin
          if (init_index_q == LastIndex) begin
            state_d = StIdle;
          end else begin
            init_index_d = init_index_q + 7'd1;
            state_d = StInitMetaReq;
          end
        end
      end

      StIdle: begin
        pending_write_d = 1'b0;
        flush_seen_d = 1'b0;

        if (selected_valid) begin
          request_cache_d = selected_cache;
          request_addr_d = selected_cache ? c1_bus_addr_i : c0_bus_addr_i;
          request_data_d = selected_cache ? c1_bus_wdata_i : c0_bus_wdata_i;
          request_cmd_d = selected_cache ? c1_bus_cache_cmd_i :
                                            c0_bus_cache_cmd_i;
          request_priority_d = ~selected_cache;
          state_d = StReadMetaReq;
        end
      end

      StReadMetaReq: begin
        if (dir_mem_ready_i) begin
          state_d = StReadMetaResp;
        end
      end

      StReadMetaResp: begin
        if (dir_mem_ready_i) begin
          line_state_d = dir_mem_rdata_i[1:0];
          line_sharers_d = dir_mem_rdata_i[3:2];
          line_owner_d = dir_mem_rdata_i[4];
          line_data_valid_d = dir_mem_rdata_i[5];
          state_d = StReadDirDataReq;
        end
      end

      StReadDirDataReq: begin
        if (dir_mem_ready_i) begin
          state_d = StReadDirDataResp;
        end
      end

      StReadDirDataResp: begin
        if (dir_mem_ready_i) begin
          line_data_d = dir_mem_rdata_i;
          if (line_data_valid_q) begin
            state_d = StLookup;
          end else begin
            state_d = StReadBackingReq;
          end
        end
      end

      StReadBackingReq: begin
        if (dir_mem_ready_i) begin
          state_d = StReadBackingResp;
        end
      end

      StReadBackingResp: begin
        if (dir_mem_ready_i) begin
          line_data_d = dir_mem_rdata_i;
          state_d = StLookup;
        end
      end

      StLookup: begin
        pending_ack_cache_d = request_cache_q;
        pending_ack_cmd_d = DirCmdNone;
        pending_ack_data_d = 32'b0;

        pending_snoop_cache_d = other_bit;
        pending_snoop_cmd_d = DirCmdNone;

        pending_write_d = 1'b0;
        pending_write_state_d = line_state_q;
        pending_write_sharers_d = line_sharers_q;
        pending_write_owner_d = line_owner_q;
        pending_write_data_valid_d = line_data_valid_q;
        pending_write_data_d = line_data_q;
        pending_write_backing_d = 1'b0;
        pending_write_backing_data_d = 32'b0;

        unique case (request_cmd_q)
          CacheCmdBusRd: begin
            if (remote_modified_owner) begin
              pending_snoop_cache_d = line_owner_q;
              pending_snoop_cmd_d = DirCmdSnoopBusRd;
              state_d = StSendSnoop;
            end else begin
              pending_ack_cmd_d = DirCmdBusRdAck;
              pending_ack_data_d = line_data_q;

              pending_write_d = 1'b1;
              pending_write_state_d = LineShared;
              pending_write_sharers_d =
                  line_sharers_q | (request_cache_q ? 2'b10 : 2'b01);
              pending_write_owner_d = 1'b0;
              pending_write_data_valid_d = 1'b1;
              pending_write_data_d = line_data_q;
              state_d = StSendAck;
            end
          end

          CacheCmdBusRdx: begin
            if (remote_modified_owner) begin
              pending_snoop_cache_d = line_owner_q;
              pending_snoop_cmd_d = DirCmdSnoopBusRdx;
              state_d = StSendSnoop;
            end else if ((line_state_q == LineShared) && other_is_sharer) begin
              pending_snoop_cache_d = other_bit;
              pending_snoop_cmd_d = DirCmdSnoopBusUpgr;
              state_d = StSendSnoop;
            end else begin
              pending_ack_cmd_d = DirCmdBusRdxAck;
              pending_ack_data_d = line_data_q;

              pending_write_d = 1'b1;
              pending_write_state_d = LineModified;
              pending_write_sharers_d = 2'b00;
              pending_write_owner_d = request_cache_q;
              pending_write_data_valid_d = 1'b1;
              pending_write_data_d = line_data_q;
              state_d = StSendAck;
            end
          end

          CacheCmdBusUpgr: begin
            if ((line_state_q == LineShared) && other_is_sharer) begin
              pending_snoop_cache_d = other_bit;
              pending_snoop_cmd_d = DirCmdSnoopBusUpgr;
              state_d = StSendSnoop;
            end else begin
              pending_ack_cmd_d = DirCmdBusUpgrAck;
              pending_ack_data_d = 32'b0;

              pending_write_d = 1'b1;
              pending_write_state_d = LineModified;
              pending_write_sharers_d = 2'b00;
              pending_write_owner_d = request_cache_q;
              pending_write_data_valid_d = line_data_valid_q;
              pending_write_data_d = line_data_q;
              state_d = StSendAck;
            end
          end

          CacheCmdEvictClean: begin
            // If this clean eviction removes the last sharer, invalidate both
            // metadata and cached directory data so the next BusRd reads the
            // normal backing memory again.
            pending_write_d = 1'b1;
            pending_write_sharers_d =
                line_sharers_q & ~(request_cache_q ? 2'b10 : 2'b01);
            pending_write_owner_d = 1'b0;
            pending_write_backing_d = 1'b0;
            pending_write_backing_data_d = 32'b0;

            if (pending_write_sharers_d == 2'b00) begin
              pending_write_state_d = LineInvalid;
              pending_write_data_valid_d = 1'b0;
              pending_write_data_d = 32'b0;
            end else begin
              pending_write_state_d = LineShared;
              pending_write_data_valid_d = line_data_valid_q;
              pending_write_data_d = line_data_q;
            end

            state_d = StWriteMetaReq;
          end

          CacheCmdEvictDirty: begin
            pending_write_d = 1'b1;
            pending_write_state_d = LineInvalid;
            pending_write_sharers_d = 2'b00;
            pending_write_owner_d = 1'b0;
            pending_write_data_valid_d = 1'b0;
            pending_write_data_d = 32'b0;
            pending_write_backing_d = 1'b1;
            pending_write_backing_data_d = request_data_q;
            state_d = StWriteBackingReq;
          end

          default: begin
            state_d = StIdle;
          end
        endcase
      end

      StSendSnoop: begin
        if (snoop_send_ready) begin
          state_d = StWaitSnoop;
        end
      end

      StWaitSnoop: begin
        if (dirty_flush_accept) begin
          flush_seen_d = 1'b1;
          flush_data_d = pending_snoop_cache_q ? c1_bus_wdata_i :
                                                c0_bus_wdata_i;
        end

        if (snoop_ack_accept) begin
          pending_ack_cache_d = request_cache_q;

          unique case (request_cmd_q)
            CacheCmdBusRd: begin
              pending_ack_cmd_d = DirCmdBusRdAck;
              pending_ack_data_d = finish_data;

              pending_write_d = 1'b1;
              pending_write_state_d = LineShared;
              pending_write_sharers_d =
                  (request_cache_q ? 2'b10 : 2'b01) |
                  (pending_snoop_cache_q ? 2'b10 : 2'b01);
              pending_write_owner_d = 1'b0;
              pending_write_data_valid_d = 1'b1;
              pending_write_data_d = finish_data;
            end

            CacheCmdBusRdx: begin
              pending_ack_cmd_d = DirCmdBusRdxAck;
              pending_ack_data_d = finish_data;

              pending_write_d = 1'b1;
              pending_write_state_d = LineModified;
              pending_write_sharers_d = 2'b00;
              pending_write_owner_d = request_cache_q;
              pending_write_data_valid_d = 1'b1;
              pending_write_data_d = finish_data;
            end

            CacheCmdBusUpgr: begin
              pending_ack_cmd_d = DirCmdBusUpgrAck;
              pending_ack_data_d = 32'b0;

              pending_write_d = 1'b1;
              pending_write_state_d = LineModified;
              pending_write_sharers_d = 2'b00;
              pending_write_owner_d = request_cache_q;
              pending_write_data_valid_d = line_data_valid_q;
              pending_write_data_d = line_data_q;
            end

            default: begin
              pending_ack_cmd_d = DirCmdNone;
              pending_ack_data_d = 32'b0;
              pending_write_d = 1'b0;
            end
          endcase

          state_d = StSendAck;
        end
      end

      StSendAck: begin
        if (ack_send_ready) begin
          if (pending_write_q) begin
            if (pending_write_backing_q) begin
              state_d = StWriteBackingReq;
            end else begin
              state_d = StWriteMetaReq;
            end
          end else begin
            state_d = StIdle;
          end
        end
      end

      StWriteBackingReq: begin
        if (dir_mem_ready_i) begin
          state_d = StWriteBackingResp;
        end
      end

      StWriteBackingResp: begin
        if (dir_mem_ready_i) begin
          state_d = StWriteMetaReq;
        end
      end

      StWriteMetaReq: begin
        if (dir_mem_ready_i) begin
          state_d = StWriteMetaResp;
        end
      end

      StWriteMetaResp: begin
        if (dir_mem_ready_i) begin
          state_d = StWriteDirDataReq;
        end
      end

      StWriteDirDataReq: begin
        if (dir_mem_ready_i) begin
          state_d = StWriteDirDataResp;
        end
      end

      StWriteDirDataResp: begin
        if (dir_mem_ready_i) begin
          state_d = StDone;
        end
      end

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
      request_priority_q <= 1'b0;

      request_cache_q <= 1'b0;
      request_addr_q <= 32'b0;
      request_data_q <= 32'b0;
      request_cmd_q <= CacheCmdNone;

      line_state_q <= LineInvalid;
      line_sharers_q <= 2'b00;
      line_owner_q <= 1'b0;
      line_data_valid_q <= 1'b0;
      line_data_q <= 32'b0;

      pending_ack_cache_q <= 1'b0;
      pending_ack_cmd_q <= DirCmdNone;
      pending_ack_data_q <= 32'b0;

      pending_snoop_cache_q <= 1'b0;
      pending_snoop_cmd_q <= DirCmdNone;

      pending_write_q <= 1'b0;
      pending_write_state_q <= LineInvalid;
      pending_write_sharers_q <= 2'b00;
      pending_write_owner_q <= 1'b0;
      pending_write_data_valid_q <= 1'b0;
      pending_write_data_q <= 32'b0;
      pending_write_backing_q <= 1'b0;
      pending_write_backing_data_q <= 32'b0;

      flush_seen_q <= 1'b0;
      flush_data_q <= 32'b0;
    end else begin
      state_q <= state_d;
      init_index_q <= init_index_d;
      request_priority_q <= request_priority_d;

      request_cache_q <= request_cache_d;
      request_addr_q <= request_addr_d;
      request_data_q <= request_data_d;
      request_cmd_q <= request_cmd_d;

      line_state_q <= line_state_d;
      line_sharers_q <= line_sharers_d;
      line_owner_q <= line_owner_d;
      line_data_valid_q <= line_data_valid_d;
      line_data_q <= line_data_d;

      pending_ack_cache_q <= pending_ack_cache_d;
      pending_ack_cmd_q <= pending_ack_cmd_d;
      pending_ack_data_q <= pending_ack_data_d;

      pending_snoop_cache_q <= pending_snoop_cache_d;
      pending_snoop_cmd_q <= pending_snoop_cmd_d;

      pending_write_q <= pending_write_d;
      pending_write_state_q <= pending_write_state_d;
      pending_write_sharers_q <= pending_write_sharers_d;
      pending_write_owner_q <= pending_write_owner_d;
      pending_write_data_valid_q <= pending_write_data_valid_d;
      pending_write_data_q <= pending_write_data_d;
      pending_write_backing_q <= pending_write_backing_d;
      pending_write_backing_data_q <= pending_write_backing_data_d;

      flush_seen_q <= flush_seen_d;
      flush_data_q <= flush_data_d;
    end
  end

endmodule : directory_controller

`default_nettype wire

