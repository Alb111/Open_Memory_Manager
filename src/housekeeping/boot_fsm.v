module boot_fsm (
	clk_i,
	reset_i,
	spi_start_o,
	spi_out_o,
	spi_in_i,
	spi_done_i,
	spi_busy_i,
	flash_csb_o,
	cores_en_o,
	boot_done_o,
	sram_wr_en_o,
	sram_addr_o,
	sram_data_o
);
	reg _sv2v_0;
	parameter BOOT_SIZE = 32;
	parameter SRAM_BASE_ADDR = 32'h00000000;
	input wire clk_i;
	input wire reset_i;
	output reg spi_start_o;
	output reg [7:0] spi_out_o;
	input wire [7:0] spi_in_i;
	input wire spi_done_i;
	input wire spi_busy_i;
	output reg flash_csb_o;
	output reg cores_en_o;
	output reg boot_done_o;
	output reg sram_wr_en_o;
	output reg [31:0] sram_addr_o;
	output reg [31:0] sram_data_o;
	reg [3:0] curr_state;
	reg [3:0] next_state;
	reg [31:0] word_buffer;
	reg [1:0] byte_in_word;
	reg [31:0] byte_cntr;
	reg [31:0] sram_addr;
	reg [1:0] addr_byte_cnt;
	always @(posedge clk_i)
		if (reset_i)
			curr_state <= 4'd0;
		else
			curr_state <= next_state;
	always @(posedge clk_i)
		if (reset_i) begin
			word_buffer <= 32'h00000000;
			byte_in_word <= 2'd0;
			byte_cntr <= 32'h00000000;
			sram_addr <= SRAM_BASE_ADDR;
			addr_byte_cnt <= 2'd0;
		end
		else begin
			if (curr_state == 4'd0) begin
				byte_in_word <= 2'd0;
				addr_byte_cnt <= 2'd0;
				byte_cntr <= 32'h00000000;
			end
			if ((curr_state == 4'd4) && spi_done_i)
				addr_byte_cnt <= addr_byte_cnt + 1'b1;
			if ((curr_state == 4'd6) && spi_done_i) begin
				case (byte_in_word)
					2'd0: word_buffer[7:0] <= spi_in_i;
					2'd1: word_buffer[15:8] <= spi_in_i;
					2'd2: word_buffer[23:16] <= spi_in_i;
					2'd3: word_buffer[31:24] <= spi_in_i;
				endcase
				byte_in_word <= byte_in_word + 1'b1;
				byte_cntr <= byte_cntr + 1'b1;
			end
			if (curr_state == 4'd7) begin
				byte_in_word <= 2'd0;
				sram_addr <= sram_addr + 4;
			end
		end
	always @(*) begin
		if (_sv2v_0)
			;
		next_state = curr_state;
		spi_start_o = 1'b0;
		spi_out_o = 8'h00;
		flash_csb_o = 1'b1;
		sram_wr_en_o = 1'b0;
		sram_addr_o = sram_addr;
		sram_data_o = word_buffer;
		cores_en_o = 1'b0;
		boot_done_o = 1'b0;
		case (curr_state)
			4'd0: next_state = 4'd1;
			4'd1: begin
				flash_csb_o = 1'b0;
				spi_start_o = 1'b1;
				spi_out_o = 8'h03;
				next_state = 4'd2;
			end
			4'd2: begin
				flash_csb_o = 1'b0;
				if (spi_done_i)
					next_state = 4'd3;
			end
			4'd3: begin
				flash_csb_o = 1'b0;
				spi_start_o = 1'b1;
				spi_out_o = 8'h00;
				next_state = 4'd4;
			end
			4'd4: begin
				flash_csb_o = 1'b0;
				if (spi_done_i) begin
					if (addr_byte_cnt == 2'd2)
						next_state = 4'd5;
					else
						next_state = 4'd3;
				end
			end
			4'd5: begin
				flash_csb_o = 1'b0;
				spi_start_o = 1'b1;
				spi_out_o = 8'h00;
				next_state = 4'd6;
			end
			4'd6: begin
				flash_csb_o = 1'b0;
				if (spi_done_i) begin
					if (byte_in_word == 2'd3)
						next_state = 4'd7;
					else
						next_state = 4'd5;
				end
				else
					next_state = 4'd6;
			end
			4'd7: begin
				flash_csb_o = 1'b0;
				sram_wr_en_o = 1'b1;
				sram_addr_o = sram_addr;
				sram_data_o = word_buffer;
				if (byte_cntr >= BOOT_SIZE)
					next_state = 4'd8;
				else
					next_state = 4'd5;
			end
			4'd8: begin
				flash_csb_o = 1'b1;
				cores_en_o = 1'b1;
				boot_done_o = 1'b1;
				next_state = 4'd8;
			end
			default: next_state = 4'd0;
		endcase
	end
	initial _sv2v_0 = 0;
endmodule
