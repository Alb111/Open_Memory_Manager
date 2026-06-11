# Directory Controller RTL

This directory contains the directory-controller RTL for a two-core MSI
directory. The controller accepts decoded coherence requests from two
`directory_interface` instances, arbitrates between them, applies MSI metadata
updates, performs snoops when needed, and sends decoded responses back to the
interfaces.

The controller does **not** serialize or deserialize interposer packets — that
work belongs to `directory_interface`. This RTL starts after packet decode and
ends before packet encode.

## RTL Files

- `directory_controller.sv`
  Top-level directory controller. Implements the request arbitration, the MSI
  decision logic, and the memory-side state machine.
- `wrr_arbiter.sv`
  Weighted round-robin arbiter used to select between the two cache request
  ports. Defaults to equal weights (`{1, 1}`), giving a standard round-robin.

## Scope and Design Choices

The controller intentionally tracks **128 coherent line IDs** and does not store
address tags. The directory index is taken from `request_addr_q[6:0]`, so only
the low 7 bits of the address are used.

This module intentionally does not serialize/deserialize packets, track more
than 128 lines, store tags, treat addresses above 127 as coherent lines, clear
normal backing memory on reset, or process more than one request at a time.

## Address Map

| Address range | Owner | Purpose |
| --- | --- | --- |
| `0` to `127` | Directory controller | Coherent tracked line IDs |
| `128` to `1791` | System memory path | Normal main memory outside this controller |
| `1792` to `1919` | Directory controller | Backup data words for cache 0, one per line |
| `1920` to `2047` | Directory controller | Backup data words for cache 1, one per line |

Backup addresses are computed as `1792 + request_index` (cache 0) and
`1920 + request_index` (cache 1). Metadata is accessed through the
`directory_mem` abstraction at the line index directly (`0` to `127`), which
routes metadata to the 128x6 metadata SRAM.

## Metadata Word Layout

Each tracked line has one metadata word, accessed through `directory_mem`.

| Bits | Field | Meaning |
| --- | --- | --- |
| `[1:0]` | `line_state` | Invalid, Shared, or Modified |
| `[3:2]` | `line_sharers` | Bit 0 is cache 0, bit 1 is cache 1 |
| `[4]` | `line_owner` | Modified owner, 0 = cache 0, 1 = cache 1 |
| `[5]` | `line_data_valid` | Stored directory data is valid |
| `[31:6]` | unused | Reserved |

## MSI Encodings

### Line States

| Name | Value | Meaning |
| --- | --- | --- |
| `LINE_INVALID` | `2'b00` | No valid directory entry |
| `LINE_SHARED` | `2'b01` | One or both caches hold a clean copy |
| `LINE_MODIFIED` | `2'b10` | One cache owns the dirty copy |

### Cache Request Commands (one-hot)

| Name | Value | Meaning |
| --- | --- | --- |
| `CACHE_CMD_BUS_RD` | `5'b00001` | Request a readable copy |
| `CACHE_CMD_BUS_RDX` | `5'b00010` | Request exclusive ownership and data |
| `CACHE_CMD_BUS_UPGR` | `5'b00100` | Upgrade a shared copy to writable |
| `CACHE_CMD_EVICT_CLEAN` | `5'b01000` | Drop a clean shared copy |
| `CACHE_CMD_EVICT_DIRTY` | `5'b10000` | Write back and drop a dirty copy |

### Directory Response Commands (one-hot)

| Name | Value | Meaning |
| --- | --- | --- |
| `DIR_CMD_BUS_RD_ACK` | `6'b000001` | Read acknowledgement |
| `DIR_CMD_BUS_RDX_ACK` | `6'b000010` | Exclusive read acknowledgement |
| `DIR_CMD_BUS_UPGR_ACK` | `6'b000100` | Upgrade acknowledgement |
| `DIR_CMD_SNOOP_BUS_RD` | `6'b001000` | Ask current owner for shared read data |
| `DIR_CMD_SNOOP_BUS_RDX` | `6'b010000` | Ask current owner to transfer ownership |
| `DIR_CMD_SNOOP_BUS_UPGR` | `6'b100000` | Ask another sharer to invalidate |

Acknowledgement commands go to the requester. Snoop commands go to the other
cache when it must provide data or invalidate a copy.

## Port Groups

- **Clock and reset:** `clk_i`, `rst_ni` (active low). After reset, the
  controller invalidates all metadata before accepting requests, then asserts
  `dir_state_invalidated_o`.
- **Cache request inputs** (per cache): `c*_bus_valid_i`, `c*_bus_addr_i`,
  `c*_bus_wdata_i`, `c*_bus_cache_cmd_i`, `c*_bus_ready_o`.
- **Cache snoop ack inputs** (per cache): `c*_snoop_valid_i`, `c*_snoop_data_i`,
  `c*_snoop_cache_cmd_i`, `c*_snoop_ready_o`.
