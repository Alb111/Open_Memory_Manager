`timescale 1ns/1ps

module mmio (
    input logic clk_i,
    input logic rst_in,

    // interface from the addr decoder
    input logic [31:0] addr_i,
    input logic [31:0] wr_data_i,
    input logic wr_en_i, // write enable
    output logic [31:0] rd_data_o,     // read data back to cpu

    // physical gpio connections
    output logic [7:0] gpio_pins_o, // data going out
    input logic [7:0] gpio_pins_i, // data coming in
    output logic [7:0] gpio_dir_o,   // 1 = output, 0 = input

    //serializer interface
    output logic ser_tx_valid_o,
    input logic ser_tx_ready_i
);

    // registers
    logic [7:0] data_reg; //value
    logic [7:0] csr_reg;  //direction out/in

    logic tx_valid_reg;

    // write
    always_ff @(posedge clk_i or negedge rst_in) begin
        if(!rst_in) begin
            data_reg <= 8'h00;
            csr_reg <= 8'h00;
            tx_valid_reg <= 1'b0;
        end else begin
            //clear valid after serializer accpets
            if(ser_tx_ready_i && ser_tx_valid_o) begin
                tx_valid_reg <= 1'b0;
            end

            if(wr_en_i) begin
                //write to direction/csr
                if(addr_i == 32'h8000_0018) begin
                    csr_reg <= wr_data_i[7:0];
                //write to data/gpio
                end else if(addr_i == 32'h8000_0010) begin
                    //only update bits that are set as output in csr
                    data_reg <= (wr_data_i[7:0] & csr_reg) | (data_reg & ~csr_reg);
                    //serializer valid when writing to data
                    tx_valid_reg <= 1'b1;
                end
            end
        end
    end

    //read
    always_comb begin
        if(addr_i == 32'h8000_0018) begin
            rd_data_o = {24'h0, csr_reg};
        end else if(addr_i == 32'h8000_0010) begin
            //read data_reg for ouputs and gpio_pin_i for inputs
            rd_data_o = {24'h0, (data_reg & csr_reg) | (gpio_pins_i & ~csr_reg)};
        end else begin
            rd_data_o = 32'h0;
        end
    end

    assign gpio_pins_o = data_reg;
    assign gpio_dir_o = csr_reg;
    assign ser_tx_valid_o = tx_valid_reg;

endmodule
