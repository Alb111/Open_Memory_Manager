// SPDX-License-Identifier: Apache-2.0
//
// Full-directory two-core MSI directory controller.
//
// This controller maintains coherence for every line in main memory: the line
// address is the directory index, so no tags are needed. It owns only the
// directory's protocol responsibilities:
//
//   * arbitrate between the two cache request ports (weighted round robin),
//   * read/modify/write the per-line directory metadata,
//   * issue snoops and collect snoop acknowledgements (they carry flushed data),
//   * move line data to and from main memory at the line's real address,
//   * return decoded responses on two independent per-cache interfaces.
//
// Explicitly out of scope (handled elsewhere):
//   * packet (de)serialization                -> directory_interface
//   * directory metadata storage + its reset  -> external mem2048x3 + reset
//   * main memory storage + its reset          -> external mem_ctrl_2048x32
// DFT: a concat scan chain over all functional registers is included below
// (debug_mode_i gated). Chain order: scan_in_i -> [18 controller regs] ->
// u_wrr_arbiter (curr_ptr, credit_cnt) -> scan_out_o.
//
// Metadata entry (3 bits, matches mem2048x3):
//   [1:0] sharers : bit0 = cache 0 holds a copy, bit1 = cache 1 holds a copy
//   [2]   dirty   : 1 => the single sharer owns a modified copy (memory stale)
// Derived states: INVALID = (sharers == 0); SHARED = (!dirty && sharers != 0);
// MODIFIED = dirty (exactly one sharer bit set, which identifies the owner).

`timescale 1ns/1ps
`default_nettype none

