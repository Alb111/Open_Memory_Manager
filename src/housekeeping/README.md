# Bootloader Subsystem

## Overview
The Bootloader subsystem is responsible for initializing the system SRAM with executable code stored in an external SPI Flash. This process starts automatically once the system is powered on and the initial hardware reset is de-asserted.

## Technical Specifications
* **Flash Interface:** Uses the SPI protocol (Mode 0) to communicate with external flash memory via the SPI Engine.
* **Word Assembly:** The controller retrieves 8-bit data packets and assembles them into 32-bit words using a **Little-Endian** format.
* **System Control:** `cores_en_o`: Held low during the boot process to keep the CPU cores in a reset state.
    * `boot_done_o`: Signals the completion of the transfer and acts as the selector for the Memory Controller mux.
* **Path:** Muxed directly into the Memory Controller to ensure MSI Directory state remains clean during initialization.

## Flash Reprogramming (Pass-Through Mode)
The subsystem supports external flash reprogramming using an external SPI master (e.g. USB-to-SPI bridge). In this design, the flash pins are shared between the bootloader and the external programmer.

**Operation:**

When `pass_thru_en_i = 1`:
* Boot controller system is held in reset.
* Internal SPI outputs (`spi_sck_o`, `spi_mosi_o`, `flash_csb_o`) are tri-stated.
* An external SPI master can directly drive the flash pins (`SCK`, `MOSI`, `CSB`) and read from `MISO`.

This allows the external SPI master to safely program the flash without conflicts with the internal bootloader logic.

When `pass_thru_en_i = 0`:
* Tri-state is removed and boot controller system becomes active.
* Boot controller reads flash and copies contents into SRAM.


## Module Descriptions

### 1. `spi_engine.sv`
The low-level SPI master. It handles:
* **Serialization:** Converting parallel 8-bit bytes into a serial bitstream for the `MOSI` pin.
* **Deserialization:** Reconstructing a bitstream from the `MISO` pin back into 8-bit bytes.
* **Clocking:** Manages the `SCK` signal generation.

### 2. `boot_fsm.sv`
The main control logic. It implements a FSM that:
1.  **Initializes:** Sends the standard SPI Read Command (`0x03`) and the starting address.
2.  **Fetches:** Requests bytes from the SPI Engine sequentially.
3.  **Writes:** Once a full 32-bit word is assembled, it pulses the `sram_wr_en_o` signal to the Memory Controller.
4.  **Hands Over:** Once the defined `BOOT_SIZE` is reached, it releases the cores and stays in a `DONE` state.

### 3. `housekeeping_top.sv`
The top-level wrapper that integrates the SPI Engine and the Boot FSM, providing a unified interface for the rest of the SoC.

---

## Verification (Cocotb)
The subsystem is verified using a Cocotb testbench (`housekeeping_tb.py`) and an asynchronous Flash model.

### Test Suite
* **test_reset_behavior:** Verifies that all outputs are held low while reset_i is asserted.
* **test_full_boot_sequence:** Verifies a complete 32-byte boot, checking every SRAM address, data word, and the final `boot_done_o` / `cores_en_o handoff`.
* **test_mux_boot_mode:** Verifies that the boot controller can talk to flash and complete a boot when `pass_thru_en_i = 0`.
* **test_mux_passthrough_mode:** Verifies that the boot controller goes completely silent when `pass_thru_en_i = 1`.
* **test_mid_boot_interrupt:** Verifies that asserting `pass_thru_en_i` mid-boot immediately stops all SRAM writes and prevents `boot_done_o` from firing.
* **test_boot_after_passthrough:** Verifies that a clean boot completes correctly after reprogramming is complete and reset is applied.
  
### How to Run Tests
From the `cocotb` directory, run:
```bash
python3 housekeeping_tb.py
```


