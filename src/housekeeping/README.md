# Bootloader Subsystem
 
## Overview
 
The Bootloader subsystem is responsible for initializing the system SRAM with executable code stored in an external SPI Flash. This process starts automatically once the system is powered on and the initial hardware reset is de-asserted. The bootloader holds all CPU cores frozen during initialization and releases them only once the full program image has been copied into SRAM.
 
---
 
## Technical Specifications
 
- **Flash Interface:** Uses the SPI protocol (Mode 0) to communicate with external flash memory via the SPI Engine.
- **Word Assembly:** The controller retrieves 8-bit data packets and assembles them into 32-bit words using **Little-Endian** format.
- **Clear handshake:** On reset release, the boot FSM/SPI engine are held in reset until the external memory reset generator reports the directory metadata and main memory are fully cleared. Housekeeping asserts `mem_clear_start_o` out of reset and releases the boot machinery (`clear_done`) only once `mem_clear_done_i` is high, so booting never begins over dirty memory. There is no fixed-cycle settle counter.
- **WhoAmI Pulse:** At the start of boot, a handshaked pulse is sent to both `directory_interface` instances via `whoami_pulse_o`, triggering transmission of each core's CPU ID over the interposer serial link before program execution begins.
- **System Control:**
  - `cores_en_o`: Held low during the boot process to keep the CPU cores frozen. Goes high when boot completes.
  - `boot_done_o`: Signals completion of the flash-to-SRAM transfer. Acts as the memory bus mux selector, handing control from the boot controller to the directory controller.
- **Path:** Boot controller output is muxed directly into the Memory Controller, bypassing the cache and directory controller entirely during boot to ensure MSI directory state remains clean.

---

## Boot Sequence
 
After `rst_n` is de-asserted:
 
1. **Clear handshake:** Boot FSM/SPI remain in reset while the external reset generator clears the directory metadata and main memory. Housekeeping holds `mem_clear_start_o` high and waits for `mem_clear_done_i`; only then does `clear_done` release the boot machinery.
2. **Command phase:** Boot controller pulls `flash_csb_o` low and sends the SPI Read Command (`0x03`) followed by three address bytes (`0x000000`).
3. **Data retrieval:** SPI engine fetches bytes from flash one at a time. Boot FSM assembles every four bytes into a 32-bit little-endian word.
4. **WhoAmI:** On the first clock cycle after the FSM leaves IDLE, `whoami_pulse_o` is asserted and held until both directory interface tserializers confirm acceptance via `whoami_ready_i`. This triggers each `directory_interface` to transmit a WhoAmI packet containing its `cpu_id` over the interposer serial link.
5. **Memory write:** Once a complete 32-bit word is assembled, `mem_valid_o` pulses for one clock cycle to write the word to SRAM via the memory controller.
6. **Completion:** When `BOOT_SIZE` bytes have been transferred, `flash_csb_o` returns high, `boot_done_o` and `cores_en_o` go high and stay high, releasing the CPU cores to begin execution from address `0x0000_0000`.

---
 
## Flash Reprogramming (Pass-Through Mode)
 
The subsystem supports external flash reprogramming using an external SPI
master (e.g. USB-to-SPI bridge). The flash pins are shared between the
bootloader and the external programmer, controlled by `pass_thru_en_i`, which
is driven by `boot_pass_en` on `bidir_PAD[1]`.
 
**When `pass_thru_en_i = 1` (programmer connected):**
- Boot controller and SPI engine are held in reset.
- Internal SPI outputs (`spi_sck_o`, `spi_mosi_o`, `flash_csb_o`) are tri-stated on the pad ring.
- External SPI master can drive the flash pins directly without bus contention.

**When `pass_thru_en_i = 0` (normal boot):**
- Tri-state is removed and the boot controller becomes active.
- Boot controller reads flash and copies the program image into SRAM.

The external master must be idle while changing ownership. Assert
`boot_pass_en`, wait at least 25 ns, and then begin driving flash `CSB`, `MOSI`,
and `SCLK`. Before returning ownership, stop driving those signals, deassert
`boot_pass_en`, and wait at least 25 ns. Physical STA constrains either
ownership transition to reach all three output pads within 20 ns.

