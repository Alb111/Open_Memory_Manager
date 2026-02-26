# Bootloader Subsystem

## Overview
The Bootloader subsystem is responsible for initializing the system SRAM with executable code stored in an external SPI Flash. This process starts automatically once the system is powered on and the initial hardware reset is de-asserted.

## Hardware Architecture
* **Flash Interface:** Uses the SPI protocol (Mode 0) to communicate with external flash memory via the SPI Engine.
* **Word Assembly:** The controller retrieves 8-bit data packets and assembles them into 32-bit words using a **Little-Endian** format.
* **System Control:** * `cores_en_o`: Held low during the boot process to keep the CPU cores in a reset state.
    * `boot_done_o`: Signals the completion of the transfer and acts as the selector for the Memory Controller mux.

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
* **`test_boot_full`**: Verifies a complete 32-byte transfer, ensuring every address and data word is correct.
* **`test_reset_during_boot`**: Verifies that a hardware reset mid-process correctly clears all internal counters and stops SRAM writes.
* **`test_short_boot_failure`**: A security/safety check to ensure CPU cores are never enabled if the SPI stream ends prematurely.

### How to Run Tests
From the `cocotb` directory, run:
```bash
python3 housekeeping_tb.py

