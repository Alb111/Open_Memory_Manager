// SPDX-FileCopyrightText: © 2025 Project Template Contributors
// SPDX-License-Identifier: Apache-2.0

`default_nettype none

`include "generated_defines.svh"
`include "slot_defines.svh"

`ifdef SRAM_gf180mcu_ocd_ip_sram
`define gf180mcu_xxx_ip_sram__sram512x8m8wm1 gf180mcu_ocd_ip_sram__sram512x8m8wm1
`else
`define gf180mcu_xxx_ip_sram__sram512x8m8wm1 gf180mcu_fd_ip_sram__sram512x8m8wm1
`endif

`ifdef PAD_gf180mcu_ocd_io
`define gf180mcu_xxx_io__vdd gf180mcu_ocd_io__vdd
`define gf180mcu_xxx_io__vss gf180mcu_ocd_io__vss
`define gf180mcu_xxx_io__dvdd gf180mcu_ocd_io__dvdd
`define gf180mcu_xxx_io__dvss gf180mcu_ocd_io__dvss
`define gf180mcu_xxx_io__in_s gf180mcu_ocd_io__in_s
`define gf180mcu_xxx_io__in_c gf180mcu_ocd_io__in_c
`define gf180mcu_xxx_io__bi_24t gf180mcu_ocd_io__bi_24t
`define gf180mcu_xxx_io__asig_5p0 gf180mcu_ocd_io__asig_5p0
`else
`define gf180mcu_xxx_io__vdd gf180mcu_fd_io__dvdd
`define gf180mcu_xxx_io__vss gf180mcu_fd_io__dvss
`define gf180mcu_xxx_io__dvdd gf180mcu_fd_io__dvdd
`define gf180mcu_xxx_io__dvss gf180mcu_fd_io__dvss
`define gf180mcu_xxx_io__in_s gf180mcu_fd_io__in_s
`define gf180mcu_xxx_io__in_c gf180mcu_fd_io__in_c
`define gf180mcu_xxx_io__bi_24t gf180mcu_fd_io__bi_24t
`define gf180mcu_xxx_io__asig_5p0 gf180mcu_fd_io__asig_5p0
`endif

module chip_top #(
    // Power/ground pads for I/O
    parameter NUM_DVDD_PADS = `NUM_DVDD_PADS,
    parameter NUM_DVSS_PADS = `NUM_DVSS_PADS,

    // Power/ground pads for core
    // parameter NUM_VDD_PADS = `NUM_VDD_PADS,
    // parameter NUM_VSS_PADS = `NUM_VSS_PADS,

    // Signal pads
    parameter NUM_BIDIR_PADS = `NUM_BIDIR_PADS
    )(
    `ifdef USE_POWER_PINS
    inout  wire VDD,
    inout  wire VSS,
    inout  wire DVDD,
    inout  wire DVSS,
    `endif

    inout  wire clk_PAD,
    inout  wire rst_n_PAD,
    
    inout  wire [NUM_BIDIR_PADS-1:0] bidir_PAD
);

    wire clk_PAD2CORE;
    wire rst_n_PAD2CORE;

    // Assert reset immediately, but release it only after two clock edges.
    // Raw pad reset is confined to these synchronizer flops so every reset
    // consumer in the core observes deassertion in the same clock domain.
    (* async_reg = "true" *) logic [1:0] reset_sync_ff;
    wire rst_n_sync;

    always_ff @(posedge clk_PAD2CORE or negedge rst_n_PAD2CORE) begin
        if (!rst_n_PAD2CORE)
            reset_sync_ff <= 2'b00;
        else
            reset_sync_ff <= {reset_sync_ff[0], 1'b1};
    end

    assign rst_n_sync = reset_sync_ff[1];

    wire [NUM_BIDIR_PADS-1:0] bidir_PAD2CORE;
    wire [NUM_BIDIR_PADS-1:0] bidir_CORE2PAD;
    wire [NUM_BIDIR_PADS-1:0] bidir_CORE2PAD_OE;
    wire [NUM_BIDIR_PADS-1:0] bidir_PAD_DRIVE;
    wire [NUM_BIDIR_PADS-1:0] bidir_PAD_OE;
    wire [NUM_BIDIR_PADS-1:0] bidir_PAD_IE;
    wire [NUM_BIDIR_PADS-1:0] bidir_CORE2PAD_CS;
    wire [NUM_BIDIR_PADS-1:0] bidir_CORE2PAD_SL;
    wire [NUM_BIDIR_PADS-1:0] bidir_CORE2PAD_IE;
    wire [NUM_BIDIR_PADS-1:0] bidir_CORE2PAD_PU;
    wire [NUM_BIDIR_PADS-1:0] bidir_CORE2PAD_PD;

    // debug_mode is a scan/functional-mode control with loads spread across
    // the core. Do not drive those loads directly from the I/O cell: the
    // pad's Y pin has a very small Liberty fanout limit, which otherwise makes
    // post-placement design repair build a pathological buffer tree. A strong
    // root followed by one branch per major core region keeps the pad fanout
    // at one and gives the placer useful physical partition points.
    wire       debug_mode_root;
    wire [3:0] debug_mode_branches;

    // Each receive-request pad drives a strong root and five local branches:
    // one for receive-state logic and four shared round-robin by shift words.
    localparam int C0_REQ_I_ID = 6;
    localparam int C1_REQ_I_ID = 40;
    localparam int C0_CLK_ID = 29;
    localparam int C1_CLK_ID = 63;
    localparam int REQ_I_BRANCHES = 5;
    wire c0_req_i_root;
    wire c1_req_i_root;
    wire [REQ_I_BRANCHES-1:0] c0_req_i_branches;
    wire [REQ_I_BRANCHES-1:0] c1_req_i_branches;

    // Forward the received clock through dedicated, kept output drivers. The
    // functional core clock remains on clk_PAD2CORE and is handled by CTS;
    // these two branches bypass the generic chip_core output-data network.
    wire c0_clk_to_pad;
    wire c1_clk_to_pad;

    // In the foundry pads, the I/O and
    // core voltage domains are shorted
    `ifdef USE_POWER_PINS
    `ifdef PAD_gf180mcu_fd_io
    assign VDD = DVDD;
    assign VSS = DVSS;
    `endif
    `endif

    // Power/ground pad instances
    generate
    for (genvar i=0; i<NUM_DVDD_PADS; i++) begin : dvdd_pads
        (* keep *)
        `gf180mcu_xxx_io__dvdd pad (
            `ifdef USE_POWER_PINS
            .DVDD   (DVDD),
            .DVSS   (DVSS),
            .VDD    (VDD),
            .VSS    (VSS)
            `endif
        );
    end
    for (genvar i=0; i<NUM_DVSS_PADS; i++) begin : dvss_pads
        (* keep *)
        `gf180mcu_xxx_io__dvss pad (
            `ifdef USE_POWER_PINS
            .DVDD   (DVDD),
            .DVSS   (DVSS),
            .VDD    (VDD),
            .VSS    (VSS)
            `endif
        );
    end
    // for (genvar i=0; i<NUM_VDD_PADS; i++) begin : vdd_pads
    //     (* keep *)
    //     `gf180mcu_xxx_io__vdd pad (
    //         `ifdef USE_POWER_PINS
    //         .DVDD   (DVDD),
    //         .DVSS   (DVSS),
    //         .VDD    (VDD),
    //         .VSS    (VSS)
    //         `endif
    //     );
    // end
    // for (genvar i=0; i<NUM_VSS_PADS; i++) begin : vss_pads
    //     (* keep *)
    //     `gf180mcu_xxx_io__vss pad (
    //         `ifdef USE_POWER_PINS
    //         .DVDD   (DVDD),
    //         .DVSS   (DVSS),
    //         .VDD    (VDD),
    //         .VSS    (VSS)
    //         `endif
    //     );
    // end
    endgenerate

    // Signal IO pad instances

    // Schmitt trigger
    `gf180mcu_xxx_io__in_s clk_pad (
        `ifdef USE_POWER_PINS
        .DVDD   (DVDD),
        .DVSS   (DVSS),
        .VDD    (VDD),
        .VSS    (VSS),
        `endif
    
        .Y      (clk_PAD2CORE),
        .PAD    (clk_PAD),
        
        .PU     (1'b0),
        .PD     (1'b0)
    );

    (* keep *) gf180mcu_fd_sc_mcu7t5v0__buf_16 c0_clk_forward_buf (
        `ifdef USE_POWER_PINS
        .VDD (VDD),
        .VSS (VSS),
        .VNW (VDD),
        .VPW (VSS),
        `endif
        .I   (clk_PAD2CORE),
        .Z   (c0_clk_to_pad)
    );

    (* keep *) gf180mcu_fd_sc_mcu7t5v0__buf_16 c1_clk_forward_buf (
        `ifdef USE_POWER_PINS
        .VDD (VDD),
        .VSS (VSS),
        .VNW (VDD),
        .VPW (VSS),
        `endif
        .I   (clk_PAD2CORE),
        .Z   (c1_clk_to_pad)
    );
    
    // Normal input
    `gf180mcu_xxx_io__in_c rst_n_pad (
        `ifdef USE_POWER_PINS
        .DVDD   (DVDD),
        .DVSS   (DVSS),
        .VDD    (VDD),
        .VSS    (VSS),
        `endif
    
        .Y      (rst_n_PAD2CORE),
        .PAD    (rst_n_PAD),
        
        .PU     (1'b0),
        .PD     (1'b0)
    );

    generate
    for (genvar i=0; i<NUM_BIDIR_PADS; i++) begin : bidir
        if (i == C0_CLK_ID) begin : c0_forwarded_clock
            assign bidir_PAD_DRIVE[i] = c0_clk_to_pad;
            assign bidir_PAD_OE[i] = 1'b1;
            assign bidir_PAD_IE[i] = 1'b0;
        end else if (i == C1_CLK_ID) begin : c1_forwarded_clock
            assign bidir_PAD_DRIVE[i] = c1_clk_to_pad;
            assign bidir_PAD_OE[i] = 1'b1;
            assign bidir_PAD_IE[i] = 1'b0;
        end else begin : core_signal
            assign bidir_PAD_DRIVE[i] = bidir_CORE2PAD[i];
            assign bidir_PAD_OE[i] = bidir_CORE2PAD_OE[i];
            assign bidir_PAD_IE[i] = bidir_CORE2PAD_IE[i];
        end

        (* keep *)
        `gf180mcu_xxx_io__bi_24t pad (
            `ifdef USE_POWER_PINS
            .DVDD   (DVDD),
            .DVSS   (DVSS),
            .VDD    (VDD),
            .VSS    (VSS),
            `endif
        
            .A      (bidir_PAD_DRIVE[i]),
            .OE     (bidir_PAD_OE[i]),
            .Y      (bidir_PAD2CORE[i]),
            .PAD    (bidir_PAD[i]),
            
            .CS     (bidir_CORE2PAD_CS[i]),
            .SL     (bidir_CORE2PAD_SL[i]),
            .IE     (bidir_PAD_IE[i]),

            .PU     (bidir_CORE2PAD_PU[i]),
            .PD     (bidir_CORE2PAD_PD[i])
        );
    end
    endgenerate

    (* keep *) gf180mcu_fd_sc_mcu7t5v0__buf_16 c0_req_i_root_buf (
        `ifdef USE_POWER_PINS
        .VDD (VDD),
        .VSS (VSS),
        .VNW (VDD),
        .VPW (VSS),
        `endif
        .I   (bidir_PAD2CORE[C0_REQ_I_ID]),
        .Z   (c0_req_i_root)
    );

    (* keep *) gf180mcu_fd_sc_mcu7t5v0__buf_16 c1_req_i_root_buf (
        `ifdef USE_POWER_PINS
        .VDD (VDD),
        .VSS (VSS),
        .VNW (VDD),
        .VPW (VSS),
        `endif
        .I   (bidir_PAD2CORE[C1_REQ_I_ID]),
        .Z   (c1_req_i_root)
    );

    generate
    for (genvar i=0; i<REQ_I_BRANCHES; i++) begin : c0_req_i_tree
        (* keep *) gf180mcu_fd_sc_mcu7t5v0__buf_16 branch_buf (
            `ifdef USE_POWER_PINS
            .VDD (VDD),
            .VSS (VSS),
            .VNW (VDD),
            .VPW (VSS),
            `endif
            .I   (c0_req_i_root),
            .Z   (c0_req_i_branches[i])
        );
    end
    for (genvar i=0; i<REQ_I_BRANCHES; i++) begin : c1_req_i_tree
        (* keep *) gf180mcu_fd_sc_mcu7t5v0__buf_16 branch_buf (
            `ifdef USE_POWER_PINS
            .VDD (VDD),
            .VSS (VSS),
            .VNW (VDD),
            .VPW (VSS),
            `endif
            .I   (c1_req_i_root),
            .Z   (c1_req_i_branches[i])
        );
    end
    endgenerate

    (* keep *) gf180mcu_fd_sc_mcu7t5v0__buf_16 debug_mode_root_buf (
        `ifdef USE_POWER_PINS
        .VDD (VDD),
        .VSS (VSS),
        .VNW (VDD),
        .VPW (VSS),
        `endif
        .I   (bidir_PAD2CORE[0]),
        .Z   (debug_mode_root)
    );

    generate
    for (genvar i=0; i<4; i++) begin : debug_mode_tree
        (* keep *) gf180mcu_fd_sc_mcu7t5v0__buf_16 branch_buf (
            `ifdef USE_POWER_PINS
            .VDD (VDD),
            .VSS (VSS),
            .VNW (VDD),
            .VPW (VSS),
            `endif
            .I   (debug_mode_root),
            .Z   (debug_mode_branches[i])
        );
    end
    endgenerate

    // Core design

    chip_core #(
        .NUM_BIDIR_PADS  (NUM_BIDIR_PADS)
    ) i_chip_core (
        `ifdef USE_POWER_PINS
        .VDD        (VDD),
        .VSS        (VSS),
        `endif
    
        .clk        (clk_PAD2CORE),
        .rst_n      (rst_n_sync),

        .debug_mode_i (debug_mode_branches),
        .c0_req_i_branches (c0_req_i_branches),
        .c1_req_i_branches (c1_req_i_branches),

        .bidir_in   (bidir_PAD2CORE),
        .bidir_out  (bidir_CORE2PAD),
        .bidir_oe   (bidir_CORE2PAD_OE),
        .bidir_cs   (bidir_CORE2PAD_CS),
        .bidir_sl   (bidir_CORE2PAD_SL),
        .bidir_ie   (bidir_CORE2PAD_IE),
        .bidir_pu   (bidir_CORE2PAD_PU),
        .bidir_pd   (bidir_CORE2PAD_PD)
    );
    
    // Do not remove, necessary for tapeout
    (* keep *) gf180mcu_ws_ip__qrcode_id qrcode_id ();
    (* keep *) gf180mcu_ws_ip__shuttle_id shuttle_id ();
    (* keep *) gf180mcu_ws_ip__project_id project_id ();
    (* keep *) gf180mcu_ws_ip__marker marker ();
    
    // wafer.space logo - can be removed if desired
    (* keep *) gf180mcu_ws_ip__logo wafer_space_logo ();

endmodule

`default_nettype wire
