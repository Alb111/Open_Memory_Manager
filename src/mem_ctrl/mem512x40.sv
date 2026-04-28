// SPDX-FileCopyrightText: © 2025 Albert Felix
// SPDX-License-Identifier: Apache-2.0

`default_nettype none

module mem_ctrl_512x40
(
	input wire         clk_i,
	input wire         rst_ni,	

	// input interface
	input  wire [0:0]   mem_valid_i,
	output wire [0:0]   mem_ready_o,
	input  wire [31:0]  mem_addr_i,
	input  wire [39:0]  mem_wdata_i,
	input  wire [3:0]   mem_wstrb_i,   

	// output interface 	
	output wire [39:0] mem_rdata_o,
	output wire [0:0]  mem_valid_o,
	input wire  [0:0]  mem_ready_i
);
	
	// States
  typedef enum logic [2:0] {
			RESET_SRAMS = 3'b000, 
			RESET_DATA  = 3'b001,
      IDLE        = 3'b010,
      MEM_REQ     = 3'b011,
      MEM_RESP    = 3'b100
  } state_t;

  state_t state_q, state_d;
	logic [8:0]  reset_addr_q, reset_addr_d;
	logic [8:0]  addr_q, addr_d;
	logic [39:0] wdata_q, wdata_d;
	logic [3:0] mode_q, mode_d;

  always_ff @(posedge clk_i) begin
      if (!rst_ni) begin
          state_q <= RESET_SRAMS;
					reset_addr_q <= '0;
					addr_q <= '0;
					wdata_q <= '0;
					mode_q <= '0;
      end else begin
          state_q <= state_d;
					reset_addr_q <= reset_addr_d;
					addr_q <= addr_d;
					wdata_q <= wdata_d;
					mode_q <= mode_d;
      end
  end

  always_comb begin
      state_d = state_q;
			reset_addr_d = reset_addr_q;
			addr_d = addr_q;
			wdata_d = wdata_q;
			mode_d = mode_q;
			
      case (state_q)

					RESET_SRAMS: begin
						state_d = RESET_DATA;
					end

          RESET_DATA: begin
						if (reset_addr_q == 10'd511) state_d = IDLE;
						reset_addr_d = reset_addr_q + 1;
          end
			
          IDLE: begin
            if (mem_valid_i && mem_ready_o) begin
							state_d = MEM_REQ;
							addr_d = mem_addr_i[8:0];
							wdata_d = mem_wdata_i;
							mode_d = mem_wstrb_i;
						end
          end
          
          MEM_REQ: begin
            state_d = MEM_RESP;
          end
          
          MEM_RESP: begin
            if (mem_valid_o && mem_ready_i) state_d = IDLE;
          end
          
          default: state_d = IDLE;
      endcase
  end

	// ready valid logic
	assign mem_ready_o = (state_q == IDLE);
	assign mem_valid_o = (state_q == MEM_RESP);

	// sram control signal logic
	logic [0:0]  sram_enable_n;
	logic [8:0]  sram_addr;
	logic [39:0] data_to_write;
	logic [39:0] data_read;
	logic [3:0]  sram_mode;

	// data outputs
	assign mem_rdata_o = data_read;

	always_comb begin
		if (state_q == RESET_SRAMS) begin
			sram_enable_n = 1;
			sram_addr = 32'd0;
			data_to_write = 56'd0;
			sram_mode = 4'd0;
		end
		else if (state_q == RESET_DATA) begin
			sram_enable_n = 1'b0;
			sram_addr = reset_addr_q;
			data_to_write = 56'd0;
			sram_mode = 4'b1111; 
		end
		else begin
			sram_enable_n = (state_q != MEM_REQ);
			sram_addr = addr_q;
			data_to_write = wdata_q;
			sram_mode = mode_q;
		end
	end



	gf180mcu_fd_ip_sram__sram512x8m8wm1 sram0 (
		.CLK(clk_i),
		.CEN(sram_enable_n), 
		.GWEN(~sram_mode[0]),
		.WEN(8'b0),
		.A(sram_addr),
		.D(data_to_write[7:0]),
		.Q(data_read[7:0]),
		.VDD(),
		.VSS()
	);

	gf180mcu_fd_ip_sram__sram512x8m8wm1 sram1 (
		.CLK(clk_i),
		.CEN(sram_enable_n), 
		.GWEN(~sram_mode[1]),
		.WEN(8'b0),
		.A(sram_addr),
		.D(data_to_write[15:8]),
		.Q(data_read[15:8]),
		.VDD(),
		.VSS()
	);

	gf180mcu_fd_ip_sram__sram512x8m8wm1 sram2 (
		.CLK(clk_i),
		.CEN(sram_enable_n), 
		.GWEN(~sram_mode[2]),
		.WEN(8'b0),
		.A(sram_addr),
		.D(data_to_write[23:16]),
		.Q(data_read[23:16]),
		.VDD(),
		.VSS()
	);

	gf180mcu_fd_ip_sram__sram512x8m8wm1 sram3 (
		.CLK(clk_i),
		.CEN(sram_enable_n), 
		.GWEN(~sram_mode[3]),
		.WEN(8'b0),
		.A(sram_addr),
		.D(data_to_write[31:24]),
		.Q(data_read[31:24]),
		.VDD(),
		.VSS()
	);


	gf180mcu_fd_ip_sram__sram512x8m8wm1 sram4 (
		.CLK(clk_i),
		.CEN(sram_enable_n), 
		.GWEN(~sram_mode[0]),
		.WEN(8'b0),
		.A(sram_addr),
		.D(data_to_write[39:32]),
		.Q(data_read[39:32]),
		.VDD(),
		.VSS()
	);

endmodule

`default_nettype wire
