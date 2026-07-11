# Debug scan-chain architecture

The chip contains four parallel scan chains selected by the existing
`debug_mode` input. The chains cover every synthesizable `always_ff` register
in the active `chip_core` hierarchy. The GF180 SRAM bit arrays are hard macros
and are not part of the chains; the RTL control registers surrounding those
macros are included.

## External interface

`DFT_START_ID` is 32 and `DFT_PINS` is 8. The lower half of the DFT pad range
is used for scan input and the upper half for scan output.

| Chain | Scan input pad | Scan output pad | Length |
|---:|---:|---:|---:|
| 0 | `bidir[32]` | `bidir[36]` | 152 bits |
| 1 | `bidir[33]` | `bidir[37]` | 223 bits |
| 2 | `bidir[34]` | `bidir[38]` | 223 bits |
| 3 | `bidir[35]` | `bidir[39]` | 289 bits |

The output pads are enabled only while `debug_mode` is high. This leaves all
previously unused DFT pads in their original high-impedance state during
normal operation.

To scan:

1. Assert the global reset to initialize the chains if a known starting state
   is required.
2. Deassert reset.
3. Assert `debug_mode`.
4. Present one bit on each scan input and pulse the normal chip clock. Each
   rising edge shifts all four chains by one bit.
5. Read the corresponding scan output before or after each edge as required by
   the tester timing convention.
6. Deassert `debug_mode` to resume functional register updates using the values
   inserted through scan.

Reset has priority over scan. With `debug_mode == 0`, every sequential block
executes its original functional branch. Scan shifts toward each vector's most
significant bit: a serial bit enters bit 0, then advances through increasing
bit indices. The tables below list elements from scan input to scan output.

## Chain 0: housekeeping and boot

| Order | Instance | Register bits | Width |
|---:|---|---|---:|
| 1 | `i_housekeeping_top.spi_master` | `curr_state[0:1]` | 2 |
| 2 | | `bit_cnt[0:2]` | 3 |
| 3 | | `shift_out[0:7]` | 8 |
| 4 | | `shift_in[0:7]` | 8 |
| 5 | | `data_out_o[0:7]` | 8 |
| 6 | | `spi_mosi_o` | 1 |
| 7 | | `sck_div[0:3]` | 4 |
| 8 | `i_housekeeping_top.boot_controller` | `curr_state[0:3]` | 4 |
| 9 | | `word_buffer[0:31]` | 32 |
| 10 | | `byte_in_word[0:1]` | 2 |
| 11 | | `byte_cntr[0:31]` | 32 |
| 12 | | `sram_addr[0:31]` | 32 |
| 13 | | `addr_byte_cnt[0:1]` | 2 |
| 14 | `i_housekeeping_top` | `clear_counter[0:12]` | 13 |
| 15 | | `whoami_sent` | 1 |

## Chain 1: core-0 directory interface

| Order | Instance | Register bits | Width |
|---:|---|---|---:|
| 1 | `i_directory_interface_0.u_tserializer` | `current_state` | 1 |
| 2 | | `curr_msg_len[0:2]` | 3 |
| 3 | | `count[0:2]` | 3 |
| 4 | | `shift_arr[0][0]` through `shift_arr[3][8]` | 36 |
| 5 | `i_directory_interface_0.u_rserializer` | `current_state` | 1 |
| 6 | | `shift_arr[0][0]` through `shift_arr[7][8]` | 72 |
| 7 | | `valid_o` | 1 |
| 8 | `i_directory_interface_0.bus_ack_pipe` | `valid_o_r` | 1 |
| 9 | | `data_r[0:68]` | 69 |
| 10 | `i_directory_interface_0.snoop_pipe` | `valid_o_r` | 1 |
| 11 | | `data_r[0:34]` | 35 |

## Chain 2: core-1 directory interface

Chain 2 has the same 223-bit register order as chain 1, with every
`i_directory_interface_0` instance prefix replaced by
`i_directory_interface_1`.

## Chain 3: directory controller and memory control

| Order | Instance | Register bits | Width |
|---:|---|---|---:|
| 1 | `i_directory_controller.u_wrr_arbiter` | `curr_ptr` | 1 |
| 2 | | `credit_cnt[0:2]` | 3 |
| 3 | `i_directory_controller` | `state_q[0:4]` | 5 |
| 4 | | `init_index_q[0:6]` | 7 |
| 5 | | `dir_state_invalidated_q` | 1 |
| 6 | | `request_cache_q` | 1 |
| 7 | | `request_addr_q[0:31]` | 32 |
| 8 | | `request_data_q[0:31]` | 32 |
| 9 | | `request_cmd_q[0:4]` | 5 |
| 10 | | `line_state_q[0:1]` | 2 |
| 11 | | `line_sharers_q[0:1]` | 2 |
| 12 | | `line_owner_q` | 1 |
| 13 | | `line_valid_q` | 1 |
| 14 | | `pending_ack_cache_q` | 1 |
| 15 | | `pending_ack_cmd_q[0:5]` | 6 |
| 16 | | `pending_ack_data_q[0:31]` | 32 |
| 17 | | `pending_snoop_cache_q` | 1 |
| 18 | | `pending_snoop_cmd_q[0:5]` | 6 |
| 19 | | `pending_write_q` | 1 |
| 20 | | `pending_write_state_q[0:1]` | 2 |
| 21 | | `pending_write_sharers_q[0:1]` | 2 |
| 22 | | `pending_write_owner_q` | 1 |
| 23 | | `pending_write_valid_q` | 1 |
| 24 | | `pending_backup_write_q` | 1 |
| 25 | | `pending_backup_data_q[0:31]` | 32 |
| 26 | | `backup_read_then_snoop_q` | 1 |
| 27 | | `flush_seen_q` | 1 |
| 28 | | `flush_data_q[0:31]` | 32 |
| 29 | `i_directory_mem` | `state_q[0:1]` | 2 |
| 30 | | `addr_q[0:31]` | 32 |
| 31 | | `w_data_q[0:31]` | 32 |
| 32 | | `wstrb_q[0:3]` | 4 |
| 33 | | `w_state_q[0:1]` | 2 |
| 34 | | `w_sharers_q[0:1]` | 2 |
| 35 | | `w_owner_q` | 1 |
| 36 | | `w_valid_data_q` | 1 |

## Functional-mode guarantee

Scan selection is implemented as an `else if (scan_en_i)` branch after reset
and before the pre-existing functional branch in each sequential block. Since
`scan_en_i` is driven by `debug_mode`, the pre-existing functional assignments
are selected unchanged whenever debug mode is low.