---
 
## Module Descriptions
 
### `spi_engine.sv`
Low-level SPI master handling:
- **Serialization:** Converting parallel 8-bit bytes into a serial bitstream for `MOSI`.
- **Deserialization:** Reconstructing a serial bitstream from `MISO` into 8-bit bytes.
- **Clocking:** Generating the `SCK` signal. Clock is the system clock divided by 16 (8 cycles low, 8 cycles high).

### `boot_fsm.sv`
Main control FSM with the following states: `IDLE → SEND_CMD → WAIT_CMD → SEND_ADDR → WAIT_ADDR → READ_BYTE → WAIT_BYTE → WRITE_SRAM → DONE`.
 
Key outputs:
- `sram_wr_en_o`: Pulses high for exactly one clock cycle per 32-bit word write.
- `boot_started_o`: Goes high on the first cycle the FSM leaves IDLE, used by `housekeeping_top` to generate `whoami_pulse_o`.
- `cores_en_o` / `boot_done_o`: Both asserted in the `DONE` state and held high indefinitely.

### `housekeeping_top.sv`
Top-level wrapper integrating the SPI Engine and Boot FSM. Also handles:
- **Clear handshake:** Holds `boot_fsm` and `spi_engine` in reset after `rst_n` goes high until the external reset generator asserts `mem_clear_done_i`, driving `mem_clear_start_o` to request the clear.
- **Memory controller adapter:** Translates raw `sram_wr_en_o` / `sram_addr_o` / `sram_data_o` from the FSM into the `mem_valid_o` / `mem_addr_o` / `mem_wdata_o` / `mem_wstrb_o` interface expected by `mem_ctrl_512x32`.
- **WhoAmI handshake:** Generates `whoami_pulse_o` using a rising-edge detect on `boot_started_o`, holds it high until `whoami_ready_i` confirms both directory interface tserializers have accepted the transmission, then latches `whoami_sent` to prevent re-transmission.

---

## Verification

The subsystem is verified across three Cocotb testbenches.

`housekeeping_tb.py` is the behavioral baseline. It tests the boot FSM and SPI engine logic using a hand-written Python flash model, covering reset behavior, full boot sequencing, pass-through mode, mid-boot interrupts, and recovery after reprogramming.

`boot_flash_test.py` is the hardware-accuracy testbench. It replaces the Python flash model with the manufacturer's official Verilog model of the exact Cypress S25FL128L flash IC used on the PCB. Tests cover the full boot against real SPI protocol behavior, page boundary crossing, signal integrity checks (CSB continuity, write enable pulse width, reset recovery), and the WhoAmI pulse and clear window timing.

`boot_mem_test.py` is the end-to-end integration testbench. It extends the chain through the physical GF180MCU SRAM macros, verifying that data written by the boot controller during flash-to-SRAM transfer can be read back correctly from silicon-accurate memory cells. This is the highest-confidence test that the complete path from flash through the bootloader through the memory controller into SRAM is functionally correct.

`whoami_boot_tb.py` tests the WhoAmI handshake integration with the directory interfaces. It verifies that the `whoami_pulse_o` signal correctly triggers both `directory_interface` instances to serialize and transmit WhoAmI packets with the correct `cpu_id` values over the interposer serial link, and that the handshake deasserts the pulse correctly before boot completes.

---

### How to Run
 
From the `cocotb/` directory:
 
```bash
python3 housekeeping_tb.py
python3 boot_flash_test.py
python3 boot_mem_test.py
python3 whoami_boot_tb.py
```
 
Or using the Makefile targets from the repo root:
 
```bash
make test-boot
make test-boot-flash
make test-boot-mem
```
 
> **Note:** The Cypress S25FL128L Verilog model files (`s25fl128l.v`, `s25fl128l.mem`, `s25fl128lSECR.mem`) are proprietary and not committed to the repository. Place them in `src/housekeeping/cypress_model/` before running `boot_flash_test.py`, `boot_mem_test.py`, or `whoami_boot_tb.py`. The `boot_image.mem` file is generated automatically by the test runner and does not need to be committed.

