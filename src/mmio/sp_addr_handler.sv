`timescale 1ns/1ps

module sp_addr_handler #(
    parameter int WHOAMI_ID = 32'hA1B2_C3D4 // ID
)(
    input logic clk_i,
    input logic rst_in,

    //interface from cpu /system bus
    input logic [31:0] addr_i,
    input logic [31:0] wr_data_i,
    input logic wr_en_i,      // write enable (1 = write, 0 =read)
    output logic [31:0] rd_data_o,     //data sent back to cpu
    output logic ack_o,       //addr acknowledged

    //interface to rest of chip (passthrough)
    output logic [31:0] passthru_addr_o,
    output logic [31:0] passthru_wr_data_o,
    output logic passthru_wr_en_o,
    input logic [31:0] passthru_rd_data_i,

    //pin connections
    output logic [7:0] gpio_pins_o,
    input logic [7:0] gpio_pins_i,
    output logic [7:0] gpio_dir_o,

    output logic ser_tx_valid_o,
    input logic ser_tx_ready_i
);

    //internal signals to talk to mmio block
    logic [31:0] mmio_rd_data; //data from gpio/csr regs
    logic is_special_addr;  // high is cpu taregting 0x8000_xxxx range

    //detect addr starting w/ 0x8000
    assign is_special_addr = (addr_i & 32'hFFFF_0000) == 32'h8000_0000;

    // if special addr/mmio then block it from going to rest of chip
    assign passthru_addr_o = (is_special_addr) ? 32'h0 : addr_i;
    assign passthru_wr_en_o = (is_special_addr) ? 1'b0 : wr_en_i;
    assign passthru_wr_data_o = wr_data_i;

    //which data cpu recieves
    always_comb begin
        if(is_special_addr) begin
            ack_o = 1'b1;   //acknowledge bus request for mmio range
            //0x8000_0000 returns whoami, any other 0x8000_xxxx addr returns data from mmio/gpio block
            rd_data_o = (addr_i == 32'h8000_0000) ? WHOAMI_ID : mmio_rd_data;
        end else begin
            ack_o = 1'b0;     //let exteneral system handle ack
            //pass thru data from external system bus
            rd_data_o = passthru_rd_data_i;
        end
    end

    mmio mmio_inst (
        .clk_i(clk_i),
        .rst_in(rst_in),
        .addr_i(addr_i),
        .wr_data_i(wr_data_i),
        .wr_en_i(wr_en_i && is_special_addr), //only write if its a special addr
        .rd_data_o(mmio_rd_data),
        .gpio_pins_o(gpio_pins_o),
        .gpio_pins_i(gpio_pins_i),
        .gpio_dir_o(gpio_dir_o),
        .ser_tx_valid_o(ser_tx_valid_o),
        .ser_tx_ready_i(ser_tx_ready_i)
    );

endmodule
