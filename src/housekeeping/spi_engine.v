module spi_engine (
	clk_i,
	reset_i,
	start_i,
	data_in_i,
	data_out_o,
	done_o,
	busy_o,
	spi_sck_o,
	spi_mosi_o,
	spi_miso_i
);
	input wire clk_i;
	input wire reset_i;
	input wire start_i;
	input wire [7:0] data_in_i;
	output reg [7:0] data_out_o;
	output wire done_o;
	output wire busy_o;
	output wire spi_sck_o;
	output reg spi_mosi_o;
	input wire spi_miso_i;
	reg [1:0] curr_state;
	wire [1:0] next_state;
	reg [7:0] shift_out;
	reg [7:0] shift_in;
	reg [2:0] bit_cnt;
	reg [3:0] sck_div;
	always @(posedge clk_i)
		if (reset_i) begin
			curr_state <= 2'd0;
			bit_cnt <= 3'd0;
			shift_out <= 8'h00;
			shift_in <= 8'h00;
			data_out_o <= 8'h00;
			spi_mosi_o <= 1'b0;
			sck_div <= 4'd0;
		end
		else
			case (curr_state)
				2'd0: begin
					sck_div <= 4'd0;
					if (start_i) begin
						shift_out <= data_in_i;
						bit_cnt <= 3'd0;
						spi_mosi_o <= data_in_i[7];
						curr_state <= 2'd1;
					end
				end
				2'd1:
					if (sck_div == 4'd7) begin
						sck_div <= 4'd0;
						curr_state <= 2'd2;
						shift_in <= {shift_in[6:0], spi_miso_i};
					end
					else
						sck_div <= sck_div + 1'b1;
				2'd2:
					if (sck_div == 4'd7) begin
						sck_div <= 4'd0;
						if (bit_cnt == 3'd7)
							curr_state <= 2'd0;
						else begin
							bit_cnt <= bit_cnt + 1'b1;
							spi_mosi_o <= shift_out[6];
							shift_out <= {shift_out[6:0], 1'b0};
							curr_state <= 2'd1;
						end
					end
					else begin
						sck_div <= sck_div + 1'b1;
						if ((bit_cnt == 3'd7) && (sck_div == 4'd6))
							data_out_o <= shift_in;
					end
			endcase
	assign spi_sck_o = curr_state == 2'd2;
	assign done_o = ((curr_state == 2'd2) && (sck_div == 4'd7)) && (bit_cnt == 3'd7);
	assign busy_o = curr_state != 2'd0;
endmodule