module directory_controller_full #(
  // Valid address space is [0, ADDR_SPACE_WORDS). Requests whose address falls
  // outside it are answered with zero data and never reach the memories. The
  // default spans the full 2048-line/word backing store, so it is a no-op until
  // narrowed.
  parameter logic [31:0] ADDR_SPACE_WORDS = 32'd8192
) (
  input  logic        clk_i,
  input  logic        rst_ni,

  // Cache 0 request path from directory_interface.
  input  logic        c0_bus_valid_i,
  input  logic [31:0] c0_bus_addr_i,
  input  logic [31:0] c0_bus_wdata_i,
  input  logic [3:0]  c0_bus_cache_cmd_i,
  output logic        c0_bus_ready_o,

  // Cache 0 snoop acknowledgement path from directory_interface.
  input  logic        c0_snoop_valid_i,
  input  logic [31:0] c0_snoop_data_i,
  input  logic [3:0]  c0_snoop_cache_cmd_i,
  output logic        c0_snoop_ready_o,

  // Cache 0 directory response path to directory_interface.
  output logic        c0_dir_valid_o,
  output logic [31:0] c0_dir_data_o,
  output logic [31:0] c0_dir_addr_o,
  output logic [3:0]  c0_dir_cmd_o,
  input  logic        c0_dir_ready_i,

  // Cache 1 request path from directory_interface.
  input  logic        c1_bus_valid_i,
  input  logic [31:0] c1_bus_addr_i,
  input  logic [31:0] c1_bus_wdata_i,
  input  logic [3:0]  c1_bus_cache_cmd_i,
  output logic        c1_bus_ready_o,

  // Cache 1 snoop acknowledgement path from directory_interface.
  input  logic        c1_snoop_valid_i,
  input  logic [31:0] c1_snoop_data_i,
  input  logic [3:0]  c1_snoop_cache_cmd_i,
  output logic        c1_snoop_ready_o,

  // Cache 1 directory response path to directory_interface.
  output logic        c1_dir_valid_o,
  output logic [31:0] c1_dir_data_o,
  output logic [31:0] c1_dir_addr_o,
  output logic [3:0]  c1_dir_cmd_o,
  input  logic        c1_dir_ready_i,

  // Directory metadata memory port (external mem2048x3). Reset/clear external.
  output logic        md_enable_n_o,   // active-low access enable
  output logic        md_we_o,         // 1 = write, 0 = read
  output logic [12:0] md_addr_o,       // line index
  output logic [2:0]  md_wdata_o,      // {dirty, sharers[1:0]}
  input  logic [2:0]  md_rdata_i,      // {dirty, sharers[1:0]}

  // Main memory port (external mem_ctrl_2048x32). Reset external.
  output logic        mm_valid_o,
  output logic        mm_instr_o,
  output logic [31:0] mm_addr_o,
  output logic [3:0]  mm_wstrb_o,      // per-byte write enable, 0 = read
  output logic [31:0] mm_wdata_o,
  input  logic [31:0] mm_rdata_i,
  input  logic        mm_ready_i,

  // Boot-size status register (words). Marks the instruction/data split:
  // instruction space [0, boot_len_i) served raw by InstrFetch, data space
  // normalized 0-based and re-offset by boot_len_i into physical memory. Static
  // after boot -- a plain config strap, not on any coherence timing path.
  input  logic [31:0] boot_len_i,

  // DFT scan chain (debug_mode_i is the scan/functional select).
  input  logic        debug_mode_i,
  input  logic        scan_in_i,
  output logic        scan_out_o
);

  // ---------------------------------------------------------------------------
  // Command / state encodings (values match directory_interface expectations).
  // ---------------------------------------------------------------------------
  // Normalized 4-bit binary command codes (match the serial-packet `metadata`
  // encoding end-to-end). Requests and their acks share a code; the transfer
  // direction disambiguates.
  localparam logic [3:0] CACHE_CMD_BUS_RD      = 4'd1;
  localparam logic [3:0] CACHE_CMD_BUS_RDX     = 4'd2;
  localparam logic [3:0] CACHE_CMD_BUS_UPGR    = 4'd3;
  localparam logic [3:0] CACHE_CMD_INSTR_FETCH = 4'd4;   // private instruction fetch
  localparam logic [3:0] CACHE_CMD_EVICT_CLEAN = 4'd5;
  localparam logic [3:0] CACHE_CMD_EVICT_DIRTY = 4'd6;

  localparam logic [3:0] SNOOP_ACK_NONE = 4'd0;

  localparam logic [3:0] DIR_CMD_NONE            = 4'd0;
  localparam logic [3:0] DIR_CMD_INSTR_FETCH_ACK = 4'd4;   // echoes InstrFetch (returns the word)
  localparam logic [3:0] DIR_CMD_BUS_RD_ACK      = 4'd1;   // echoes BusRD
  localparam logic [3:0] DIR_CMD_BUS_RDX_ACK     = 4'd2;   // echoes BusRDX
  localparam logic [3:0] DIR_CMD_BUS_UPGR_ACK    = 4'd3;   // echoes BusUPGR
  localparam logic [3:0] DIR_CMD_EVICT_DIRTY_ACK = 4'd6;   // echoes EvictDirty (writeback persisted)
  localparam logic [3:0] DIR_CMD_SNOOP_BUS_RD    = 4'd9;
  localparam logic [3:0] DIR_CMD_SNOOP_BUS_RDX   = 4'd10;
  localparam logic [3:0] DIR_CMD_SNOOP_BUS_UPGR  = 4'd11;

  typedef enum logic [3:0] {
    StIdle,
    StReadMetaReq,
    StReadMetaResp,
    StLookup,
    StReadDataReq,
    StReadDataResp,
    StSendSnoop,
    StWaitSnoop,
    StSendAck,
    StWriteData,
    StWriteMeta,
    StSendEvictAck,
    StDone
  } dir_state_e;

  dir_state_e state_d, state_q;

  // Captured request.
  logic        request_cache_d, request_cache_q;
  logic [31:0] request_addr_d,  request_addr_q;
  logic [31:0] request_data_d,  request_data_q;
  logic [3:0]  request_cmd_d,   request_cmd_q;

  // Metadata read back for the current line.
  logic [1:0] line_sharers_d, line_sharers_q;
  logic       line_dirty_d,   line_dirty_q;

  // Pending response to the requester.
  logic        pending_ack_cache_d, pending_ack_cache_q;
  logic [3:0]  pending_ack_cmd_d,   pending_ack_cmd_q;
  logic [31:0] pending_ack_data_d,  pending_ack_data_q;

  // Pending snoop to the conflicting cache.
  logic       pending_snoop_cache_d, pending_snoop_cache_q;
  logic [3:0] pending_snoop_cmd_d,   pending_snoop_cmd_q;

  // Pending metadata write-back.
  logic       pending_write_d,         pending_write_q;
  logic [1:0] pending_write_sharers_d, pending_write_sharers_q;
  logic       pending_write_dirty_d,   pending_write_dirty_q;

  // Pending main-memory data write-back.
  logic        pending_data_write_d, pending_data_write_q;
  logic [31:0] pending_data_d,       pending_data_q;

  // Sequencing.
  logic data_read_then_snoop_d, data_read_then_snoop_q;

  // Arbiter.
  logic [1:0] arb_req;
  logic [1:0] arb_grant;
  logic [1:0] arb_req_passthrough_unused;

  logic selected_valid;
  logic selected_cache;

  // Derived metadata views.
  logic [1:0] req_onehot;
  logic [1:0] snoop_onehot;
  logic       owner_cache;
  logic       other_is_sharer;
  logic       remote_modified;
  logic       line_shared;

  logic [12:0] request_index;

  logic [31:0] selected_addr;
  logic [3:0]  selected_cmd;
  logic        selected_in_range;
  logic        request_in_range;

  logic snoop_send_ready;
  logic ack_send_ready;
  logic snoop_ack_accept;
  logic [31:0] snoop_ack_data;

  // ---------------------------------------------------------------------------
  // DFT scan chain: concat of all 18 functional registers. A serial bit enters
  // at state_q (LSB); the vector MSB feeds u_wrr_arbiter, whose scan_out_o is
  // this module's scan_out_o. The register block below selects scan vs.
  // functional on debug_mode_i.
  // ---------------------------------------------------------------------------
  localparam int SCAN_N = 156;
  logic [SCAN_N-1:0] scan_state;
  assign scan_state = {
    data_read_then_snoop_q, pending_data_q, pending_data_write_q,
    pending_write_dirty_q, pending_write_sharers_q, pending_write_q,
    pending_snoop_cmd_q, pending_snoop_cache_q,
    pending_ack_data_q, pending_ack_cmd_q, pending_ack_cache_q,
    line_dirty_q, line_sharers_q,
    request_cmd_q, request_data_q, request_addr_q, request_cache_q,
    state_q
  };

  // ---------------------------------------------------------------------------
  // Arbitration (inside the controller). Scan chained after the controller regs.
  // ---------------------------------------------------------------------------
  assign arb_req = {c1_bus_valid_i, c0_bus_valid_i};

  wrr_arbiter #(
    .NUM_REQ  (2),
    .WEIGHT_W (3),
    .WEIGHTS  ({3'd1, 3'd1})
  ) u_wrr_arbiter (
    .clk_i     (clk_i),
    .rst_ni    (rst_ni),
    .req_i     (arb_req),
    .grant_o   (arb_grant),
    .req_o     (arb_req_passthrough_unused),
    .scan_en_i (debug_mode_i),
    .scan_in_i (scan_state[SCAN_N-1]),
    .scan_out_o(scan_out_o)
  );

  assign selected_valid = (arb_grant != 2'b00);
  assign selected_cache = arb_grant[1];

  // ---------------------------------------------------------------------------
  // Combinational metadata views.
  // ---------------------------------------------------------------------------
  assign request_index = request_addr_q[12:0];

  // Address-space bounds check, dynamic in boot_len. selected_* qualifies an
  // incoming request as it is accepted; request_* re-derives it for the captured
  // request. Instruction fetches live in [0, boot_len_i); normalized data lives
  // in [0, ADDR_SPACE_WORDS - boot_len_i) (it is re-offset by boot_len_i into the
  // physical store, so physical stays < ADDR_SPACE_WORDS).
  assign selected_addr     = selected_cache ? c1_bus_addr_i : c0_bus_addr_i;
  assign selected_cmd      = selected_cache ? c1_bus_cache_cmd_i : c0_bus_cache_cmd_i;
  assign selected_in_range = (selected_cmd == CACHE_CMD_INSTR_FETCH)
                           ? (selected_addr < boot_len_i)
                           : (selected_addr < (ADDR_SPACE_WORDS - boot_len_i));
  assign request_in_range  = (request_cmd_q == CACHE_CMD_INSTR_FETCH)
                           ? (request_addr_q < boot_len_i)
                           : (request_addr_q < (ADDR_SPACE_WORDS - boot_len_i));

  assign req_onehot   = request_cache_q ? 2'b10 : 2'b01;
  assign snoop_onehot = pending_snoop_cache_q ? 2'b10 : 2'b01;

  // In MODIFIED exactly one sharer bit is set and it names the owner.
  assign owner_cache     = line_sharers_q[1];
  assign other_is_sharer = request_cache_q ? line_sharers_q[0] : line_sharers_q[1];
  assign remote_modified = line_dirty_q && (owner_cache != request_cache_q);
  assign line_shared     = !line_dirty_q && (line_sharers_q != 2'b00);

  // ---------------------------------------------------------------------------
  // Snoop-phase helpers.
  // ---------------------------------------------------------------------------
  assign snoop_send_ready = pending_snoop_cache_q ? c1_dir_ready_i : c0_dir_ready_i;
  assign ack_send_ready   = pending_ack_cache_q   ? c1_dir_ready_i : c0_dir_ready_i;

  assign snoop_ack_accept =
      (state_q == StWaitSnoop) &&
      (pending_snoop_cache_q ? c1_snoop_valid_i : c0_snoop_valid_i) &&
      ((pending_snoop_cache_q ? c1_snoop_cache_cmd_i : c0_snoop_cache_cmd_i) !=
       SNOOP_ACK_NONE);

  // The snooped cache returns any flushed data inline on its snoop-ack channel.
  assign snoop_ack_data = pending_snoop_cache_q ? c1_snoop_data_i : c0_snoop_data_i;

  // ---------------------------------------------------------------------------
  // Metadata memory outputs.
  // ---------------------------------------------------------------------------
  always_comb begin
    md_enable_n_o = 1'b1;
    md_we_o       = 1'b0;
    md_addr_o     = request_index;
    md_wdata_o    = 3'b000;

    unique case (state_q)
      // Two-phase read: hold the index stable across the capture cycle so the
      // mem2048x3 bit-lane select matches the registered byte.
      StReadMetaReq, StReadMetaResp: begin
        md_enable_n_o = 1'b0;
        md_we_o       = 1'b0;
      end

      StWriteMeta: begin
        md_enable_n_o = 1'b0;
        md_we_o       = 1'b1;
        md_wdata_o    = {pending_write_dirty_q, pending_write_sharers_q};
      end

      default: begin
        md_enable_n_o = 1'b1;
      end
    endcase
  end

  // ---------------------------------------------------------------------------
  // Main memory outputs.
  // ---------------------------------------------------------------------------
  always_comb begin
    mm_valid_o = 1'b0;
    // Instruction fetches address main memory raw ([0, boot_len_i)); normalized
    // data is re-offset by boot_len_i into the physical store [boot_len_i, MEM).
    // boot_len_i is static, so this adder is off the coherence timing path.
    mm_instr_o = (request_cmd_q == CACHE_CMD_INSTR_FETCH);
    mm_addr_o  = (request_cmd_q == CACHE_CMD_INSTR_FETCH)
               ? request_addr_q
               : (request_addr_q + boot_len_i);
    mm_wstrb_o = 4'b0000;
    mm_wdata_o = 32'b0;

    unique case (state_q)
      // Two-phase read: hold address across the capture cycle for the bank mux.
      StReadDataReq, StReadDataResp: begin
        mm_valid_o = 1'b1;
        mm_wstrb_o = 4'b0000;
      end

      StWriteData: begin
        mm_valid_o = 1'b1;
        mm_wstrb_o = 4'b1111;
        mm_wdata_o = pending_data_q;
      end

      default: begin
        mm_valid_o = 1'b0;
      end
    endcase
  end

  // ---------------------------------------------------------------------------
  // Upstream request / snoop / response outputs (two independent interfaces).
  // ---------------------------------------------------------------------------
  always_comb begin
    c0_bus_ready_o   = 1'b0;
    c1_bus_ready_o   = 1'b0;
    c0_snoop_ready_o = 1'b0;
    c1_snoop_ready_o = 1'b0;

    c0_dir_valid_o = 1'b0;
    c0_dir_data_o  = 32'b0;
    c0_dir_addr_o  = 32'b0;
    c0_dir_cmd_o   = DIR_CMD_NONE;

    c1_dir_valid_o = 1'b0;
    c1_dir_data_o  = 32'b0;
    c1_dir_addr_o  = 32'b0;
    c1_dir_cmd_o   = DIR_CMD_NONE;

    // Accept a new request from the arbiter-selected cache.
    if ((state_q == StIdle) && selected_valid) begin
      if (selected_cache) c1_bus_ready_o = 1'b1;
      else                c0_bus_ready_o = 1'b1;
    end

    // Drive the snoop command to the conflicting cache.
    if ((state_q == StSendSnoop) || (state_q == StWaitSnoop)) begin
      if (pending_snoop_cache_q) begin
        c1_dir_valid_o = 1'b1;
        c1_dir_addr_o  = request_addr_q;
        c1_dir_cmd_o   = pending_snoop_cmd_q;
      end else begin
        c0_dir_valid_o = 1'b1;
        c0_dir_addr_o  = request_addr_q;
        c0_dir_cmd_o   = pending_snoop_cmd_q;
      end
    end

    // Deliver the decoded response to the requester.
    if (state_q == StSendAck) begin
      if (pending_ack_cache_q) begin
        c1_dir_valid_o = 1'b1;
        c1_dir_data_o  = pending_ack_data_q;
        c1_dir_addr_o  = request_addr_q;
        c1_dir_cmd_o   = pending_ack_cmd_q;
      end else begin
        c0_dir_valid_o = 1'b1;
        c0_dir_data_o  = pending_ack_data_q;
        c0_dir_addr_o  = request_addr_q;
        c0_dir_cmd_o   = pending_ack_cmd_q;
      end
    end

    // Acknowledge a persisted dirty writeback to the requester (echoes the
    // EvictDirty code). Gives the fire-and-forget evict flow control so the
    // cache can't clobber it in the lossy request pipe with the following refill.
    if (state_q == StSendEvictAck) begin
      if (pending_ack_cache_q) begin
        c1_dir_valid_o = 1'b1;
        c1_dir_addr_o  = request_addr_q;
        c1_dir_cmd_o   = DIR_CMD_EVICT_DIRTY_ACK;
      end else begin
        c0_dir_valid_o = 1'b1;
        c0_dir_addr_o  = request_addr_q;
        c0_dir_cmd_o   = DIR_CMD_EVICT_DIRTY_ACK;
      end
    end

    // Accept the snoop acknowledgement.
    if (snoop_ack_accept) begin
      if (pending_snoop_cache_q) c1_snoop_ready_o = 1'b1;
      else                       c0_snoop_ready_o = 1'b1;
    end
  end

  // ---------------------------------------------------------------------------
  // Next-state / register update logic.
  // ---------------------------------------------------------------------------
  always_comb begin
    state_d = state_q;

    request_cache_d = request_cache_q;
    request_addr_d  = request_addr_q;
    request_data_d  = request_data_q;
    request_cmd_d   = request_cmd_q;

    line_sharers_d = line_sharers_q;
    line_dirty_d   = line_dirty_q;

    pending_ack_cache_d = pending_ack_cache_q;
    pending_ack_cmd_d   = pending_ack_cmd_q;
    pending_ack_data_d  = pending_ack_data_q;

    pending_snoop_cache_d = pending_snoop_cache_q;
    pending_snoop_cmd_d   = pending_snoop_cmd_q;

    pending_write_d         = pending_write_q;
    pending_write_sharers_d = pending_write_sharers_q;
    pending_write_dirty_d   = pending_write_dirty_q;

    pending_data_write_d = pending_data_write_q;
    pending_data_d       = pending_data_q;

    data_read_then_snoop_d = data_read_then_snoop_q;

    unique case (state_q)
      // Accept one request selected by the weighted round-robin arbiter.
      StIdle: begin
        pending_write_d        = 1'b0;
        pending_data_write_d   = 1'b0;
        pending_ack_cmd_d      = DIR_CMD_NONE;
        pending_ack_data_d     = 32'b0;
        pending_snoop_cmd_d    = DIR_CMD_NONE;
        data_read_then_snoop_d = 1'b0;

        if (selected_valid) begin
          request_cache_d = selected_cache;
          request_addr_d  = selected_addr;
          request_data_d  = selected_cache ? c1_bus_wdata_i     : c0_bus_wdata_i;
          request_cmd_d   = selected_cache ? c1_bus_cache_cmd_i : c0_bus_cache_cmd_i;
          // Instruction fetches bypass coherence: never read metadata, go straight
          // to StLookup (which routes them to a raw main-memory read). Out-of-range
          // requests also skip the metadata read; StLookup emits a zero-data
          // response for them instead.
          if (selected_cmd == CACHE_CMD_INSTR_FETCH) state_d = StLookup;
          else if (selected_in_range)                state_d = StReadMetaReq;
          else                                       state_d = StLookup;
        end
      end

      StReadMetaReq: begin
        state_d = StReadMetaResp;
      end

      StReadMetaResp: begin
        line_sharers_d = md_rdata_i[1:0];
        line_dirty_d   = md_rdata_i[2];
        state_d = StLookup;
      end

      // Decide snoop / data-read / ack / write based on command and state.
      StLookup: begin
        pending_ack_cache_d = request_cache_q;
        pending_ack_cmd_d   = DIR_CMD_NONE;
        pending_ack_data_d  = 32'b0;

        pending_snoop_cache_d = !request_cache_q;
        pending_snoop_cmd_d   = DIR_CMD_NONE;

        pending_write_d         = 1'b0;
        pending_write_sharers_d = line_sharers_q;
        pending_write_dirty_d   = line_dirty_q;

        pending_data_write_d   = 1'b0;
        pending_data_d         = 32'b0;
        data_read_then_snoop_d = 1'b0;

        if (!request_in_range) begin
          // Address outside [0, ADDR_SPACE_WORDS): acknowledge read-type
          // requests with zero data and leave metadata and main memory
          // untouched. Evicts to unmapped addresses expect no response and are
          // simply dropped. pending_write_d / pending_data_write_d stay 0 (set
          // in the defaults above), so no memory write is issued.
          pending_ack_cache_d = request_cache_q;
          pending_ack_data_d  = 32'b0;

          unique case (request_cmd_q)
            CACHE_CMD_BUS_RD: begin
              pending_ack_cmd_d = DIR_CMD_BUS_RD_ACK;
              state_d = StSendAck;
            end
            CACHE_CMD_BUS_RDX: begin
              pending_ack_cmd_d = DIR_CMD_BUS_RDX_ACK;
              state_d = StSendAck;
            end
            CACHE_CMD_BUS_UPGR: begin
              pending_ack_cmd_d = DIR_CMD_BUS_UPGR_ACK;
              state_d = StSendAck;
            end
            CACHE_CMD_INSTR_FETCH: begin
              // Fetch past the instruction image: return zero (an illegal insn
              // that the core will trap on) without touching memory.
              pending_ack_cmd_d = DIR_CMD_INSTR_FETCH_ACK;
              state_d = StSendAck;
            end
            default: begin
              state_d = StIdle;
            end
          endcase
        end else begin
          unique case (request_cmd_q)
            CACHE_CMD_INSTR_FETCH: begin
              // Private instruction fetch: no metadata, no snoop, no writes.
              // Read main memory at the raw address (mm_addr_o handles the
              // no-offset case) and return the word.
              pending_ack_cmd_d = DIR_CMD_INSTR_FETCH_ACK;
              state_d = StReadDataReq;
            end

            CACHE_CMD_BUS_RD: begin
              if (remote_modified) begin
                pending_snoop_cache_d = owner_cache;
                pending_snoop_cmd_d   = DIR_CMD_SNOOP_BUS_RD;
                state_d = StSendSnoop;
              end else begin
                pending_ack_cmd_d       = DIR_CMD_BUS_RD_ACK;
                pending_write_d         = 1'b1;
                pending_write_dirty_d   = 1'b0;
                pending_write_sharers_d = line_sharers_q | req_onehot;
                state_d = StReadDataReq;
              end
            end

            CACHE_CMD_BUS_RDX: begin
              if (remote_modified) begin
                pending_snoop_cache_d = owner_cache;
                pending_snoop_cmd_d   = DIR_CMD_SNOOP_BUS_RDX;
                state_d = StSendSnoop;
              end else if (line_shared && other_is_sharer) begin
                pending_ack_cmd_d       = DIR_CMD_BUS_RDX_ACK;
                pending_snoop_cache_d   = !request_cache_q;
                pending_snoop_cmd_d     = DIR_CMD_SNOOP_BUS_UPGR;
                pending_write_d         = 1'b1;
                pending_write_dirty_d   = 1'b1;
                pending_write_sharers_d = req_onehot;
                data_read_then_snoop_d  = 1'b1;
                state_d = StReadDataReq;
              end else begin
                pending_ack_cmd_d       = DIR_CMD_BUS_RDX_ACK;
                pending_write_d         = 1'b1;
                pending_write_dirty_d   = 1'b1;
                pending_write_sharers_d = req_onehot;
                state_d = StReadDataReq;
              end
            end

            CACHE_CMD_BUS_UPGR: begin
              if (line_shared && other_is_sharer) begin
                pending_snoop_cache_d = !request_cache_q;
                pending_snoop_cmd_d   = DIR_CMD_SNOOP_BUS_UPGR;
                state_d = StSendSnoop;
              end else begin
                pending_ack_cmd_d       = DIR_CMD_BUS_UPGR_ACK;
                pending_write_d         = 1'b1;
                pending_write_dirty_d   = 1'b1;
                pending_write_sharers_d = req_onehot;
                state_d = StSendAck;
              end
            end

            CACHE_CMD_EVICT_CLEAN: begin
              pending_write_d         = 1'b1;
              pending_write_dirty_d   = 1'b0;
              pending_write_sharers_d = line_sharers_q & ~req_onehot;
              state_d = StWriteMeta;
            end

            CACHE_CMD_EVICT_DIRTY: begin
              pending_write_d         = 1'b1;
              pending_write_dirty_d   = 1'b0;
              pending_write_sharers_d = 2'b00;
              pending_data_write_d    = 1'b1;
              pending_data_d          = request_data_q;
              state_d = StWriteData;
            end

            default: begin
              state_d = StIdle;
            end
          endcase
        end
      end

      StReadDataReq: begin
        if (mm_ready_i) state_d = StReadDataResp;
      end

      StReadDataResp: begin
        pending_ack_data_d = mm_rdata_i;
        if (data_read_then_snoop_q) state_d = StSendSnoop;
        else                        state_d = StSendAck;
      end

      StSendSnoop: begin
        if (snoop_send_ready) state_d = StWaitSnoop;
      end

      StWaitSnoop: begin
        if (snoop_ack_accept) begin
          pending_ack_cache_d = request_cache_q;

          unique case (request_cmd_q)
            CACHE_CMD_BUS_RD: begin
              pending_ack_cmd_d       = DIR_CMD_BUS_RD_ACK;
              pending_ack_data_d      = snoop_ack_data;
              pending_write_d         = 1'b1;
              pending_write_dirty_d   = 1'b0;
              pending_write_sharers_d = req_onehot | snoop_onehot;
              pending_data_write_d    = 1'b1;
              pending_data_d          = snoop_ack_data;
            end

            CACHE_CMD_BUS_RDX: begin
              pending_ack_cmd_d       = DIR_CMD_BUS_RDX_ACK;
              pending_write_d         = 1'b1;
              pending_write_dirty_d   = 1'b1;
              pending_write_sharers_d = req_onehot;

              // An owner snoop always flushes the recovered data both to the
              // requester and back to memory, symmetric with SNOOP_BUS_RD. The
              // shared upgrade path already captured memory data before snooping.
              if (pending_snoop_cmd_q == DIR_CMD_SNOOP_BUS_RDX) begin
                pending_ack_data_d   = snoop_ack_data;
                pending_data_write_d = 1'b1;
                pending_data_d       = snoop_ack_data;
              end
            end

            CACHE_CMD_BUS_UPGR: begin
              pending_ack_cmd_d       = DIR_CMD_BUS_UPGR_ACK;
              pending_ack_data_d      = 32'b0;
              pending_write_d         = 1'b1;
              pending_write_dirty_d   = 1'b1;
              pending_write_sharers_d = req_onehot;
            end

            default: begin
              pending_ack_cmd_d = DIR_CMD_NONE;
              pending_write_d   = 1'b0;
            end
          endcase

          state_d = StSendAck;
        end
      end

      StSendAck: begin
        if (ack_send_ready) begin
          if      (pending_data_write_q) state_d = StWriteData;
          else if (pending_write_q)      state_d = StWriteMeta;
          else                           state_d = StIdle;
        end
      end

      StWriteData: begin
        if (mm_ready_i) begin
          if (pending_write_q) state_d = StWriteMeta;
          else                 state_d = StDone;
        end
      end

      StWriteMeta: begin
        // A dirty eviction gets an explicit ack once its data+meta are persisted.
        if (request_cmd_q == CACHE_CMD_EVICT_DIRTY) state_d = StSendEvictAck;
        else                                        state_d = StDone;
      end

      StSendEvictAck: begin
        if (ack_send_ready) state_d = StDone;
      end

      StDone: begin
        state_d = StIdle;
      end

      default: begin
        state_d = StIdle;
      end
    endcase
  end

  // ---------------------------------------------------------------------------
  // Registers. reset > scan (debug_mode_i) > functional, so functional updates
  // are selected unchanged whenever debug mode is low.
  // ---------------------------------------------------------------------------
  always_ff @(posedge clk_i) begin
    if (!rst_ni) begin
      state_q <= StIdle;

      request_cache_q <= 1'b0;
      request_addr_q  <= 32'b0;
      request_data_q  <= 32'b0;
      request_cmd_q   <= 4'b0;

      line_sharers_q <= 2'b00;
      line_dirty_q   <= 1'b0;

      pending_ack_cache_q <= 1'b0;
      pending_ack_cmd_q   <= DIR_CMD_NONE;
      pending_ack_data_q  <= 32'b0;

      pending_snoop_cache_q <= 1'b0;
      pending_snoop_cmd_q   <= DIR_CMD_NONE;

      pending_write_q         <= 1'b0;
      pending_write_sharers_q <= 2'b00;
      pending_write_dirty_q   <= 1'b0;

      pending_data_write_q <= 1'b0;
      pending_data_q       <= 32'b0;

      data_read_then_snoop_q <= 1'b0;
    end else if (debug_mode_i) begin
      // DFT scan shift: load the concat one bit, scan_in at the LSB (state_q).
      {
        data_read_then_snoop_q, pending_data_q, pending_data_write_q,
        pending_write_dirty_q, pending_write_sharers_q, pending_write_q,
        pending_snoop_cmd_q, pending_snoop_cache_q,
        pending_ack_data_q, pending_ack_cmd_q, pending_ack_cache_q,
        line_dirty_q, line_sharers_q,
        request_cmd_q, request_data_q, request_addr_q, request_cache_q,
        state_q
      } <= {scan_state[SCAN_N-2:0], scan_in_i};
    end else begin
      state_q <= state_d;

      request_cache_q <= request_cache_d;
      request_addr_q  <= request_addr_d;
      request_data_q  <= request_data_d;
      request_cmd_q   <= request_cmd_d;

      line_sharers_q <= line_sharers_d;
      line_dirty_q   <= line_dirty_d;

      pending_ack_cache_q <= pending_ack_cache_d;
      pending_ack_cmd_q   <= pending_ack_cmd_d;
      pending_ack_data_q  <= pending_ack_data_d;

      pending_snoop_cache_q <= pending_snoop_cache_d;
      pending_snoop_cmd_q   <= pending_snoop_cmd_d;

      pending_write_q         <= pending_write_d;
      pending_write_sharers_q <= pending_write_sharers_d;
      pending_write_dirty_q   <= pending_write_dirty_d;

      pending_data_write_q <= pending_data_write_d;
      pending_data_q       <= pending_data_d;

      data_read_then_snoop_q <= data_read_then_snoop_d;
    end
  end

endmodule : directory_controller_full

`default_nettype wire
