module spi_engine (
    input logic clk,
    input logic reset_n,

    input logic start_i,
    input logic [7:0] tx_byte_i,
    input logic [7:0] rx_byte_i,
    output logic byte_done_o,

    //spi pins
    output logic spi_sck,
    output logic spi_mosi,
    input logic spi_miso,
    output logic spi_csb
);
    typedef enum logic [1:0] {IDLE, SHIFT, DONE} spi_state_t;

    spi_state_t curr_state, next_state;

    logic [7:0] tx_shift, rx_shift;
    logic [2:0] bit_cnt;


    //clock speed
    logic [2:0] div;
    logic sck_en;

    //shift logic
    logic [7:0] shifter_tx;
    logic [7:0] shifter_rx;
    logic [2:0] bit_cnt;

    //state reg
    always_ff @(posedge clk) begin
        if(!reset_n) begin
            curr_state <= IDLE;
        end else begin
            curr_state <= next_state;
        end
    end

    always_comb begin
        next_state = curr_state;
        spi_csb = 1'b1;
        spi_sck = 1'b0;
        spi_mosi = 1'b0;
        byte_done_o = 1'b0;

        case(curr_state)
            IDLE: begin
                if(start_i) begin
                    next_state = SHIFT;
                end
            end
            SHIFT: begin
                spi_csb = 1'b0;
                spi_sck = clk;
                spi_mosi = tx_shift[bit_cnt];

                if(bit_cnt == 0) begin
                    next_state = DONE;
                end
            end

            DONE: begin
                byte_done_o = 1'b1;
                next_state = IDLE;
            end

            defailt: next_state = IDLE;
        endcase
    end

    //data path
    always_ff @(posedge clk) begin
        if(!reset_n) begin
            bit_cnt <= 3'd7;
            tx_shift <= 0;
            rx_shift <= 0;
        end else begin
            if(curr_state == IDLE && start_i) begin
                tx_shift <= tx_byte_i;
                rx_shift <= 0;
                bit_cnt <= 3'd7;
            end else if(curr_state == SHIFT) begin
                rx_shift[bit_cnt] <= spi_miso;
                bit_cnt <= bit_cnt - 1;
            end else if(curr_state == DONE) begin
                rx_byte_i <= rx_shift;
            end
        end
        
    end



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
endmodule