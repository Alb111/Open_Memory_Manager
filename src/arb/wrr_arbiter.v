module wrr_arbiter (
	clk_i,
	rst_i,
	req_i,
	grant_o,
	req_o
);
	reg _sv2v_0;
	parameter NUM_REQ = 2;
	parameter WEIGHT_W = 3;
	parameter [(NUM_REQ * WEIGHT_W) - 1:0] WEIGHTS = 6'h09;
	input wire clk_i;
	input wire rst_i;
	input wire [NUM_REQ - 1:0] req_i;
	output wire [NUM_REQ - 1:0] grant_o;
	output wire [NUM_REQ - 1:0] req_o;
	localparam PTR_MASK = NUM_REQ - 1;
	reg [$clog2(NUM_REQ) - 1:0] curr_ptr;
	reg [$clog2(NUM_REQ) - 1:0] next_ptr;
	wire [WEIGHT_W - 1:0] weight_table [NUM_REQ - 1:0];
	reg [WEIGHT_W - 1:0] credit_cnt;
	reg [WEIGHT_W - 1:0] next_credit_cnt;
	reg [NUM_REQ - 1:0] next_grant;
	genvar _gv_i_1;
	generate
		for (_gv_i_1 = 0; _gv_i_1 < NUM_REQ; _gv_i_1 = _gv_i_1 + 1) begin : genblk1
			localparam i = _gv_i_1;
			assign weight_table[i] = WEIGHTS[((i * WEIGHT_W) + WEIGHT_W) - 1:i * WEIGHT_W];
		end
	endgenerate
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
				next_credit_cnt = weight_table[next_ptr];
			end
		end
		else begin
			next_ptr = (curr_ptr + 1) & PTR_MASK;
			next_credit_cnt = weight_table[next_ptr];
		end
	end
	always @(posedge clk_i)
		if (rst_i) begin
			curr_ptr <= 1'sb0;
			credit_cnt <= weight_table[0];
		end
		else begin
			curr_ptr <= next_ptr;
			credit_cnt <= next_credit_cnt;
		end
	assign grant_o = (rst_i ? {NUM_REQ {1'sb0}} : next_grant);
	assign req_o = req_i;
	initial _sv2v_0 = 0;
endmodule
