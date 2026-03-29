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
    output logic [7:0] gpio_dir_o
);

    //internal signals to talk to mmio block
    logic [31:0] mmio_rd_data;
    logic is_special_addr;

    //addr decoding
    //check if addr starts with 0x8000
    always_comb begin
        if(addr_i[31:16] == 16'h8000) begin
            is_special_addr = 1'b1;
        end else begin
            is_special_addr = 1'b0;
        end
    end

    //routing
    // if special addr then block it from going to rest of chip
    assign passthru_addr_o = (is_special_addr) ? 32'h0 : addr_i;
    assign passthru_wr_en_o = (is_special_addr) ? 1'b0 : wr_en_i;
    assign passthru_wr_data_o = wr_data_i;

    //handling whoami and mmio reads
    always_comb begin
        if(is_special_addr) begin
            ack_o = 1'b1; //claim this address
            if(addr_i == 32'h8000_0000) begin
                rd_data_o = WHOAMI_ID; // return chips unique ID
            end else begin
                rd_data_o = mmio_rd_data; //return data from the mmio regs
            end
        end else begin
            ack_o = 1'b0;
            rd_data_o = passthru_rd_data_i; // passhtru data from memory
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
        .gpio_dir_o(gpio_dir_o)
    );

endmodule