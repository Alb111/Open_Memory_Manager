module mmio (
    input logic clk_i,
    input logic rst_in,

    // interface from the addr decoder
    input logic [31:0] addr_i,
    input logic [31:0] wr_data_i,
    input logic wr_en_i, // write enable
    output logic [31:0] rdata_o,     // read data back to cpu

    // physical connections to the serializer/pins
    output logic [7:0] gpio_pins_o, // data going out
    input logic [7:0] gpio_pins_i, // data coming in
    output logic [7:0] gpio_dir_o   // 1 = output, 0 = input
);

    // registers
    logic [7:0] data_reg; // holds pin vals
    logic [7:0] csr_reg;  // holds direction (out/in)

    // addr constants
    localparam ADDR_DATA = 32'h8000_0010;
    localparam ADDR_CSR = 32'h8000_0018;

    // write
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            data_reg <= 8'h00;
            csr_reg <= 8'h00; // default all to inputs
        end else if(wen_i) begin
            if(addr_i == ADDR_DATA) begin
                data_reg <= wdata_i[7:0];
            end else if(addr_i == ADDR_CSR) begin
                csr_reg <= wdata_i[7:0];
            end
        end
    end

    //read
    always_comb begin
        if(addr_i == ADDR_DATA) begin
            rdata_o = {24'h0, data_reg};
        end else if(addr_i == ADDR_CSR) begin
            rdata_o = {24'h0, csr_reg};
        end else begin
            rdata_o = 32'h0;
        end
    end

    assign gpio_pins_o = data_reg;
    assign gpio_dir_o = csr_reg;

endmodule