module spi_engine (
    input logic clk_i,
    input logic reset_i,

    input logic start_i,
    input logic [7:0] data_in_i,
    output logic [7:0] data_out_o,
    output logic done_o,
    output logic busy_o,

    //spi pins
    output logic spi_sck_o,
    output logic spi_mosi_o,
    input logic spi_miso_i
    //output logic spi_csb_o
);
    typedef enum logic [1:0] {IDLE, SHIFT} spi_state_t;

    spi_state_t curr_state, next_state;

    logic [7:0] shift_out, shift_in;
    logic [2:0] bit_cnt;


    //clock speed
    // logic [2:0] div;
    // logic sck_en;

    //state reg
    always_ff @(posedge clk_i) begin
        if(reset_i) begin
            curr_state <= IDLE;
        end else begin
            curr_state <= next_state;
        end
    end

    //data path
    always_ff @(posedge clk_i) begin
        if(reset_i) begin
            bit_cnt <= 3'd0;
            shift_out <= 8'h00;
            shift_in <= 8'h00;
            data_out_o <= 8'h00;
            spi_mosi_o <= 1'b0;
        end else begin
            case(curr_state)
            IDLE: begin
                if(start_i) begin
                    shift_out <= data_in_i;
                    bit_cnt <= 3'd0;
                    spi_mosi_o <= data_in_i[7] //msb first
                end
            end
            SHIFT: begin
                //shift in miso bit
                shift_in <= {shift_in[6:0], spi_miso_i};

                //shift out next mosi bit
                shift_out <= {shift_out[6:0], 1'b0};
                spi_mosi_o <= shift_out[6];

                //inc cntr
                bit_cnt <= bit_cnt +1;

                //if done, save byte
                if(bit_cnt == 3'd7) begin
                    data_out_o <= {shift_in[6:0], spi_miso_i};
                end
            end
            endcase
        end 
    end

//fsm
    always_comb begin
        next_state = curr_state;
        spi_sck_o = 1'b0;
        done_o = 1'b0;
        busy_o = 1'b0;

        unique case(curr_state)
            IDLE: begin
                if(start_i) begin
                    next_state = SHIFT;
                end
            end
            SHIFT: begin
                busy_o = 1'b1;
                spi_sck_o = 1'b1; //made clock always high for now 

                if(bit_cnt == 3'd7) begin
                    done_o = 1'b1;
                    next_state = IDLE;
                end
            end

            default: next_state = IDLE;
        endcase
    end
endmodule


    //clock divider
    // always_ff @(posedge clk or negedge reset_n ) begin
    //     if(!reset_n) begin
    //         div <= 0;
    //         spi_sck <= 0;
    //     end else if(sck_en) begin
    //         div <= div +1;
    //         if(div == 3'd3) begin
    //             spi_sck <= ~spi_sck;
    //             div <= 0;
    //         end
    //     end
    // end