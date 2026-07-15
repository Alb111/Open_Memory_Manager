`timescale 1ns/1ps

// Boot loader FSM.
//
// The flash image is self-describing: the FIRST 32-bit word (flash bytes 0..3,
// little-endian) is a HEADER holding the image length in 32-bit words (i.e. the
// number of instructions). The boot loader reads that header, latches it into
// the boot_len status register, then streams exactly that many words into main
// memory starting at SRAM_BASE_ADDR. The header word itself is not written to
// memory; the instruction image begins at flash byte 4.
//
// boot_len is exposed as a status output. It marks the boundary between the
// instruction space [0, boot_len) and the (zero-initialised) data space
// [boot_len, MEM_WORDS): intended for later making the instruction space
// private and keeping the data space normalised to zero.
//
// The header value is clamped to MEM_WORDS so a corrupt/oversized length can
// never run the write past the end of memory.
module boot_fsm #(
    parameter BOOT_SIZE = 512,          // legacy/unused: length now comes from
                                        // the flash header (kept for interface
                                        // compatibility).
    parameter MEM_WORDS = 32'd8192,     // main-memory depth; boot_len clamp.
    parameter SRAM_BASE_ADDR = 32'h0000_0000
)(
    input logic clk_i,
    input logic reset_ni,
    output logic spi_start_o,
    output logic [7:0] spi_out_o,
    input logic [7:0] spi_in_i,
    input logic spi_done_i,
    input logic spi_busy_i,
    output logic flash_csb_o,
    output logic cores_en_o,
    output logic boot_done_o,

    output logic sram_wr_en_o,
    output logic [31:0] sram_addr_o,
    output logic [31:0] sram_data_o,

    // Boot-image length in words, latched from the flash header. Valid from the
    // CAPTURE_LEN step onward and held stable after boot completes.
    output logic [31:0] boot_len_o,

    output logic boot_started_o,

    input logic scan_en_i,
    input logic scan_in_i,
    output logic scan_out_o
);

    typedef enum logic [3:0] {
        IDLE,
        SEND_CMD,
        WAIT_CMD,
        SEND_ADDR,
        WAIT_ADDR,
        READ_BYTE,
        WAIT_BYTE,
        CAPTURE_LEN,
        WRITE_SRAM,
        DONE
    } boot_state_t;

    boot_state_t curr_state, next_state;
    logic [31:0] word_buffer;  //collects 4 bytes
    logic [1:0]  byte_in_word;  // which byte in word (0-3)
    logic [31:0] byte_cntr;   // image bytes read (reset after the header)
    logic [31:0] sram_addr;  // curr sram addr
    logic [1:0]  addr_byte_cnt;   // count 3 address bytes
    logic [31:0] boot_len;   // image length in words (from header), clamped
    logic        hdr_done;   // 0 while reading the header word, 1 afterwards

    // Clamp the header value so a bad length cannot overrun main memory.
    logic [31:0] len_clamped;
    assign len_clamped = (word_buffer > MEM_WORDS) ? MEM_WORDS : word_buffer;

    assign boot_len_o = boot_len;

    //state register
    always_ff @(posedge clk_i) begin
        if (!reset_ni) begin
            curr_state <= IDLE;
        end else if (scan_en_i) begin
            curr_state <= boot_state_t'((curr_state << 1) | scan_in_i);
        end else begin
            curr_state <= next_state;
        end
    end

    // data path
    always_ff @(posedge clk_i) begin
        if(!reset_ni) begin
            word_buffer <= 32'h0;
            byte_in_word <= 2'd0;
            byte_cntr <= 32'h0;
            sram_addr <= SRAM_BASE_ADDR;
            addr_byte_cnt <= 2'd0;
            boot_len <= 32'h0;
            hdr_done <= 1'b0;
        end else if (scan_en_i) begin
            // Scan chain (LSB->MSB): curr_state -> word_buffer -> byte_in_word
            // -> byte_cntr -> sram_addr -> addr_byte_cnt -> boot_len -> hdr_done.
            word_buffer <= (word_buffer << 1) | curr_state[$bits(curr_state)-1];
            byte_in_word <= (byte_in_word << 1) | word_buffer[31];
            byte_cntr <= (byte_cntr << 1) | byte_in_word[1];
            sram_addr <= (sram_addr << 1) | byte_cntr[31];
            addr_byte_cnt <= (addr_byte_cnt << 1) | sram_addr[31];
            boot_len <= (boot_len << 1) | addr_byte_cnt[1];
            hdr_done <= boot_len[31];
        end else begin
            // idle to reset counters before a new boot starts
            if (curr_state == IDLE) begin
                byte_in_word <= 2'd0;
                addr_byte_cnt <= 2'd0;
                byte_cntr <= 32'h0;
                hdr_done <= 1'b0;
                boot_len <= 32'h0;
            end

            if (curr_state == WAIT_ADDR && spi_done_i) begin
                addr_byte_cnt <= addr_byte_cnt + 1'b1;
            end

            // byte assembly (both the header word and the image words)
            if (curr_state == WAIT_BYTE && spi_done_i) begin
                case(byte_in_word)
                    2'd0: word_buffer[7:0] <= spi_in_i;
                    2'd1: word_buffer[15:8] <= spi_in_i;
                    2'd2: word_buffer[23:16] <= spi_in_i;
                    2'd3: word_buffer[31:24] <= spi_in_i;
                endcase
                byte_in_word <= byte_in_word + 1'b1;
                byte_cntr <= byte_cntr + 1'b1;
            end

            // Latch the header length, then restart byte/word counting for the
            // image. The header word is not written to memory.
            if (curr_state == CAPTURE_LEN) begin
                boot_len <= len_clamped;
                hdr_done <= 1'b1;
                byte_in_word <= 2'd0;
                byte_cntr <= 32'h0;
            end

            if (curr_state == WRITE_SRAM) begin
                byte_in_word <= 2'd0;
                // Shared memory is word-indexed: write image word i at word
                // index i (stride 1), matching the CPU side after sp_addr_handler
                // translates its byte address to a word index.
                sram_addr <= sram_addr + 1;
            end

        end
    end

    //fsm
    always_comb begin
        next_state = curr_state;
        spi_start_o = 1'b0;
        spi_out_o = 8'h00;
        flash_csb_o = 1'b1;
        sram_wr_en_o = 1'b0;
        sram_addr_o = sram_addr;
        sram_data_o = word_buffer;
        cores_en_o = 1'b0;
        boot_done_o = 1'b0;
        boot_started_o = (curr_state != IDLE);

        case(curr_state)
            IDLE: begin
                next_state = SEND_CMD;
            end

            SEND_CMD: begin
                flash_csb_o = 1'b0;
                spi_start_o = 1'b1;
                spi_out_o = 8'h03;  // read command
                next_state = WAIT_CMD;
            end


            WAIT_CMD: begin
                flash_csb_o = 1'b0;
                if (spi_done_i) begin
                    next_state = SEND_ADDR;
                end
            end

            SEND_ADDR: begin
                flash_csb_o = 1'b0;
                spi_start_o = 1'b1;
                spi_out_o = 8'h00;  // addr bytes are all 0x00
                next_state = WAIT_ADDR;
            end

            WAIT_ADDR: begin
                flash_csb_o = 1'b0;
                if (spi_done_i) begin
                    if (addr_byte_cnt == 2'd2)
                        // sent all 3 addr bytes -> read the header word first
                        next_state = READ_BYTE;
                    else
                        // send next addr byte
                        next_state = SEND_ADDR;
                end
            end

            READ_BYTE: begin
                flash_csb_o = 1'b0;
                spi_start_o = 1'b1;
                spi_out_o = 8'h00;
                next_state = WAIT_BYTE;
            end

            WAIT_BYTE: begin
                flash_csb_o = 1'b0;
                if (spi_done_i) begin
                    // if this was the 4th byte (index 3), the word is complete
                    if (byte_in_word == 2'd3) begin
                        // header word first, then the image words
                        next_state = hdr_done ? WRITE_SRAM : CAPTURE_LEN;
                    end else begin
                        next_state = READ_BYTE;
                    end
                end else begin
                    // need more bytes
                    next_state = WAIT_BYTE;
                end
            end

            CAPTURE_LEN: begin
                flash_csb_o = 1'b0;
                // Empty image (length 0) finishes immediately; otherwise start
                // streaming the instruction words.
                next_state = (len_clamped == 32'd0) ? DONE : READ_BYTE;
            end

            WRITE_SRAM: begin
                flash_csb_o = 1'b0;
                sram_wr_en_o = 1'b1;
                sram_addr_o = sram_addr;
                sram_data_o = word_buffer;

                // Stop once boot_len words (boot_len*4 bytes) have been written.
                if (byte_cntr >= (boot_len << 2)) begin
                    next_state = DONE;
                end else begin
                    next_state = READ_BYTE;
                end
            end

            DONE: begin
                flash_csb_o = 1'b1;  // deselect flash
                cores_en_o = 1'b1;
                boot_done_o = 1'b1;
                next_state = DONE;   // stay here
            end

            default: next_state = IDLE;
        endcase
    end

    assign scan_out_o = hdr_done;
endmodule