- **Directory response outputs** (per cache): `c*_dir_valid_o`, `c*_dir_data_o`,
  `c*_dir_addr_o`, `c*_dir_cmd_o`, `c*_dir_ready_i`.
- **Unified `directory_mem` port:** request side carries
  `dir_mem_valid_o`/`dir_mem_ready_i`, `dir_mem_addr_o`, `dir_mem_wstrb_o`, and
  the packed write fields (`dir_mem_w_state_o`, `dir_mem_w_sharers_o`,
  `dir_mem_w_owner_o`, `dir_mem_w_valid_data_o`, `dir_mem_w_data_o`); response
  side carries the read fields (`dir_mem_r_*`) with `dir_mem_resp_ready_o`.
  Reads use `wstrb = 4'b0000`, writes use `wstrb = 4'b1111`.

## State Machine

Each memory operation is stretched across two accepted phases (a `*Req` and a
`*Resp` state) so the address and control signals stay stable while the memory
path produces valid read data or commits a write.

| State | Purpose |
| --- | --- |
| `StInitMetaReq` / `StInitMetaResp` | Invalidate each metadata entry after reset (indices 0–127) |
| `StIdle` | Accept one request selected by the WRR arbiter |
| `StReadMetaReq` / `StReadMetaResp` | Read and capture line metadata |
| `StLookup` | Decide the coherence action |
| `StReadBackupReq` / `StReadBackupResp` | Read the requester's backup data word |
| `StSendSnoop` | Send snoop command to the conflicting cache |
| `StWaitSnoop` | Wait for snoop ack; capture an early dirty flush if it arrives |
| `StSendAck` | Deliver the final response to the requester |
| `StWriteBackup0Req` / `StWriteBackup0Resp` | Update cache 0 backup word |
| `StWriteBackup1Req` / `StWriteBackup1Resp` | Update cache 1 backup word |
| `StWriteMetaReq` / `StWriteMetaResp` | Write updated metadata fields |
| `StDone` | Single-cycle cleanup before returning to idle |

### Typical Flow

```text
Idle
Read metadata
Lookup coherence action
Optionally read backup data
Optionally send and wait for snoop
Send acknowledgement
Optionally write backup data (cache 0 then cache 1)
Optionally write metadata
Done
Idle
```

## Lookup Decisions

`StLookup` chooses whether to acknowledge immediately, read backup data first,
or send a snoop.

| Command | Condition | Action |
| --- | --- | --- |
| `BUS_RD` | Other cache is Modified owner | Snoop owner (`SNOOP_BUS_RD`), then `StSendSnoop` |
| `BUS_RD` | No other Modified owner | Read backup, ack `BUS_RD_ACK`, line → Shared, add requester as sharer |
| `BUS_RDX` | Other cache is Modified owner | Snoop owner (`SNOOP_BUS_RDX`), then `StSendSnoop` |
| `BUS_RDX` | Line Shared and other is sharer | Read backup, then snoop other sharer (`SNOOP_BUS_UPGR`); line → Modified, requester owner |
| `BUS_RDX` | No conflict | Read backup, ack `BUS_RDX_ACK`, line → Modified, requester owner, clear sharers |
| `BUS_UPGR` | Line Shared and other is sharer | Snoop other sharer (`SNOOP_BUS_UPGR`), then `StSendSnoop` |
| `BUS_UPGR` | No other sharer | Ack `BUS_UPGR_ACK`, line → Modified, requester owner |
| `EVICT_CLEAN` | Last sharer removed | Line → Invalid, clear sharers/owner/data-valid |
| `EVICT_CLEAN` | Sharer remains | Keep Shared with remaining sharer |
| `EVICT_DIRTY` | — | Write back dirty data to backup, invalidate metadata, clear data |

### After a Snoop Completes

| Original request | Requester ack | Resulting metadata |
| --- | --- | --- |
| `BUS_RD` | `BUS_RD_ACK` with latest data | Shared; requester and snooped cache are sharers; owner cleared; data valid |
| `BUS_RDX` | `BUS_RDX_ACK` (data on `SNOOP_BUS_RDX`) | Modified; requester owner; sharers cleared; data valid |
| `BUS_UPGR` | `BUS_UPGR_ACK` with data 0 | Modified; requester owner; sharers cleared |

When waiting in `StWaitSnoop`, if dirty flush data arrives before the snoop ack,
the controller latches it in `flush_seen_q`/`flush_data_q` and uses it as the
latest data.

## Debugging Notes

- A cold read returning the wrong value usually means the line had a prior dirty
  eviction; backing memory may persist that value across resets.
- A read from address 128 aliasing with address 0 is expected — only addresses
  0–127 are owned by this controller.
- If a snoop is never sent, check `line_state_q`, `line_owner_q`, and
  `line_sharers_q` after the metadata read.
- If a clean eviction reuses stale data, confirm the final-sharer case clears
  the data-valid bit.
