// SPDX-License-Identifier: Apache-2.0
//
// Two-cache directory controller with memory backed directory metadata storage.

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

  localparam int unsigned DIRECTORY_INDEX_WIDTH = 7;

  localparam logic [1:0] LineInvalid  = 2'b00;
  localparam logic [1:0] LineShared   = 2'b01;
  localparam logic [1:0] LineModified = 2'b10;

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

  localparam logic [3:0] StIdle           = 4'd0;
  localparam logic [3:0] StReadTable      = 4'd1;
  localparam logic [3:0] StLookup         = 4'd2;
  localparam logic [3:0] StSendSnoop      = 4'd3;
  localparam logic [3:0] StWaitSnoop      = 4'd4;
  localparam logic [3:0] StSendAck        = 4'd5;
  localparam logic [3:0] StWriteTableReq  = 4'd6;
  localparam logic [3:0] StWriteTableResp = 4'd7;

  logic [3:0] state_q;
  logic [3:0] state_d;

  logic rr_priority_q;
  logic rr_priority_d;

  logic selected_valid;
  logic selected_cache;
  logic selected_request_accepted;
  logic selected_status_allowed;

  logic        request_cache_q;
  logic        request_cache_d;
  logic [31:0] request_addr_q;
  logic [31:0] request_addr_d;
  logic [31:0] request_data_q;
  logic [31:0] request_data_d;
  logic [4:0]  request_cmd_q;
  logic [4:0]  request_cmd_d;

  logic [1:0]  active_state_q;
  logic [1:0]  active_state_d;
  logic [1:0]  active_sharers_q;
  logic [1:0]  active_sharers_d;
  logic        active_owner_q;
  logic        active_owner_d;
  logic        active_data_valid_q;
  logic        active_data_valid_d;
  logic [31:0] active_data_q;
  logic [31:0] active_data_d;

  logic [1:0]  planned_state;
  logic [1:0]  planned_sharers;
  logic        planned_owner;
  logic        planned_data_valid;
  logic [31:0] planned_data;
  logic        planned_write;
  logic        planned_send_ack;
  logic [5:0]  planned_ack_cmd;
  logic [31:0] planned_ack_data;
  logic        planned_send_snoop;
  logic        planned_target_cache;
  logic [5:0]  planned_snoop_cmd;
  logic [2:0]  planned_expected_ack;
  logic        planned_done_no_ack;

  logic        pending_write_q;
  logic        pending_write_d;
  logic [1:0]  pending_state_q;
  logic [1:0]  pending_state_d;
  logic [1:0]  pending_sharers_q;
  logic [1:0]  pending_sharers_d;
  logic        pending_owner_q;
  logic        pending_owner_d;
  logic        pending_data_valid_q;
  logic        pending_data_valid_d;
  logic [31:0] pending_data_q;
  logic [31:0] pending_data_d;
  logic [5:0]  pending_ack_cmd_q;
  logic [5:0]  pending_ack_cmd_d;
  logic [31:0] pending_ack_data_q;
  logic [31:0] pending_ack_data_d;

  logic target_cache_q;
  logic target_cache_d;
  logic [5:0] snoop_cmd_q;
  logic [5:0] snoop_cmd_d;
  logic [2:0] expected_ack_q;
  logic [2:0] expected_ack_d;

  logic flush_seen_q;
  logic flush_seen_d;
  logic [31:0] flush_data_q;
  logic [31:0] flush_data_d;

  logic [1:0] request_cache_bit;
  logic [1:0] other_cache_bit;
  logic [1:0] remaining_sharers;
  logic       other_sharer_present;
  logic [31:0] selected_active_data;
  logic [6:0] selected_index;
  logic [6:0] request_index;

  logic target_bus_valid;
  logic [31:0] target_bus_addr;
  logic [31:0] target_bus_data;
  logic [4:0] target_bus_cmd;
  logic target_snoop_valid;
  logic [2:0] target_snoop_cmd;
  logic dirty_flush_accept;
  logic snoop_ack_accept;
  logic snoop_wait_active;

  logic [1:0] finish_request_cache_bit;
  logic [1:0] finish_target_cache_bit;
  logic [31:0] finish_data;

  logic send_cache;
  logic send_valid;
  logic [31:0] send_addr;
  logic [31:0] send_data;
  logic [5:0] send_cmd;
  logic send_ready;

  logic table_read_valid;
  logic table_read_ready;
  logic [6:0] table_read_index;
  logic table_read_resp_valid;
  logic table_read_resp_ready;
  logic [1:0] table_read_state;
  logic [1:0] table_read_sharers;
  logic table_read_owner;
  logic table_read_data_valid;
  logic [31:0] table_read_data;

  logic table_write_valid;
  logic table_write_ready;
  logic [6:0] table_write_index;
  logic [1:0] table_write_state;
  logic [1:0] table_write_sharers;
  logic table_write_owner;
  logic table_write_data_valid;
  logic [31:0] table_write_data;
  logic table_write_done_valid;
  logic table_write_done_ready;

  logic table_status_valid;
  logic table_status_ready;

  assign selected_valid = c0_bus_valid_i || c1_bus_valid_i;
  assign selected_cache = (c0_bus_valid_i && c1_bus_valid_i) ?
                          rr_priority_q : c1_bus_valid_i;
  assign selected_index = selected_cache ?
                          c1_bus_addr_i[DIRECTORY_INDEX_WIDTH-1:0] :
                          c0_bus_addr_i[DIRECTORY_INDEX_WIDTH-1:0];
  assign request_index = request_addr_q[DIRECTORY_INDEX_WIDTH-1:0];

  assign request_cache_bit = request_cache_q ? 2'b10 : 2'b01;
  assign other_cache_bit = request_cache_q ? 2'b01 : 2'b10;
  assign remaining_sharers = active_sharers_q & ~request_cache_bit;
  assign other_sharer_present = ((active_sharers_q & other_cache_bit) != 2'b00);
  assign selected_active_data = active_data_valid_q ? active_data_q : request_data_q;

  assign snoop_wait_active = (state_q == StWaitSnoop);
  assign target_bus_valid = target_cache_q ? c1_bus_valid_i : c0_bus_valid_i;
  assign target_bus_addr = target_cache_q ? c1_bus_addr_i : c0_bus_addr_i;
  assign target_bus_data = target_cache_q ? c1_bus_wdata_i : c0_bus_wdata_i;
  assign target_bus_cmd = target_cache_q ? c1_bus_cache_cmd_i : c0_bus_cache_cmd_i;
  assign target_snoop_valid = target_cache_q ? c1_snoop_valid_i : c0_snoop_valid_i;
  assign target_snoop_cmd = target_cache_q ? c1_snoop_cache_cmd_i : c0_snoop_cache_cmd_i;

  assign dirty_flush_accept = snoop_wait_active && target_bus_valid &&
                              (target_bus_cmd == CacheCmdEvictDirty) &&
                              (target_bus_addr[DIRECTORY_INDEX_WIDTH-1:0] == request_index);
  assign snoop_ack_accept = snoop_wait_active && target_snoop_valid &&
                            ((target_snoop_cmd & expected_ack_q) != 3'b000);

  assign finish_request_cache_bit = request_cache_q ? 2'b10 : 2'b01;
  assign finish_target_cache_bit = target_cache_q ? 2'b10 : 2'b01;
  assign finish_data = (flush_seen_q || dirty_flush_accept) ?
                       (dirty_flush_accept ? target_bus_data : flush_data_q) :
                       selected_active_data;

  //////////////////////////
  // Metadata table access //
  //////////////////////////

  assign selected_request_accepted = (state_q == StIdle) && selected_valid && table_read_ready;
  assign selected_status_allowed = (state_q == StIdle) && !selected_valid;

  assign table_read_valid = (state_q == StIdle) && selected_valid;
  assign table_read_index = selected_index;
  assign table_read_resp_ready = (state_q == StReadTable);

  assign table_write_valid = (state_q == StWriteTableReq) && pending_write_q;
  assign table_write_index = request_index;
  assign table_write_state = pending_state_q;
  assign table_write_sharers = pending_sharers_q;
  assign table_write_owner = pending_owner_q;
  assign table_write_data_valid = pending_data_valid_q;
  assign table_write_data = pending_data_q;
  assign table_write_done_ready = (state_q == StWriteTableResp);

  assign table_status_valid = status_valid_i && selected_status_allowed;
  assign status_ready_o = table_status_ready && selected_status_allowed;

  directory_metadata_table u_metadata_table (
    .clk_i,
    .rst_ni,

    .read_valid_i      (table_read_valid),
    .read_ready_o      (table_read_ready),
    .read_index_i      (table_read_index),
    .read_valid_o      (table_read_resp_valid),
    .read_ready_i      (table_read_resp_ready),
    .read_state_o      (table_read_state),
    .read_sharers_o    (table_read_sharers),
    .read_owner_o      (table_read_owner),
    .read_data_valid_o (table_read_data_valid),
    .read_data_o       (table_read_data),

    .write_valid_i     (table_write_valid),
    .write_ready_o     (table_write_ready),
    .write_index_i     (table_write_index),
    .write_state_i     (table_write_state),
    .write_sharers_i   (table_write_sharers),
    .write_owner_i     (table_write_owner),
    .write_data_valid_i(table_write_data_valid),
    .write_data_i      (table_write_data),
    .write_done_valid_o(table_write_done_valid),
    .write_done_ready_i(table_write_done_ready),

    .status_valid_i      (table_status_valid),
    .status_ready_o      (table_status_ready),
    .status_index_i      (status_index_i),
    .status_valid_o      (status_valid_o),
    .status_ready_i      (status_ready_i),
    .status_state_o      (status_state_o),
    .status_sharers_o    (status_sharers_o),
    .status_owner_o      (status_owner_o),
    .status_data_valid_o (status_data_valid_o),
    .status_data_o       (status_data_o)
  );

  ////////////////////
  // Lookup planner //
  ////////////////////

  always_comb begin
    planned_state = active_state_q;
    planned_sharers = active_sharers_q;
    planned_owner = active_owner_q;
    planned_data_valid = active_data_valid_q;
    planned_data = active_data_q;
    planned_write = 1'b0;
    planned_send_ack = 1'b0;
    planned_ack_cmd = DirCmdNone;
    planned_ack_data = 32'b0;
    planned_send_snoop = 1'b0;
    planned_target_cache = 1'b0;
    planned_snoop_cmd = DirCmdNone;
    planned_expected_ack = SnoopAckNone;
    planned_done_no_ack = 1'b0;

    unique case (request_cmd_q)
      CacheCmdEvictClean: begin
        planned_done_no_ack = 1'b1;
        planned_write = 1'b1;
        planned_owner = 1'b0;

        if ((active_state_q == LineModified) &&
            (active_owner_q == request_cache_q)) begin
          planned_state = LineInvalid;
          planned_sharers = 2'b00;
        end else begin
          planned_sharers = remaining_sharers;
          if (remaining_sharers != 2'b00) begin
            planned_state = LineShared;
          end else begin
            planned_state = LineInvalid;
          end
        end
      end

      CacheCmdEvictDirty: begin
        planned_done_no_ack = 1'b1;
        planned_write = 1'b1;
        planned_state = LineInvalid;
        planned_sharers = 2'b00;
        planned_owner = 1'b0;
        planned_data_valid = 1'b1;
        planned_data = request_data_q;
      end

      CacheCmdBusRd: begin
        if ((active_state_q == LineModified) &&
            (active_owner_q != request_cache_q)) begin
          planned_send_snoop = 1'b1;
          planned_target_cache = active_owner_q;
          planned_snoop_cmd = DirCmdSnoopBusRd;
          planned_expected_ack = SnoopAckBusRd;
        end else begin
          planned_send_ack = 1'b1;
          planned_ack_cmd = DirCmdBusRdAck;
          planned_ack_data = selected_active_data;
          planned_write = 1'b1;
          planned_state = LineShared;
          planned_sharers = active_sharers_q | request_cache_bit;
          planned_owner = 1'b0;
          planned_data_valid = 1'b1;
          planned_data = selected_active_data;
        end
      end

      CacheCmdBusRdx: begin
        if ((active_state_q == LineModified) &&
            (active_owner_q != request_cache_q)) begin
          planned_send_snoop = 1'b1;
          planned_target_cache = active_owner_q;
          planned_snoop_cmd = DirCmdSnoopBusRdx;
          planned_expected_ack = SnoopAckBusRdx;
        end else if ((active_state_q == LineShared) && other_sharer_present) begin
          planned_send_snoop = 1'b1;
          planned_target_cache = !request_cache_q;
          planned_snoop_cmd = DirCmdSnoopBusUpgr;
          planned_expected_ack = SnoopAckBusUpgr;
        end else begin
          planned_send_ack = 1'b1;
          planned_ack_cmd = DirCmdBusRdxAck;
          planned_ack_data = selected_active_data;
          planned_write = 1'b1;
          planned_state = LineModified;
          planned_sharers = 2'b00;
          planned_owner = request_cache_q;
          planned_data_valid = 1'b1;
          planned_data = selected_active_data;
        end
      end

      CacheCmdBusUpgr: begin
        if ((active_state_q == LineShared) && other_sharer_present) begin
          planned_send_snoop = 1'b1;
          planned_target_cache = !request_cache_q;
          planned_snoop_cmd = DirCmdSnoopBusUpgr;
          planned_expected_ack = SnoopAckBusUpgr;
        end else begin
          planned_send_ack = 1'b1;
          planned_ack_cmd = DirCmdBusUpgrAck;
          planned_ack_data = 32'b0;
          planned_write = 1'b1;
          planned_state = LineModified;
          planned_sharers = 2'b00;
          planned_owner = request_cache_q;
          planned_data_valid = active_data_valid_q;
          planned_data = selected_active_data;
        end
      end

      default: begin
        planned_done_no_ack = 1'b1;
      end
    endcase
  end

  ////////////////////
  // Output routing //
  ////////////////////

  assign send_ready = send_cache ? c1_dir_ready_i : c0_dir_ready_i;

  always_comb begin
    c0_dir_valid_o = 1'b0;
    c0_dir_data_o = 32'b0;
    c0_dir_addr_o = 32'b0;
    c0_dir_cmd_o = DirCmdNone;

    c1_dir_valid_o = 1'b0;
    c1_dir_data_o = 32'b0;
    c1_dir_addr_o = 32'b0;
    c1_dir_cmd_o = DirCmdNone;

    if (send_valid && !send_cache) begin
      c0_dir_valid_o = 1'b1;
      c0_dir_data_o = send_data;
      c0_dir_addr_o = send_addr;
      c0_dir_cmd_o = send_cmd;
    end else if (send_valid && send_cache) begin
      c1_dir_valid_o = 1'b1;
      c1_dir_data_o = send_data;
      c1_dir_addr_o = send_addr;
      c1_dir_cmd_o = send_cmd;
    end
  end

  //////////////////////
  // Ready signalling //
  //////////////////////

  always_comb begin
    c0_bus_ready_o = 1'b0;
    c1_bus_ready_o = 1'b0;
    c0_snoop_ready_o = 1'b0;
    c1_snoop_ready_o = 1'b0;

    if (selected_request_accepted && !selected_cache) begin
      c0_bus_ready_o = 1'b1;
    end else if (selected_request_accepted && selected_cache) begin
      c1_bus_ready_o = 1'b1;
    end

    if (dirty_flush_accept && !target_cache_q) begin
      c0_bus_ready_o = 1'b1;
    end else if (dirty_flush_accept && target_cache_q) begin
      c1_bus_ready_o = 1'b1;
    end

    if (snoop_ack_accept && !target_cache_q) begin
      c0_snoop_ready_o = 1'b1;
    end else if (snoop_ack_accept && target_cache_q) begin
      c1_snoop_ready_o = 1'b1;
    end
  end

  //////////////////////
  // Main transaction //
  //////////////////////

  always_comb begin
    state_d = state_q;
    rr_priority_d = rr_priority_q;

    request_cache_d = request_cache_q;
    request_addr_d = request_addr_q;
    request_data_d = request_data_q;
    request_cmd_d = request_cmd_q;

    active_state_d = active_state_q;
    active_sharers_d = active_sharers_q;
    active_owner_d = active_owner_q;
    active_data_valid_d = active_data_valid_q;
    active_data_d = active_data_q;

    pending_write_d = pending_write_q;
    pending_state_d = pending_state_q;
    pending_sharers_d = pending_sharers_q;
    pending_owner_d = pending_owner_q;
    pending_data_valid_d = pending_data_valid_q;
    pending_data_d = pending_data_q;
    pending_ack_cmd_d = pending_ack_cmd_q;
    pending_ack_data_d = pending_ack_data_q;

    target_cache_d = target_cache_q;
    snoop_cmd_d = snoop_cmd_q;
    expected_ack_d = expected_ack_q;

    flush_seen_d = flush_seen_q;
    flush_data_d = flush_data_q;

    send_cache = 1'b0;
    send_valid = 1'b0;
    send_addr = 32'b0;
    send_data = 32'b0;
    send_cmd = DirCmdNone;

    unique case (state_q)
      StIdle: begin
        if (selected_request_accepted) begin
          request_cache_d = selected_cache;
          request_addr_d = selected_cache ? c1_bus_addr_i : c0_bus_addr_i;
          request_data_d = selected_cache ? c1_bus_wdata_i : c0_bus_wdata_i;
          request_cmd_d = selected_cache ? c1_bus_cache_cmd_i : c0_bus_cache_cmd_i;
          rr_priority_d = !selected_cache;
          state_d = StReadTable;
        end
      end

      StReadTable: begin
        if (table_read_resp_valid) begin
          active_state_d = table_read_state;
          active_sharers_d = table_read_sharers;
          active_owner_d = table_read_owner;
          active_data_valid_d = table_read_data_valid;
          active_data_d = table_read_data;
          state_d = StLookup;
        end
      end

      StLookup: begin
        if (planned_done_no_ack) begin
          pending_write_d = planned_write;
          pending_state_d = planned_state;
          pending_sharers_d = planned_sharers;
          pending_owner_d = planned_owner;
          pending_data_valid_d = planned_data_valid;
          pending_data_d = planned_data;

          if (planned_write) begin
            state_d = StWriteTableReq;
          end else begin
            state_d = StIdle;
          end
        end else if (planned_send_snoop) begin
          target_cache_d = planned_target_cache;
          snoop_cmd_d = planned_snoop_cmd;
          expected_ack_d = planned_expected_ack;
          state_d = StSendSnoop;
        end else if (planned_send_ack) begin
          pending_write_d = planned_write;
          pending_state_d = planned_state;
          pending_sharers_d = planned_sharers;
          pending_owner_d = planned_owner;
          pending_data_valid_d = planned_data_valid;
          pending_data_d = planned_data;
          pending_ack_cmd_d = planned_ack_cmd;
          pending_ack_data_d = planned_ack_data;
          state_d = StSendAck;
        end else begin
          state_d = StIdle;
        end
      end

      StSendSnoop: begin
        send_cache = target_cache_q;
        send_valid = 1'b1;
        send_addr = request_addr_q;
        send_data = 32'b0;
        send_cmd = snoop_cmd_q;

        if (send_ready) begin
          flush_seen_d = 1'b0;
          flush_data_d = 32'b0;
          state_d = StWaitSnoop;
        end
      end

      StWaitSnoop: begin
        if (dirty_flush_accept) begin
          flush_seen_d = 1'b1;
          flush_data_d = target_bus_data;
        end

        if (snoop_ack_accept) begin
          pending_write_d = 1'b1;
          pending_ack_data_d = finish_data;

          unique case (request_cmd_q)
            CacheCmdBusRd: begin
              pending_ack_cmd_d = DirCmdBusRdAck;
              pending_state_d = LineShared;
              pending_sharers_d = finish_request_cache_bit | finish_target_cache_bit;
              pending_owner_d = 1'b0;
              pending_data_valid_d = 1'b1;
              pending_data_d = finish_data;
            end

            CacheCmdBusRdx: begin
              pending_ack_cmd_d = DirCmdBusRdxAck;
              pending_state_d = LineModified;
              pending_sharers_d = 2'b00;
              pending_owner_d = request_cache_q;
              pending_data_valid_d = 1'b1;
              pending_data_d = finish_data;
            end

            CacheCmdBusUpgr: begin
              pending_ack_cmd_d = DirCmdBusUpgrAck;
              pending_ack_data_d = 32'b0;
              pending_state_d = LineModified;
              pending_sharers_d = 2'b00;
              pending_owner_d = request_cache_q;
              pending_data_valid_d = flush_seen_q || dirty_flush_accept || active_data_valid_q;
              pending_data_d = finish_data;
            end

            default: begin
              pending_write_d = 1'b0;
              pending_ack_cmd_d = DirCmdNone;
              pending_ack_data_d = 32'b0;
            end
          endcase

          state_d = StSendAck;
        end
      end

      StSendAck: begin
        send_cache = request_cache_q;
        send_valid = 1'b1;
        send_addr = request_addr_q;
        send_data = pending_ack_data_q;
        send_cmd = pending_ack_cmd_q;

        if (send_ready) begin
          if (pending_write_q) begin
            state_d = StWriteTableReq;
          end else begin
            state_d = StIdle;
          end
        end
      end

      StWriteTableReq: begin
        if (!pending_write_q) begin
          state_d = StIdle;
        end else if (table_write_ready) begin
          state_d = StWriteTableResp;
        end
      end

      StWriteTableResp: begin
        if (table_write_done_valid) begin
          pending_write_d = 1'b0;
          state_d = StIdle;
        end
      end

      default: begin
        state_d = StIdle;
      end
    endcase
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q <= StIdle;
      rr_priority_q <= 1'b0;

      request_cache_q <= 1'b0;
      request_addr_q <= 32'b0;
      request_data_q <= 32'b0;
      request_cmd_q <= CacheCmdNone;

      active_state_q <= LineInvalid;
      active_sharers_q <= 2'b00;
      active_owner_q <= 1'b0;
      active_data_valid_q <= 1'b0;
      active_data_q <= 32'b0;

      pending_write_q <= 1'b0;
      pending_state_q <= LineInvalid;
      pending_sharers_q <= 2'b00;
      pending_owner_q <= 1'b0;
      pending_data_valid_q <= 1'b0;
      pending_data_q <= 32'b0;
      pending_ack_cmd_q <= DirCmdNone;
      pending_ack_data_q <= 32'b0;

      target_cache_q <= 1'b0;
      snoop_cmd_q <= DirCmdNone;
      expected_ack_q <= SnoopAckNone;

      flush_seen_q <= 1'b0;
      flush_data_q <= 32'b0;
    end else begin
      state_q <= state_d;
      rr_priority_q <= rr_priority_d;

      request_cache_q <= request_cache_d;
      request_addr_q <= request_addr_d;
      request_data_q <= request_data_d;
      request_cmd_q <= request_cmd_d;

      active_state_q <= active_state_d;
      active_sharers_q <= active_sharers_d;
      active_owner_q <= active_owner_d;
      active_data_valid_q <= active_data_valid_d;
      active_data_q <= active_data_d;

      pending_write_q <= pending_write_d;
      pending_state_q <= pending_state_d;
      pending_sharers_q <= pending_sharers_d;
      pending_owner_q <= pending_owner_d;
      pending_data_valid_q <= pending_data_valid_d;
      pending_data_q <= pending_data_d;
      pending_ack_cmd_q <= pending_ack_cmd_d;
      pending_ack_data_q <= pending_ack_data_d;

      target_cache_q <= target_cache_d;
      snoop_cmd_q <= snoop_cmd_d;
      expected_ack_q <= expected_ack_d;

      flush_seen_q <= flush_seen_d;
      flush_data_q <= flush_data_d;
    end
  end

endmodule : directory_controller

`default_nettype wire

