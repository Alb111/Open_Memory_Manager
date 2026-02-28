# `wrr_arbiter` — Weighted Round-Robin Arbiter

## Overview

This module implements a **Weighted Round-Robin (WRR) arbiter** in SystemVerilog/Verilog.

---

## Why an Arbiter?

Our design implements two picoRV32, a resource-efficient RISC-V soft-core processor. Both of them share a single memory controller, but cannot both access it concurrently. Without arbitration, the two cores would collide and corrupt transactions. The arbiter sits between the cores and the memory controller, receives their requests, and issues a **one-hot grant signal** to exactly one core per cycle.

---

## Parameters

| Parameter  | Default | Description |
|------------|---------|-------------|
| `NUM_REQ`  | `2`     | Number of requesters (one per picoRV32 core). Must be a power of 2. |
| `WEIGHT_W` | `3`     | Bit-width of each weight value. Supports default weights from 1 to 7. |
| `WEIGHTS`  | `{3'd1, 3'd1}` | Packed array of per-requester weights. Defaults to equal priority or Round Robin mode. |

`WEIGHTS` control how many consecutive cycles a core can hold the bus before the arbiter rotates to the next one. For example, `WEIGHTS = {3'd3, 3'd1}` means Core 1 gets three grants for every one grant to Core 0. Core 0 will still always be the first in rotation no matter of weights. For example it will always rotate Core 0 -> Core 1 -> Core N

---

## Ports

| Port      | Direction | Width       | Description |
|-----------|-----------|-------------|-------------|
| `clk_i`   | Input     | 1-bit       | System clock |
| `rst_i`   | Input     | 1-bit       | Active-high synchronous reset |
| `req_i`   | Input     | `NUM_REQ`   | Request lines — one bit per core, asserted when that core needs the bus |
| `grant_o` | Output    | `NUM_REQ`   | One-hot grant — the asserted bit indicates which core owns the bus this cycle |
| `req_o`   | Output    | `NUM_REQ`   | Pass-through of `req_i`, for use by downstream logic |

---


## State Registers

- **`curr_ptr`** — points to the currently-served requester (0 or 1 for two cores).
- **`credit_cnt`** — tracks how many grants the current requester still has remaining before the pointer rotates.
- **`grant_o`** — registered one-hot output indicating which core received the grant last cycle.

---

## Design Flow

### Reset

On `rst_i`, the arbiter resets to:
- `curr_ptr = 0` (start at Core 0)
- `credit_cnt = weight_table[0]` (load Core 0's full weight)
- `grant_o = 0` (no grant issued yet)

Note: `credit_cnt` is initialized to the weight of the first requester rather than zero so that Core 0 is not skipped on the very first cycle.

### Combinational Logic

The `always_comb` block computes the next state.

**Case 1 — Current requester is active (`req_i[curr_ptr] == 1`):**
- Issue a grant to that requester: `next_grant[curr_ptr] = 1`.
- If `credit_cnt > 1`: decrement the credit counter and stay on the same requester.
- If `credit_cnt == 1`: this is the last grant for this requester. Advance `curr_ptr` to the next requester (with bitwise wrap using `PTR_MASK`), and load `credit_cnt` with that next requester's weight.

**Case 2 — Current requester is idle (`req_i[curr_ptr] == 0`):**
- Don't issue a grant.
- Immediately rotate `curr_ptr` to the next requester and load its weight into `credit_cnt`.

### Each Cycle (Sequential Logic)

The `always_ff` block simply registers the combinational next-state values: `curr_ptr`, `credit_cnt`, and `grant_o` all update on the rising edge of `clk_i`.

---

## Example

The table below assumes Core 0 has weight 1 and Core 1 has weight 3, and both are always requesting.

| Cycle | `curr_ptr` | `credit_cnt` | `grant_o` |
|-------|-----------|-------------|-----------|
| 1     | 0         | 1           | `0001` (Core 0) |
| 2     | 1         | 3           | `0010` (Core 1) |
| 3     | 1         | 2           | `0010` (Core 1) |
| 4     | 1         | 1           | `0010` (Core 1) |
| 5     | 0         | 1           | `0001` (Core 0) |
| 6     | 1         | 3           | `0010` (Core 1) |

---

## Key Design Decisions

- **Bitwise wrap with `PTR_MASK`:** Instead of a comparison-based wrap (`if ptr == NUM_REQ-1 then ptr = 0`), the design uses `(curr_ptr + 1) & PTR_MASK`. Since `NUM_REQ` is constrained to powers of 2, this is equivalent and synthesizes to zero extra logic.
- **Idle skip:** When a core is not requesting, the arbiter does not stall, it immediately rotates to the next candidate. This prevents the bus from going idle unnecessarily.
- **`req_o` pass-through:** `req_i` is passed directly to `req_o` as a convenience for any downstream module (e.g., a scheduler or status register) that needs visibility into which cores are requesting without tapping into the arbiter's internals.

---

## Limitations & Assumptions

- `NUM_REQ` must be a power of 2 (required for the `PTR_MASK` wrap to work correctly).
- With the default equal weights `{1, 1}`, this makes a standard round-robin arbiter.
