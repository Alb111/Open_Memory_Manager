module wrr_arbiter (
	clk_i,
	rst_ni,
	req_i,
	weights_i,
	grant_o,
	req_o
);
	reg _sv2v_0;
	parameter NUM_REQ = 2;
	parameter WEIGHT_W = 3;
	input wire clk_i;
	input wire rst_ni;
	input wire [NUM_REQ - 1:0] req_i;
	input wire [(2 * WEIGHT_W) - 1:0] weights_i;
	output wire [NUM_REQ - 1:0] grant_o;
	output wire [NUM_REQ - 1:0] req_o;
	localparam PTR_MASK = NUM_REQ - 1;
	wire [WEIGHT_W - 1:0] weight0;
	wire [WEIGHT_W - 1:0] weight1;
	assign weight0 = weights_i[WEIGHT_W - 1:0];
	assign weight1 = weights_i[(2 * WEIGHT_W) - 1:WEIGHT_W];
	reg [$clog2(NUM_REQ) - 1:0] curr_ptr;
	reg [$clog2(NUM_REQ) - 1:0] next_ptr;
	reg [WEIGHT_W - 1:0] credit_cnt;
	reg [WEIGHT_W - 1:0] next_credit_cnt;
	reg [NUM_REQ - 1:0] next_grant;
	always @(*) begin
		if (_sv2v_0)
			;
		next_ptr = curr_ptr;
		next_credit_cnt = credit_cnt;
		next_grant = 1'sb0;
		if (req_i[curr_ptr]) begin
			next_grant[curr_ptr] = 1'b1;
			if (credit_cnt > 1)
				next_credit_cnt = credit_cnt - 1;
			else begin
				next_ptr = (curr_ptr + 1) & PTR_MASK;
				if (next_ptr == 0)
					next_credit_cnt = weight0;
				else
					next_credit_cnt = weight1;
			end
		end
		else begin
			next_ptr = (curr_ptr + 1) & PTR_MASK;
			if (next_ptr == 0)
				next_credit_cnt = weight0;
			else
				next_credit_cnt = weight1;
		end
	end
	always @(posedge clk_i)
		if (!rst_ni) begin
			curr_ptr <= 0;
			credit_cnt <= weight0;
		end
		else begin
			curr_ptr <= next_ptr;
			credit_cnt <= next_credit_cnt;
		end
	assign grant_o = (!rst_ni ? {NUM_REQ {1'sb0}} : next_grant);
	assign req_o = req_i;
	initial _sv2v_0 = 0;
endmodule
