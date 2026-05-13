// SPDX-FileCopyrightText: © 2025 Albert Felix
// SPDX-License-Identifier: Apache-2.0

// MSI Cache Controller

`timescale 1ns/1ps
`default_nettype none

module cache_controller
(
  input  logic        clk_i,
  input  logic        rst_ni,

  // ── Processor → Cache ────────────────────────────────────────────
  input  logic        mem_valid,
  input  logic        mem_instr,
  input  logic [31:0] mem_addr,
  input  logic [31:0] mem_wdata,
  input  logic [3:0]  mem_wstrb,
  output logic        mem_ready,
  output logic [31:0] mem_rdata,

  // ── Cache → Directory (outbound coherence request) ────────────────
  output logic        cache_valid_o,
  output logic [31:0] cache_addr_o,
  output logic [31:0] cache_data_o,
  output logic [8:0]  cache_cmd_o,
  input  logic        cache_ready_i,

  // ── Directory → Cache (inbound coherence response) ────────────────
  input  logic        bus_valid_i,
  input  logic [31:0] bus_data_i,
  input  logic [2:0]  bus_dircmd_i,
  output logic        bus_ready_o,

  // ── Snoop Request (Directory → Cache) ─────────────────────────────
  input  logic        snoop_valid_i,
  input  logic [31:0] snoop_addr_i,
  input  logic [2:0]  snoop_dircmd_i,   
  output logic        snoop_ready_o
);

  // Local parameters
  localparam logic [1:0] S_INVALID  = 2'b00;
  localparam logic [1:0] S_SHARED   = 2'b01;
  localparam logic [1:0] S_MODIFIED = 2'b10;

  // cache to directory
  localparam logic [3:0] CMD_BUS_RD      = 4'b0001;
  localparam logic [3:0] CMD_BUS_RDX     = 4'b0010;
  localparam logic [3:0] CMD_BUS_UPGR    = 4'b0011;
  localparam logic [3:0] CMD_EVICT_CLEAN = 4'b0100;
  localparam logic [3:0] CMD_EVICT_DIRTY = 4'b1000;

  // directory to cache
  localparam logic [3:0] SNOOP_BUS_RD = 4'b1001; //9
  localparam logic [3:0] SNOOP_BUS_RDX = 4'b1010; //10
  localparam logic [3:0] SNOOP_BUS_UPGR = 4'b1011; //11
  

  // Address layout: addr[6:0]=index (7 bits), addr[8:7]=tag (2 bits)
  localparam int OFFSET_W = 0;
  localparam int INDEX_W  = 7;
  localparam int TAG_W    = 2;
  localparam int TAG_HI   = OFFSET_W + INDEX_W + TAG_W - 1;  // 8
  localparam int TAG_LO   = OFFSET_W + INDEX_W;               // 7

  // FSM state encodings
  typedef enum logic [3:0] {
    CPU_IDLE         = 4'd0,
    CPU_FETCH_LINE   = 4'd1,   // drive cache_mem read, wait for cm_ready_o
    CPU_CHECK_TAG    = 4'd2,   // compare tag
    CPU_TAG_MISMATCH = 4'd3,   // drive evict to directory
    CPU_EVICT_WAIT   = 4'd4,   // wait for directory evict ack
    CPU_TAG_MATCH    = 4'd5,   // decode read vs write
    CPU_READ         = 4'd6,   // latch proc-SM outputs (read path)
    CPU_WRITE        = 4'd7,   // latch proc-SM outputs (write path)
    CPU_CACHE_HIT_R  = 4'd8,   // re-read line from cache_mem (hit read)
    CPU_CACHE_READ   = 4'd9,   // return data to CPU
    CPU_CACHE_MISS_R = 4'd10,  // drive BUS_RD to directory
    CPU_DIR_RESP_R   = 4'd11,  // wait for directory response (read)
    CPU_CACHE_MISS_W = 4'd12,  // drive BUS_RDX/BUS_UPGR to directory
    CPU_DIR_RESP_W   = 4'd13,  // wait for directory response (write)
    CPU_CACHE_HIT_W  = 4'd14,  // write hit: apply wstrb, go to WRITE
    CPU_CACHE_WRITE  = 4'd15   // commit data+state to cache_mem
  } cpu_state_t;

  typedef enum logic [2:0] {
    SNP_IDLE          = 3'd0,
    SNP_FETCH_LINE    = 3'd1,  // drive cache_mem read, wait for cm_ready_o
    SNP_ON_SNOOP_EVT  = 3'd2,  // evaluate snoop SM outputs
    SNP_FLUSH_HANDLER = 3'd3,  // drive flush data to directory
    SNP_FLUSH_RESP    = 3'd4,  // wait for directory flush ack
    SNP_UPDATE_LINE   = 3'd5,  // commit new state to cache_mem
    SNP_DONE          = 3'd6   // pulse snoop_ready_o
  } snp_state_t;


  // Registers
  cpu_state_t cpu_state_q, cpu_state_d;
  snp_state_t snp_state_q, snp_state_d;

  logic [31:0] cpu_addr_q,      cpu_addr_d;
  logic [31:0] cpu_wdata_q,     cpu_wdata_d;
  logic [3:0]  cpu_wstrb_q,     cpu_wstrb_d;
  logic [1:0]  cpu_next_state_q, cpu_next_state_d;
  logic [2:0]  cpu_issue_cmd_q,  cpu_issue_cmd_d;
  logic        cpu_cmd_valid_q,  cpu_cmd_valid_d;
  logic [31:0] cpu_line_data_q,  cpu_line_data_d;

  logic [31:0] snp_addr_q,       snp_addr_d;
  logic [2:0]  snp_dircmd_q,     snp_dircmd_d;
  logic [1:0]  snp_next_state_q, snp_next_state_d;
  logic        snp_flush_q,      snp_flush_d;
  logic [31:0] snp_flush_data_q, snp_flush_data_d;

  // cache_mem wires
  // on_cpu_request port
  logic        cm_cpu_valid_i;
  logic        cm_cpu_ready_i;
  logic [31:0] cm_cpu_addr_i;
  logic [31:0] cm_cpu_wdata_i;
  logic [3:0]  cm_cpu_wstrb_i;
  logic [1:0]  cm_cpu_wstate_i;
  logic [1:0]  cm_cpu_wtag_i;
  logic        cm_cpu_ready_o;
  logic        cm_cpu_valid_o;
  logic [31:0] cm_cpu_line_data_o;
  logic [1:0]  cm_cpu_line_state_o;
  logic [1:0]  cm_cpu_line_tag_o;

  // on_snoop_request port
  logic        cm_snoop_valid_i;
  logic        cm_snoop_ready_i;
  logic [31:0] cm_snoop_addr_i;
  logic [31:0] cm_snoop_wdata_i;
  logic [3:0]  cm_snoop_wstrb_i;
  logic [1:0]  cm_snoop_wstate_i;
  logic [1:0]  cm_snoop_wtag_i;
  logic        cm_snoop_ready_o;
  logic        cm_snoop_valid_o;
  logic [31:0] cm_snoop_line_data_o;
  logic [1:0]  cm_snoop_line_state_o;
  logic [1:0]  cm_snoop_line_tag_o;
  

  // apply_wstrb instances
  logic [31:0] hit_data_written_over;   // hit write: base = existing line
  logic [31:0] miss_data_written_over;  // miss write: base = data from directory

  // on_processor_event_state_machine
  logic [1:0] on_processor_event_state_o;
  logic [2:0] on_processor_event_issue_cmd_o;
  logic       on_processor_event_cmd_valid_o;

  // on_snoop_event_state_machine
  logic [1:0] on_snoop_event_state_o;
  logic       on_snnop_event_flush_o;

  apply_wstrb u_apply_wstrb_hit (
    .base_data_i (line_data_r),
    .wdata_i     (cpu_wdata_q),
    .wstrb_i     (cpu_wstrb_q),
    .result_o    (hit_data_written_over)
  );

  apply_wstrb u_apply_wstrb_miss (
    .base_data_i (bus_data_i),
    .wdata_i     (cpu_wdata_q),
    .wstrb_i     (cpu_wstrb_q),
    .result_o    (miss_data_written_over)
  );

  on_snoop_event_state_machine u_snoop_sm (
    .current_state_i (cm_snoop_rstate_o),
    .snoop_event_i   (snp_dircmd_q[1:0]),  // 0=RD 1=RDX 2=UPGR
    .next_state_o    (on_snoop_event_state_o),
    .flush_o         (on_snnop_event_flush_o)
  );

  on_processor_event_state_machine u_proc_sm (
    .current_state_i   (cm_line_state_o), // state form cache_mem 
    .wstrb_i           (cpu_wstrb_q), // latched wrtsb
    .next_state_o      (on_processor_event_state_o),
    .issue_cmd_o       (proc_issue_cmd),
    .issue_cmd_valid_o (proc_cmd_valid)
  );


  two_port_cache_mem cache_mem
  (
    .clk_i(clk_i),
    .rst_ni(rst_ni),

     // on processor event port 
    .p0_valid_i(cm_cpu_valid_i),
    .p0_ready_o(cm_cpu_ready_o),
    .p0_addr_i(cm_cpu_addr_i),
    .p0_wdata_i(cm_cpu_wdata_i),
    .p0_wstrb_i(cm_cpu_wstrb_i),
    .p0_wstate_i(cm_cpu_wstate_i),
    .p0_wtag_i(cm_cpu_wtag_i),

    .p0_rdata_o(cm_cpu_rdata_o),
    .p0_rtag_o(cm_cpu_rtag_o),
    .p0_rstate_o(cm_cpu_rstate_o),
    .p0_valid_o(cm_cpu_valid_o),
    .p0_ready_i(cm_cpu_ready_i),

     // on snoop event port 
    .p1_valid_i(cm_snoop_valid_i),
    .p1_ready_o(cm_snoop_ready_o),
    .p1_addr_i(cm_snoop_addr_i),
    .p1_wdata_i(cm_snoop_wdata_i),
    .p1_wstrb_i(cm_snoop_wstrb_i),
    .p1_wstate_i(cm_snoop_wstate_i),
    .p1_wtag_i(cm_snoop_wtag_i),

    .p1_rdata_o(cm_snoop_rdata_o),
    .p1_rtag_o(cm_snoop_rtag_o),
    .p1_rstate_o(cm_snoop_rstate_o),
    .p1_valid_o(cm_snoop_valid_o),
    .p1_ready_i(cm_snoop_ready_i)
  );
  


  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      cpu_state_q      <= CPU_IDLE;
      snp_state_q      <= SNP_IDLE;
      cpu_addr_q       <= 32'b0;
      cpu_wdata_q      <= 32'b0;
      cpu_wstrb_q      <= 4'b0;
      cpu_next_state_q <= S_INVALID;
      cpu_issue_cmd_q  <= 3'b0;
      cpu_cmd_valid_q  <= 1'b0;
      cpu_line_data_q  <= 32'b0;
      snp_addr_q       <= 32'b0;
      snp_dircmd_q     <= 3'b0;
      snp_next_state_q <= S_INVALID;
      snp_flush_q      <= 1'b0;
      snp_flush_data_q <= 32'b0;
    end else begin
      cpu_state_q      <= cpu_state_d;
      snp_state_q      <= snp_state_d;
      cpu_addr_q       <= cpu_addr_d;
      cpu_wdata_q      <= cpu_wdata_d;
      cpu_wstrb_q      <= cpu_wstrb_d;
      cpu_next_state_q <= cpu_next_state_d;
      cpu_issue_cmd_q  <= cpu_issue_cmd_d;
      cpu_cmd_valid_q  <= cpu_cmd_valid_d;
      cpu_line_data_q  <= cpu_line_data_d;
      snp_addr_q       <= snp_addr_d;
      snp_dircmd_q     <= snp_dircmd_d;
      snp_next_state_q <= snp_next_state_d;
      snp_flush_q      <= snp_flush_d;
      snp_flush_data_q <= snp_flush_data_d;
    end
  end

  // Snoop FSM
  always_comb begin

    // flip flops
    snp_state_d      = snp_state_q;
    snp_addr_d       = snp_addr_q;
    snp_dircmd_d     = snp_dircmd_q;
    snp_next_state_d = snp_next_state_q;
    snp_flush_d      = snp_flush_q;
    snp_flush_data_d = snp_flush_data_q;

    // logic to control cache mem for snoop
    cm_snoop_valid_i = '0;
    cm_snoop_ready_i = '0;
    cm_snoop_addr_i  = '0;
    cm_snoop_wdata_i = '0;
    cm_snoop_wstrb_i = '0;
    cm_snoop_wstate_i = '0;
    cm_snoop_wtag_i = '0;

  
    case (snp_state_q)

      SNP_IDLE: begin
        if (snoop_valid_i) begin
          // latch the snoop data and addr
          snp_addr_d   = snoop_addr_i;
          snp_dircmd_d = snoop_dircmd_i;
          snp_state_d  = SNP_FETCH_LINE_REQ;
        end
      end

      SNP_FETCH_LINE_REQ: begin
        // set up the read request
        cm_snoop_valid_i = 1'b1;
        cm_snoop_addr_i  = snp_addr_q;
        cm_snoop_wstrb_i = '0; // send in a read req 
        if(cm_snoop_ready_o) begin
          snp_state_d  = SNP_FETCH_LINE_RESP_WAIT;
        end
      end

      SNP_FETCH_LINE_RESP_WAIT: begin
        if(cm_snoop_valid_o) begin
          cm_snoop_ready_i = 1'b1;
          snp_flush_data_d = cm_snoop_rdata_o;
          snp_state_d  = SNP_ON_SNOOP_EVT;
        end
      end

      SNP_ON_SNOOP_EVT: begin
        // latch on to the output of on_snoop_event
        snp_next_state_d = on_snoop_event_state_o;
        snp_flush_d      = on_snnop_event_flush_o;

        // flush if we need to
        if (on_snnop_event_flush_o) begin
          snp_state_d = SNP_FLUSH_HANDLER;
        end else begin
          snp_state_d = SNP_UPDATE_LINE;
        end
      end

      SNP_FLUSH_HANDLER: begin
        // wait for our cache -> directory to be ready
        if (cache_ready_i) begin
          snp_state_d = SNP_FLUSH_REQ;
        end
      end

      SNP_FLUSH_REQ: begin
        // put in the data to flush
        cache_valid_o = 1'b1;
        cache_addr_o = snp_addr_q;
        cache_data_o = snp_flush_data_d;

        if (snp_dircmd_d =

        cache_cmd_o = 
      end

      

      SNP_FLUSH_RESP: begin
        if (bus_valid_i) begin
          snp_state_d = SNP_UPDATE_LINE;
        end
      end

      SNP_UPDATE_LINE: begin
        snp_using_cm = 1'b1;
        if (cm_ready_o) begin
          snp_state_d = SNP_DONE;
        end
      end

      SNP_DONE: begin
        snoop_ready_o = 1'b1;
        snp_state_d   = SNP_IDLE;
      end

      default: snp_state_d = SNP_IDLE;
    endcase
  end

  // CPU FSM
  always_comb begin
    cpu_state_d      = cpu_state_q;
    cpu_addr_d       = cpu_addr_q;
    cpu_wdata_d      = cpu_wdata_q;
    cpu_wstrb_d      = cpu_wstrb_q;
    cpu_next_state_d = cpu_next_state_q;
    cpu_issue_cmd_d  = cpu_issue_cmd_q;
    cpu_cmd_valid_d  = cpu_cmd_valid_q;
    cpu_line_data_d  = cpu_line_data_q;

    cpu_using_cm = 1'b0;
    mem_ready    = 1'b0;
    mem_rdata    = 32'b0;

    case (cpu_state_q)

      CPU_IDLE: begin
        if (mem_valid && (snp_state_q == SNP_IDLE)) begin
          cpu_addr_d  = mem_addr;
          cpu_wdata_d = mem_wdata;
          cpu_wstrb_d = mem_wstrb;
          cpu_state_d = CPU_FETCH_LINE;
        end
      end

      // ── FETCH LINE ──────────────────────────────────────────────
      // Drive cache_mem read.  Transition on cm_ready_o.
      // cm_ready_i_sig = 0 in arbiter (don't auto-consume the output).
      CPU_FETCH_LINE: begin
        cpu_using_cm = 1'b1;
        if (cm_ready_o) begin          // ← FIX: was cm_valid_o
          cpu_state_d = CPU_CHECK_TAG;
        end
      end

      CPU_CHECK_TAG: begin
        // line_state_r / line_tag_r are stable: cache_mem output holds
        // its value until a new request is issued.
        if ((line_state_r == S_INVALID) ||
            (line_tag_r == cpu_addr_q[TAG_HI:TAG_LO])) begin
          cpu_state_d = CPU_TAG_MATCH;
        end else begin
          cpu_state_d = CPU_TAG_MISMATCH;
        end
      end

      CPU_TAG_MISMATCH: begin
        // Output mux drives evict command while in this state.
        if (cache_ready_i) begin
          cpu_state_d = CPU_EVICT_WAIT;
        end
      end

      CPU_EVICT_WAIT: begin
        if (bus_valid_i) begin
          // Slot is now INVALID; re-fetch so line_* signals are fresh.
          cpu_state_d = CPU_FETCH_LINE;
        end
      end

      CPU_TAG_MATCH: begin
        if (cpu_wstrb_q == 4'b0000) begin
          cpu_state_d = CPU_READ;
        end else begin
          cpu_state_d = CPU_WRITE;
        end
      end

      CPU_READ: begin
        // Proc SM is combinational on line_state_r (stable from FETCH).
        cpu_next_state_d = proc_next_state;
        cpu_issue_cmd_d  = proc_issue_cmd;
        cpu_cmd_valid_d  = proc_cmd_valid;
        if (proc_cmd_valid) begin
          cpu_state_d = CPU_CACHE_MISS_R;
        end else begin
          cpu_state_d = CPU_CACHE_HIT_R;
        end
      end

      // ── CACHE HIT (read) ────────────────────────────────────────
      // Re-read line per Image 2 ("CACHE READ" block reads cache mem).
      // cm_ready_i_sig = 0 in arbiter – hold output until CPU_CACHE_READ.
      CPU_CACHE_HIT_R: begin
        cpu_using_cm = 1'b1;
        if (cm_ready_o) begin          // ← FIX: was cm_valid_o
          cpu_state_d = CPU_CACHE_READ;
        end
      end

      CPU_CACHE_READ: begin
        // line_data_r is stable: no new cm request is in flight.
        mem_rdata   = line_data_r;
        mem_ready   = 1'b1;
        cpu_state_d = CPU_IDLE;
      end

      CPU_CACHE_MISS_R: begin
        if (cache_ready_i) begin
          cpu_state_d = CPU_DIR_RESP_R;
        end
      end

      CPU_DIR_RESP_R: begin
        if (bus_valid_i) begin
          cpu_line_data_d = bus_data_i;
          cpu_state_d     = CPU_CACHE_WRITE;
        end
      end

      CPU_WRITE: begin
        cpu_next_state_d = proc_next_state;
        cpu_issue_cmd_d  = proc_issue_cmd;
        cpu_cmd_valid_d  = proc_cmd_valid;
        if (proc_cmd_valid) begin
          cpu_state_d = CPU_CACHE_MISS_W;
        end else begin
          cpu_state_d = CPU_CACHE_HIT_W;
        end
      end

      CPU_CACHE_HIT_W: begin
        // hit_merged_data is combinational (apply_wstrb on line_data_r).
        // line_data_r is still the value from the original FETCH_LINE read.
        cpu_line_data_d = hit_merged_data;
        cpu_state_d     = CPU_CACHE_WRITE;
      end

      CPU_CACHE_MISS_W: begin
        if (cache_ready_i) begin
          cpu_state_d = CPU_DIR_RESP_W;
        end
      end

      CPU_DIR_RESP_W: begin
        if (bus_valid_i) begin
          // miss_merged_data = apply_wstrb(bus_data_i, cpu_wdata_q, cpu_wstrb_q)
          cpu_line_data_d = miss_merged_data;
          cpu_state_d     = CPU_CACHE_WRITE;
        end
      end

      CPU_CACHE_WRITE: begin
        cpu_using_cm = 1'b1;
        if (cm_ready_o) begin
          mem_ready   = 1'b1;
          cpu_state_d = CPU_IDLE;
        end
      end

      default: cpu_state_d = CPU_IDLE;
    endcase
  end

  // ================================================================
  // cache_mem arbitration mux  (Snoop > CPU)
  //
  // KEY: cm_ready_i_sig
  //   READ  states → 0  (don't consume output; FSM latches it next cycle)
  //   WRITE states → 1  (writes don't return useful data; consume freely)
  // ================================================================

  always_comb begin
    cm_valid       = 1'b0;
    cm_addr        = 32'b0;
    cm_wdata       = 32'b0;
    cm_wstrb       = 4'b0000;
    cm_wstate      = S_INVALID;
    cm_wtag        = 2'b00;
    cm_ready_i_sig = 1'b0;   // default: do NOT auto-consume

    if (snp_using_cm) begin

      case (snp_state_q)
        SNP_FETCH_LINE: begin
          cm_valid       = 1'b1;
          cm_addr        = snp_addr_q;
          cm_wdata       = 32'b0;
          cm_wstrb       = 4'b0000;   // read
          cm_wstate      = S_INVALID;
          cm_wtag        = 2'b00;
          cm_ready_i_sig = 1'b0;      // ← FIX: hold output; FSM samples next cycle
        end
        SNP_UPDATE_LINE: begin
          cm_valid       = 1'b1;
          cm_addr        = snp_addr_q;
          cm_wdata       = snp_flush_data_q;
          cm_wstrb       = 4'b1111;   // write all bytes
          cm_wstate      = snp_next_state_q;
          cm_wtag        = snp_addr_q[TAG_HI:TAG_LO];
          cm_ready_i_sig = 1'b1;      // writes: consume is harmless
        end
        default: ;
      endcase

    end else if (cpu_using_cm) begin

      case (cpu_state_q)
        CPU_FETCH_LINE,
        CPU_CACHE_HIT_R: begin
          cm_valid       = 1'b1;
          cm_addr        = cpu_addr_q;
          cm_wdata       = 32'b0;
          cm_wstrb       = 4'b0000;   // read
          cm_wstate      = S_INVALID;
          cm_wtag        = 2'b00;
          cm_ready_i_sig = 1'b0;      // ← FIX: hold output; FSM samples next cycle
        end
        CPU_CACHE_WRITE: begin
          cm_valid       = 1'b1;
          cm_addr        = cpu_addr_q;
          cm_wdata       = cpu_line_data_q;
          cm_wstrb       = 4'b1111;   // write all bytes
          cm_wstate      = cpu_next_state_q;
          cm_wtag        = cpu_addr_q[TAG_HI:TAG_LO];
          cm_ready_i_sig = 1'b1;      // writes: consume is harmless
        end
        default: ;
      endcase

    end
    // else: neither FSM active – all defaults (cm_valid=0, cm_ready_i_sig=0)
  end

  // ================================================================
  // Cache → Directory output mux  +  bus_ready_o
  // ================================================================

  always_comb begin
    cache_valid_o = 1'b0;
    cache_addr_o  = 32'b0;
    cache_data_o  = 32'b0;
    cache_cmd_o   = 9'b0;
    bus_ready_o   = 1'b0;

    if (snp_state_q == SNP_FLUSH_HANDLER) begin
      cache_valid_o = 1'b1;
      cache_addr_o  = snp_addr_q;
      cache_data_o  = snp_flush_data_q;
      cache_cmd_o   = CMD_EVICT_DIRTY;

    end else if (snp_state_q == SNP_FLUSH_RESP) begin
      bus_ready_o = bus_valid_i;

    end else begin
      bus_ready_o = bus_valid_i &
                    ((cpu_state_q == CPU_DIR_RESP_R) |
                     (cpu_state_q == CPU_DIR_RESP_W) |
                     (cpu_state_q == CPU_EVICT_WAIT));

      case (cpu_state_q)
        CPU_TAG_MISMATCH: begin
          cache_valid_o = 1'b1;
          cache_addr_o  = cpu_addr_q;
          // line_data_r and line_state_r are stable: only 1 cycle from FETCH
          cache_data_o  = line_data_r;
          cache_cmd_o   = (line_state_r == S_MODIFIED) ? CMD_EVICT_DIRTY
                                                       : CMD_EVICT_CLEAN;
        end
        CPU_CACHE_MISS_R: begin
          cache_valid_o = 1'b1;
          cache_addr_o  = cpu_addr_q;
          cache_data_o  = 32'b0;
          cache_cmd_o   = {6'b0, cpu_issue_cmd_q};
        end
        CPU_CACHE_MISS_W: begin
          cache_valid_o = 1'b1;
          cache_addr_o  = cpu_addr_q;
          cache_data_o  = 32'b0;
          cache_cmd_o   = {6'b0, cpu_issue_cmd_q};
        end
        default: ;
      endcase
    end
  end

endmodule

`default_nettype wire
