`timescale 1ns/1ps
`default_nettype none

// Cache controller for a direct-mapped MSI cache.
//
// Connections:
// - CPU side: native picoRV32-style memory interface from sp_addr_handler.
// - Data side: direct SRAM-style interface to cache.sv.
// - Directory side: decoded command/response interface to cache_interface.sv.
// - MSI side: instantiates the existing msi_protocol.sv module.
module cache_controller #(
  parameter int unsigned NumSets = 64,
  parameter int unsigned WordsPerLine = 4,
  localparam int unsigned SetWidth = $clog2(NumSets),
  localparam int unsigned WordWidth = $clog2(WordsPerLine),
  localparam int unsigned TagWidth = 32 - SetWidth - WordWidth - 2
) (
  input                    clk_i,
  input                    rst_ni,

  // Interface from sp_addr_handler.
  input                    mem_valid_i,
  output logic             mem_ready_o,
  input  [31:0]            mem_addr_i,
  input  [31:0]            mem_wdata_i,
  input  [3:0]             mem_wstrb_i,
  output logic [31:0]      mem_rdata_o,

  // Flush sideband from sp_addr_handler.
  input                    flush_valid_i,
  input  [31:0]            flush_addr_i,
  output logic             flush_ready_o,

  // Data cache SRAM interface.
  output logic             data_cache_rd_en_o,
  output logic [SetWidth-1:0] data_cache_rd_set_o,
  output logic [WordWidth-1:0] data_cache_rd_word_o,
  input  [31:0]            data_cache_rd_data_i,

  output logic             data_cache_wr_en_o,
  output logic [SetWidth-1:0] data_cache_wr_set_o,
  output logic [WordWidth-1:0] data_cache_wr_word_o,
  output logic [31:0]      data_cache_wr_data_o,
  output logic [3:0]       data_cache_wr_strb_o,
  input                    data_cache_ready_i,

  // Command path to cache_interface.
  output logic             cache_valid_o,
  input                    cache_ready_i,
  output logic [31:0]      cache_addr_o,
  output logic [31:0]      cache_data_o,
  output logic [8:0]       cache_cmd_o,

  // Bus acknowledgment path from cache_interface.
  input                    bus_valid_i,
  output logic             bus_ready_o,
  input  [31:0]            bus_data_i,
  input  [2:0]             bus_dircmd_i,

  // Snoop request path from cache_interface.
  input                    snoop_valid_i,
  output logic             snoop_ready_o,
  input  [31:0]            snoop_data_i,
  input  [2:0]             snoop_dircmd_i
);

  // MSI stable states used by msi_protocol.sv.
  localparam logic [1:0] MsiI = 2'b00;
  localparam logic [1:0] MsiS = 2'b01;
  localparam logic [1:0] MsiM = 2'b10;

  // Processor events used by msi_protocol.sv.
  localparam logic MsiProcRead = 1'b0;
  localparam logic MsiProcWrite = 1'b1;

  // Snoop events used by msi_protocol.sv.
  localparam logic [1:0] MsiSnoopBusRd = 2'd0;
  localparam logic [1:0] MsiSnoopBusRdx = 2'd1;
  localparam logic [1:0] MsiSnoopBusUpgr = 2'd2;

  // Three-bit command values produced by msi_protocol.sv.
  localparam logic [2:0] MsiCmdBusRd = 3'd0;
  localparam logic [2:0] MsiCmdBusRdx = 3'd1;
  localparam logic [2:0] MsiCmdBusUpgr = 3'd2;
  localparam logic [2:0] MsiCmdEvictClean = 3'd3;
  localparam logic [2:0] MsiCmdEvictDirty = 3'd4;
  localparam logic [2:0] MsiCmdSnoopBusRd = 3'd5;
  localparam logic [2:0] MsiCmdSnoopBusRdx = 3'd6;
  localparam logic [2:0] MsiCmdSnoopBusUpgr = 3'd7;

  // One-hot cache_interface command values.
  localparam logic [8:0] CacheCmdNone = 9'b000_000_000;
  localparam logic [8:0] CacheCmdBusRd = 9'b000_000_001;
  localparam logic [8:0] CacheCmdBusRdx = 9'b000_000_010;
  localparam logic [8:0] CacheCmdBusUpgr = 9'b000_000_100;
  localparam logic [8:0] CacheCmdEvictClean = 9'b000_001_000;
  localparam logic [8:0] CacheCmdEvictDirty = 9'b000_010_000;
  localparam logic [8:0] CacheCmdSnoopBusRdAck = 9'b000_100_000;
  localparam logic [8:0] CacheCmdSnoopBusRdxAck = 9'b001_000_000;
  localparam logic [8:0] CacheCmdSnoopBusUpgrAck = 9'b010_000_000;
  localparam logic [8:0] CacheCmdResetDone = 9'b100_000_000;

  // Decoded one-hot command values from cache_interface.
  localparam logic [2:0] DirCmdBusRdAck = 3'b001;
  localparam logic [2:0] DirCmdBusRdxAck = 3'b010;
  localparam logic [2:0] DirCmdBusUpgrAck = 3'b100;
  localparam logic [2:0] DirCmdSnoopBusRd = 3'b001;
  localparam logic [2:0] DirCmdSnoopBusRdx = 3'b010;
  localparam logic [2:0] DirCmdSnoopBusUpgr = 3'b100;

  typedef enum logic [2:0] {
    CtrlIdle,
    CtrlSendEvict,
    CtrlSendReq,
    CtrlWaitResp,
    CtrlSendSnoopResp,
    CtrlFlushSend
  } ctrl_state_e;

  ctrl_state_e ctrl_state_q;
  ctrl_state_e ctrl_state_d;

  logic [TagWidth-1:0] tag_q[NumSets];
  logic                valid_q[NumSets];
  logic [1:0]          msi_state_q[NumSets];

  logic [31:0] pending_addr_q;
  logic [31:0] pending_addr_d;
  logic [31:0] pending_wdata_q;
  logic [31:0] pending_wdata_d;
  logic [3:0]  pending_wstrb_q;
  logic [3:0]  pending_wstrb_d;
  logic        pending_write_q;
  logic        pending_write_d;
  logic [8:0]  pending_cmd_q;
  logic [8:0]  pending_cmd_d;
  logic [1:0]  pending_final_msi_q;
  logic [1:0]  pending_final_msi_d;

  logic [31:0] evict_addr_q;
  logic [31:0] evict_addr_d;
  logic [8:0]  evict_cmd_q;
  logic [8:0]  evict_cmd_d;

  logic [31:0] snoop_resp_addr_q;
  logic [31:0] snoop_resp_addr_d;
  logic [31:0] snoop_resp_data_q;
  logic [31:0] snoop_resp_data_d;
  logic [8:0]  snoop_resp_cmd_q;
  logic [8:0]  snoop_resp_cmd_d;
  logic [SetWidth-1:0] snoop_resp_set_q;
  logic [SetWidth-1:0] snoop_resp_set_d;
  logic [1:0]  snoop_resp_final_msi_q;
  logic [1:0]  snoop_resp_final_msi_d;
  logic        snoop_resp_valid_line_q;
  logic        snoop_resp_valid_line_d;

  logic [SetWidth-1:0] meta_set_d;
  logic [TagWidth-1:0] meta_tag_d;
  logic [1:0]          meta_state_d;
  logic                meta_valid_d;
  logic                meta_write_en_d;

  function automatic logic [SetWidth-1:0] get_set(input logic [31:0] addr);
    get_set = addr[WordWidth + 2 +: SetWidth];
  endfunction

  function automatic logic [WordWidth-1:0] get_word(input logic [31:0] addr);
    get_word = addr[2 +: WordWidth];
  endfunction

  function automatic logic [TagWidth-1:0] get_tag(input logic [31:0] addr);
    get_tag = addr[31 -: TagWidth];
  endfunction

  function automatic logic [31:0] build_addr(
    input logic [TagWidth-1:0] tag,
    input logic [SetWidth-1:0] set,
    input logic [WordWidth-1:0] word
  );
    build_addr = {tag, set, word, 2'b00};
  endfunction

  function automatic logic [31:0] merge_word(
    input logic [31:0] old_data,
    input logic [31:0] new_data,
    input logic [3:0]  strb
  );
    merge_word = old_data;
    if (strb[0]) begin
      merge_word[7:0] = new_data[7:0];
    end
    if (strb[1]) begin
      merge_word[15:8] = new_data[15:8];
    end
    if (strb[2]) begin
      merge_word[23:16] = new_data[23:16];
    end
    if (strb[3]) begin
      merge_word[31:24] = new_data[31:24];
    end
  endfunction

  function automatic logic [8:0] map_msi_cmd(input logic [2:0] msi_cmd);
    unique case (msi_cmd)
      MsiCmdBusRd:        map_msi_cmd = CacheCmdBusRd;
      MsiCmdBusRdx:       map_msi_cmd = CacheCmdBusRdx;
      MsiCmdBusUpgr:      map_msi_cmd = CacheCmdBusUpgr;
      MsiCmdEvictClean:   map_msi_cmd = CacheCmdEvictClean;
      MsiCmdEvictDirty:   map_msi_cmd = CacheCmdEvictDirty;
      MsiCmdSnoopBusRd:   map_msi_cmd = CacheCmdSnoopBusRdAck;
      MsiCmdSnoopBusRdx:  map_msi_cmd = CacheCmdSnoopBusRdxAck;
      MsiCmdSnoopBusUpgr: map_msi_cmd = CacheCmdSnoopBusUpgrAck;
      default:            map_msi_cmd = CacheCmdNone;
    endcase
  endfunction

  function automatic logic [1:0] decode_snoop_event(input logic [2:0] dir_cmd);
    unique case (dir_cmd)
      DirCmdSnoopBusRd:   decode_snoop_event = MsiSnoopBusRd;
      DirCmdSnoopBusRdx:  decode_snoop_event = MsiSnoopBusRdx;
      DirCmdSnoopBusUpgr: decode_snoop_event = MsiSnoopBusUpgr;
      default:            decode_snoop_event = MsiSnoopBusRd;
    endcase
  endfunction

  function automatic logic bus_ack_matches(
    input logic [8:0] req_cmd,
    input logic [2:0] ack_cmd
  );
    unique case (req_cmd)
      CacheCmdBusRd:   bus_ack_matches = (ack_cmd == DirCmdBusRdAck);
      CacheCmdBusRdx:  bus_ack_matches = (ack_cmd == DirCmdBusRdxAck);
      CacheCmdBusUpgr: bus_ack_matches = (ack_cmd == DirCmdBusUpgrAck);
      default:         bus_ack_matches = 1'b0;
    endcase
  endfunction

  logic [SetWidth-1:0] mem_set;
  logic [WordWidth-1:0] mem_word;
  logic [TagWidth-1:0] mem_tag;
  logic                mem_is_write;
  logic                mem_hit;
  logic [1:0]          mem_effective_msi;

  logic [SetWidth-1:0] flush_set;
  logic [WordWidth-1:0] flush_word;
  logic [TagWidth-1:0] flush_tag;
  logic                flush_hit;

  logic [SetWidth-1:0] snoop_set;
  logic [WordWidth-1:0] snoop_word;
  logic [TagWidth-1:0] snoop_tag;
  logic                snoop_hit;

  assign mem_set = get_set(mem_addr_i);
  assign mem_word = get_word(mem_addr_i);
  assign mem_tag = get_tag(mem_addr_i);
  assign mem_is_write = (mem_wstrb_i != 4'b0000);
  assign mem_hit = valid_q[mem_set] &&
                   (tag_q[mem_set] == mem_tag) &&
                   (msi_state_q[mem_set] != MsiI);
  assign mem_effective_msi = mem_hit ? msi_state_q[mem_set] : MsiI;

  assign flush_set = get_set(flush_addr_i);
  assign flush_word = get_word(flush_addr_i);
  assign flush_tag = get_tag(flush_addr_i);
  assign flush_hit = valid_q[flush_set] &&
                     (tag_q[flush_set] == flush_tag) &&
                     (msi_state_q[flush_set] != MsiI);

  assign snoop_set = get_set(snoop_data_i);
  assign snoop_word = get_word(snoop_data_i);
  assign snoop_tag = get_tag(snoop_data_i);
  assign snoop_hit = valid_q[snoop_set] &&
                     (tag_q[snoop_set] == snoop_tag) &&
                     (msi_state_q[snoop_set] != MsiI);

  logic       msi_proc_valid;
  logic       msi_proc_event;
  logic       msi_snoop_valid;
  logic [1:0] msi_snoop_event;
  logic [1:0] msi_current_state;
  logic [1:0] msi_next_state;
  logic       msi_cmd_valid;
  logic [2:0] msi_issue_cmd;
  logic       msi_flush;

  msi_protocol u_msi_protocol (
    .clk_i        (clk_i),
    .reset_i      (!rst_ni),
    .current_state(msi_current_state),
    .proc_valid   (msi_proc_valid),
    .proc_event   (msi_proc_event),
    .snoop_valid  (msi_snoop_valid),
    .snoop_event  (msi_snoop_event),
    .next_state   (msi_next_state),
    .cmd_valid    (msi_cmd_valid),
    .issue_cmd    (msi_issue_cmd),
    .flush        (msi_flush)
  );

  always_comb begin
    msi_current_state = mem_effective_msi;
    msi_proc_valid = 1'b0;
    msi_proc_event = mem_is_write ? MsiProcWrite : MsiProcRead;
    msi_snoop_valid = 1'b0;
    msi_snoop_event = MsiSnoopBusRd;

    if ((ctrl_state_q == CtrlIdle) && snoop_valid_i && snoop_hit) begin
      msi_current_state = msi_state_q[snoop_set];
      msi_snoop_valid = 1'b1;
      msi_snoop_event = decode_snoop_event(snoop_dircmd_i);
    end else if ((ctrl_state_q == CtrlIdle) && mem_valid_i) begin
      msi_current_state = mem_effective_msi;
      msi_proc_valid = 1'b1;
      msi_proc_event = mem_is_write ? MsiProcWrite : MsiProcRead;
    end
  end

  always_comb begin
    ctrl_state_d = ctrl_state_q;

    pending_addr_d = pending_addr_q;
    pending_wdata_d = pending_wdata_q;
    pending_wstrb_d = pending_wstrb_q;
    pending_write_d = pending_write_q;
    pending_cmd_d = pending_cmd_q;
    pending_final_msi_d = pending_final_msi_q;

    evict_addr_d = evict_addr_q;
    evict_cmd_d = evict_cmd_q;

    snoop_resp_addr_d = snoop_resp_addr_q;
    snoop_resp_data_d = snoop_resp_data_q;
    snoop_resp_cmd_d = snoop_resp_cmd_q;
    snoop_resp_set_d = snoop_resp_set_q;
    snoop_resp_final_msi_d = snoop_resp_final_msi_q;
    snoop_resp_valid_line_d = snoop_resp_valid_line_q;

    meta_write_en_d = 1'b0;
    meta_set_d = '0;
    meta_tag_d = '0;
    meta_state_d = MsiI;
    meta_valid_d = 1'b0;

    mem_ready_o = 1'b0;
    mem_rdata_o = 32'h0000_0000;
    flush_ready_o = 1'b0;

    data_cache_rd_en_o = 1'b0;
    data_cache_rd_set_o = mem_set;
    data_cache_rd_word_o = mem_word;
    data_cache_wr_en_o = 1'b0;
    data_cache_wr_set_o = mem_set;
    data_cache_wr_word_o = mem_word;
    data_cache_wr_data_o = mem_wdata_i;
    data_cache_wr_strb_o = mem_wstrb_i;

    cache_valid_o = 1'b0;
    cache_addr_o = 32'h0000_0000;
    cache_data_o = 32'h0000_0000;
    cache_cmd_o = CacheCmdNone;

    bus_ready_o = 1'b0;
    snoop_ready_o = 1'b0;

    unique case (ctrl_state_q)
      CtrlIdle: begin
        data_cache_rd_en_o = 1'b1;

        if (snoop_valid_i) begin
          data_cache_rd_set_o = snoop_set;
          data_cache_rd_word_o = snoop_word;
          snoop_ready_o = 1'b1;

          if (snoop_hit) begin
            meta_write_en_d = 1'b1;
            meta_set_d = snoop_set;
            meta_tag_d = tag_q[snoop_set];
            meta_state_d = msi_next_state;
            meta_valid_d = (msi_next_state != MsiI);

            if (msi_cmd_valid) begin
              cache_addr_o = snoop_data_i;
              cache_data_o = data_cache_rd_data_i;
              cache_cmd_o = map_msi_cmd(msi_issue_cmd);
              cache_valid_o = 1'b1;

              if (!cache_ready_i) begin
                snoop_resp_addr_d = snoop_data_i;
                snoop_resp_data_d = data_cache_rd_data_i;
                snoop_resp_cmd_d = map_msi_cmd(msi_issue_cmd);
                snoop_resp_set_d = snoop_set;
                snoop_resp_final_msi_d = msi_next_state;
                snoop_resp_valid_line_d = (msi_next_state != MsiI);
                ctrl_state_d = CtrlSendSnoopResp;
              end
            end else if (
                (snoop_dircmd_i == DirCmdSnoopBusUpgr) ||
                (snoop_dircmd_i == DirCmdSnoopBusRdx)
            ) begin
              cache_addr_o = snoop_data_i;
              cache_data_o = snoop_data_i;
              cache_cmd_o = CacheCmdSnoopBusUpgrAck;
              cache_valid_o = 1'b1;

              if (!cache_ready_i) begin
                snoop_resp_addr_d = snoop_data_i;
                snoop_resp_data_d = snoop_data_i;
                snoop_resp_cmd_d = CacheCmdSnoopBusUpgrAck;
                snoop_resp_set_d = snoop_set;
                snoop_resp_final_msi_d = msi_next_state;
                snoop_resp_valid_line_d = (msi_next_state != MsiI);
                ctrl_state_d = CtrlSendSnoopResp;
              end
            end
          end
        end else if (flush_valid_i) begin
          data_cache_rd_set_o = flush_set;
          data_cache_rd_word_o = flush_word;

          if (!flush_hit) begin
            flush_ready_o = 1'b1;
          end else begin
            cache_addr_o = flush_addr_i;
            cache_data_o = data_cache_rd_data_i;
            cache_cmd_o = (msi_state_q[flush_set] == MsiM) ?
                CacheCmdEvictDirty : CacheCmdEvictClean;
            cache_valid_o = 1'b1;

            if (cache_ready_i) begin
              flush_ready_o = 1'b1;
              meta_write_en_d = 1'b1;
              meta_set_d = flush_set;
              meta_tag_d = tag_q[flush_set];
              meta_state_d = MsiI;
              meta_valid_d = 1'b0;
            end else begin
              evict_addr_d = flush_addr_i;
              evict_cmd_d = (msi_state_q[flush_set] == MsiM) ?
                  CacheCmdEvictDirty : CacheCmdEvictClean;
              ctrl_state_d = CtrlFlushSend;
            end
          end
        end else if (mem_valid_i && data_cache_ready_i) begin
          data_cache_rd_set_o = mem_set;
          data_cache_rd_word_o = mem_word;

          if (mem_hit && !mem_is_write) begin
            mem_ready_o = 1'b1;
            mem_rdata_o = data_cache_rd_data_i;
          end else if (mem_hit && mem_is_write && (msi_state_q[mem_set] == MsiM)) begin
            data_cache_wr_en_o = 1'b1;
            data_cache_wr_set_o = mem_set;
            data_cache_wr_word_o = mem_word;
            data_cache_wr_data_o = mem_wdata_i;
            data_cache_wr_strb_o = mem_wstrb_i;
            mem_ready_o = 1'b1;
          end else begin
            pending_addr_d = mem_addr_i;
            pending_wdata_d = mem_wdata_i;
            pending_wstrb_d = mem_wstrb_i;
            pending_write_d = mem_is_write;
            pending_cmd_d = map_msi_cmd(msi_issue_cmd);
            pending_final_msi_d = msi_next_state;

            if (!mem_hit && valid_q[mem_set] && (msi_state_q[mem_set] != MsiI)) begin
              evict_addr_d = build_addr(tag_q[mem_set], mem_set, mem_word);
              evict_cmd_d = (msi_state_q[mem_set] == MsiM) ?
                  CacheCmdEvictDirty : CacheCmdEvictClean;
              ctrl_state_d = CtrlSendEvict;
            end else begin
              cache_addr_o = mem_addr_i;
              cache_data_o = 32'h0000_0000;
              cache_cmd_o = map_msi_cmd(msi_issue_cmd);
              cache_valid_o = msi_cmd_valid;

              if (msi_cmd_valid && cache_ready_i) begin
                ctrl_state_d = CtrlWaitResp;
              end else begin
                ctrl_state_d = CtrlSendReq;
              end
            end
          end
        end
      end

      CtrlSendEvict: begin
        data_cache_rd_en_o = 1'b1;
        data_cache_rd_set_o = get_set(evict_addr_q);
        data_cache_rd_word_o = get_word(evict_addr_q);

        cache_valid_o = 1'b1;
        cache_addr_o = evict_addr_q;
        cache_data_o = data_cache_rd_data_i;
        cache_cmd_o = evict_cmd_q;

        if (cache_ready_i) begin
          meta_write_en_d = 1'b1;
          meta_set_d = get_set(evict_addr_q);
          meta_tag_d = get_tag(evict_addr_q);
          meta_state_d = MsiI;
          meta_valid_d = 1'b0;
          ctrl_state_d = CtrlSendReq;
        end
      end

      CtrlSendReq: begin
        cache_valid_o = 1'b1;
        cache_addr_o = pending_addr_q;
        cache_data_o = 32'h0000_0000;
        cache_cmd_o = pending_cmd_q;

        if (cache_ready_i) begin
          ctrl_state_d = CtrlWaitResp;
        end
      end

      CtrlWaitResp: begin
        bus_ready_o = 1'b1;

        if (bus_valid_i && bus_ack_matches(pending_cmd_q, bus_dircmd_i)) begin
          data_cache_wr_en_o = 1'b1;
          data_cache_wr_set_o = get_set(pending_addr_q);
          data_cache_wr_word_o = get_word(pending_addr_q);

          if (pending_write_q) begin
            data_cache_wr_data_o = merge_word(bus_data_i, pending_wdata_q, pending_wstrb_q);
            data_cache_wr_strb_o = 4'b1111;
          end else begin
            data_cache_wr_data_o = bus_data_i;
            data_cache_wr_strb_o = 4'b1111;
          end

          meta_write_en_d = 1'b1;
          meta_set_d = get_set(pending_addr_q);
          meta_tag_d = get_tag(pending_addr_q);
          meta_state_d = pending_final_msi_q;
          meta_valid_d = (pending_final_msi_q != MsiI);

          mem_ready_o = 1'b1;
          mem_rdata_o = pending_write_q ? 32'h0000_0000 : bus_data_i;
          ctrl_state_d = CtrlIdle;
        end
      end

      CtrlSendSnoopResp: begin
        cache_valid_o = 1'b1;
        cache_addr_o = snoop_resp_addr_q;
        cache_data_o = snoop_resp_data_q;
        cache_cmd_o = snoop_resp_cmd_q;

        if (cache_ready_i) begin
          meta_write_en_d = 1'b1;
          meta_set_d = snoop_resp_set_q;
          meta_tag_d = tag_q[snoop_resp_set_q];
          meta_state_d = snoop_resp_final_msi_q;
          meta_valid_d = snoop_resp_valid_line_q;
          ctrl_state_d = CtrlIdle;
        end
      end

      CtrlFlushSend: begin
        data_cache_rd_en_o = 1'b1;
        data_cache_rd_set_o = get_set(evict_addr_q);
        data_cache_rd_word_o = get_word(evict_addr_q);

        cache_valid_o = 1'b1;
        cache_addr_o = evict_addr_q;
        cache_data_o = data_cache_rd_data_i;
        cache_cmd_o = evict_cmd_q;

        if (cache_ready_i) begin
          meta_write_en_d = 1'b1;
          meta_set_d = get_set(evict_addr_q);
          meta_tag_d = get_tag(evict_addr_q);
          meta_state_d = MsiI;
          meta_valid_d = 1'b0;
          flush_ready_o = 1'b1;
          ctrl_state_d = CtrlIdle;
        end
      end

      default: begin
        ctrl_state_d = CtrlIdle;
      end
    endcase
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      ctrl_state_q <= CtrlIdle;
      pending_addr_q <= 32'h0000_0000;
      pending_wdata_q <= 32'h0000_0000;
      pending_wstrb_q <= 4'b0000;
      pending_write_q <= 1'b0;
      pending_cmd_q <= CacheCmdNone;
      pending_final_msi_q <= MsiI;
      evict_addr_q <= 32'h0000_0000;
      evict_cmd_q <= CacheCmdNone;
      snoop_resp_addr_q <= 32'h0000_0000;
      snoop_resp_data_q <= 32'h0000_0000;
      snoop_resp_cmd_q <= CacheCmdNone;
      snoop_resp_set_q <= '0;
      snoop_resp_final_msi_q <= MsiI;
      snoop_resp_valid_line_q <= 1'b0;
    end else begin
      ctrl_state_q <= ctrl_state_d;
      pending_addr_q <= pending_addr_d;
      pending_wdata_q <= pending_wdata_d;
      pending_wstrb_q <= pending_wstrb_d;
      pending_write_q <= pending_write_d;
      pending_cmd_q <= pending_cmd_d;
      pending_final_msi_q <= pending_final_msi_d;
      evict_addr_q <= evict_addr_d;
      evict_cmd_q <= evict_cmd_d;
      snoop_resp_addr_q <= snoop_resp_addr_d;
      snoop_resp_data_q <= snoop_resp_data_d;
      snoop_resp_cmd_q <= snoop_resp_cmd_d;
      snoop_resp_set_q <= snoop_resp_set_d;
      snoop_resp_final_msi_q <= snoop_resp_final_msi_d;
      snoop_resp_valid_line_q <= snoop_resp_valid_line_d;
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      for (int unsigned i = 0; i < NumSets; i++) begin
        tag_q[i] <= '0;
        valid_q[i] <= 1'b0;
        msi_state_q[i] <= MsiI;
      end
    end else if (meta_write_en_d) begin
      tag_q[meta_set_d] <= meta_tag_d;
      valid_q[meta_set_d] <= meta_valid_d;
      msi_state_q[meta_set_d] <= meta_state_d;
    end
  end

endmodule : cache_controller

`default_nettype wire
