# Directory Controller RTL Guide

This guide is meant to be read next to `src/directory_controller.sv`. It explains what each major part of the RTL is doing, why it exists, and how the controller fits into the larger memory system.

## 1. What this module does

`directory_controller` is the coherence controller for the directory owned cache lines. It receives decoded coherence requests from two `directory_interface` blocks, updates MSI directory state, talks to memory, and sends decoded responses back to the interfaces.

The module handles two cache side ports:

1. Cache 0 request, snoop, and response path
2. Cache 1 request, snoop, and response path

It also has one memory side port:

1. Used to read and write backing data
2. Used to read and write internal directory metadata
3. Used to read and write internal directory stored data

The controller does not serialize or deserialize interposer packets. That work belongs to `directory_interface`. This RTL starts after packet decode and ends before packet encode.

## 2. Where the file belongs

Expected project placement:

```text
Open_Memory_Manager/src/directory_controller.sv
Open_Memory_Manager/cocotb/directory_controller_tb.py
```

## 3. Address ownership

The directory controller intentionally tracks only 128 coherent line addresses. It does not store tags. The index is taken from:

```systemverilog
assign request_index = request_addr_q[6:0];
```

Because only the low 7 bits are used, the directory supports 128 unique tracked lines.

### Address map

```text
0 to 127
  Directory tracked coherent data lines.
  These are the cacheable lines managed by this controller.

128 to 1791
  Normal system main memory outside this directory controller.
  These addresses should be routed through the rest of the system memory path,
  not through this directory controller path.

1792 to 1919
  Directory metadata region.
  One word per tracked line.
  Address = 1792 + request_index.

1920 to 2047
  Directory stored data region.
  One word per tracked line.
  Address = 1920 + request_index.
```

The important point is that addresses above 127 are not a bug case for this controller. They are outside the controller owned coherent range.

## 4. Metadata format

Each tracked line has one metadata word in the reserved metadata region.

```text
bits 1:0
  MSI line state

bits 3:2
  sharer bits
  bit 0 means cache 0 is a sharer
  bit 1 means cache 1 is a sharer

bit 4
  modified owner
  0 means cache 0 owns the modified line
  1 means cache 1 owns the modified line

bit 5
  directory stored data valid

bits 31:6
  unused
```

The metadata is packed in RTL as:

```systemverilog
assign packed_metadata = {
  26'b0,
  pending_write_data_valid_q,
  pending_write_owner_q,
  pending_write_sharers_q,
  pending_write_state_q
};
```

## 5. Line states

The controller uses a small MSI state model:

```systemverilog
LineInvalid  = 2'b00
LineShared   = 2'b01
LineModified = 2'b10
```

Meaning:

1. `LineInvalid`
   The directory has no valid coherence state for this line.

2. `LineShared`
   One or both caches may have a clean copy.

3. `LineModified`
   Exactly one cache owns the most recent dirty copy.

## 6. Cache side request commands

The cache side request commands are one hot.

```systemverilog
CacheCmdBusRd      = 5'b00001
CacheCmdBusRdx     = 5'b00010
CacheCmdBusUpgr    = 5'b00100
CacheCmdEvictClean = 5'b01000
CacheCmdEvictDirty = 5'b10000
```

Meaning:

1. `BusRd`
   A cache wants a readable copy.

2. `BusRdx`
   A cache wants exclusive ownership and data.

3. `BusUpgr`
   A cache already has a shared copy and wants write permission.

4. `EvictClean`
   A cache is dropping a clean copy.

5. `EvictDirty`
   A cache is writing back a dirty copy.

## 7. Directory response commands

The controller sends one hot decoded commands back to the selected `directory_interface`.

```systemverilog
DirCmdBusRdAck     = 6'b000001
DirCmdBusRdxAck    = 6'b000010
DirCmdBusUpgrAck   = 6'b000100
DirCmdSnoopBusRd   = 6'b001000
DirCmdSnoopBusRdx  = 6'b010000
DirCmdSnoopBusUpgr = 6'b100000
```

Acknowledgement commands go to the requester. Snoop commands go to the other cache when the other cache must provide data or invalidate a copy.

## 8. Main port groups

### Clock and reset

```systemverilog
clk_i
rst_ni
```

`rst_ni` is active low. After reset, the controller initializes the internal directory metadata and data regions before accepting normal requests.

### Cache request inputs

Each cache has a bus request path:

```systemverilog
c0_bus_valid_i
c0_bus_addr_i
c0_bus_wdata_i
c0_bus_cache_cmd_i
c0_bus_ready_o

c1_bus_valid_i
c1_bus_addr_i
c1_bus_wdata_i
c1_bus_cache_cmd_i
c1_bus_ready_o
```

These are decoded cache side requests from `directory_interface`.

### Cache snoop acknowledgement inputs

Each cache has a snoop acknowledgement path:

```systemverilog
c0_snoop_valid_i
c0_snoop_data_i
c0_snoop_cache_cmd_i
c0_snoop_ready_o

c1_snoop_valid_i
c1_snoop_data_i
c1_snoop_cache_cmd_i
c1_snoop_ready_o
```

These are used when the controller has sent a snoop and is waiting for the snooped cache to respond.

### Directory response outputs

Each cache has a response path:

```systemverilog
c0_dir_valid_o
c0_dir_data_o
c0_dir_addr_o
c0_dir_cmd_o
c0_dir_ready_i

c1_dir_valid_o
c1_dir_data_o
c1_dir_addr_o
c1_dir_cmd_o
c1_dir_ready_i
```

These go back into `directory_interface`, which serializes the response back across the interposer.

### Memory port

```systemverilog
dir_mem_valid_o
dir_mem_instr_o
dir_mem_addr_o
dir_mem_wdata_o
dir_mem_wstrb_o
dir_mem_rdata_i
dir_mem_ready_i
```

The controller uses this port for both normal backing data and internal directory storage. Reads use `wstrb = 4'b0000`. Writes use `wstrb = 4'b1111`.

## 9. Why memory operations use request and response states

The memory path may not return read data in the same cycle that a request is accepted. To avoid sampling stale data, each memory operation is stretched across two accepted phases.

Example:

1. `StReadMetaReq`
   Assert memory valid and hold the metadata address.

2. `StReadMetaResp`
   Keep memory valid and the same address stable, then capture `dir_mem_rdata_i`.

This same pattern is used for metadata reads, directory data reads, backing memory reads, backing memory writes, metadata writes, and directory data writes.

This was important for the GF180 backed memory path.

## 10. Startup initialization

After reset, the controller clears the internal directory storage:

1. `StInitMetaReq`
2. `StInitMetaResp`
3. `StInitDataReq`
4. `StInitDataResp`

This repeats for indices 0 through 127.

The metadata region and directory data region are cleared. The normal backing memory region is not cleared by this controller.

## 11. Request selection

When both caches request at the same time, the controller uses an internal two request round robin selector.

Relevant signals:

```systemverilog
request_priority_q
selected_valid
selected_cache
```

The controller handles one request at a time. If both arrive together, `request_priority_q` chooses the winner and then flips priority for the next tie.

## 12. Normal request flow

A normal request follows this high level sequence:

1. `StIdle`
   Accept one cache request.

2. `StReadMetaReq` and `StReadMetaResp`
   Read the line metadata from the reserved metadata region.

3. `StReadDirDataReq` and `StReadDirDataResp`
   Read the stored directory data word.

4. Optional `StReadBackingReq` and `StReadBackingResp`
   If the directory stored data is not valid, read the backing data address.

5. `StLookup`
   Decide whether to acknowledge immediately, send a snoop, or write updated state.

6. Optional `StSendSnoop` and `StWaitSnoop`
   Used if the other cache must provide data or invalidate a copy.

7. `StSendAck`
   Send the final response to the requester.

8. Optional writeback states
   Update backing memory, metadata, or stored directory data.

9. `StDone`
   Return to idle.

## 13. Main MSI behavior

### BusRd

If no other cache owns a modified copy, the requester receives the current line data and becomes a sharer.

If the other cache owns a modified copy, the controller snoops that owner first. After the owner responds, both caches become sharers and the requester receives the latest data.

### BusRdx

If no other cache has a conflicting copy, the requester receives the current line data and becomes the modified owner.

If the other cache owns a modified copy, the controller snoops that owner and transfers the latest data to the requester.

If the line is shared by the other cache, the controller sends an upgrade snoop to invalidate the other sharer before granting modified ownership.

### BusUpgr

If the other cache is a sharer, the controller sends an upgrade snoop to invalidate it.

If the requester is already the only relevant holder, the controller can acknowledge immediately and mark the requester as modified owner.

### EvictClean

The requester is removed from the sharer set.

If at least one sharer remains, the line stays shared.

If no sharers remain, the line becomes invalid and `data_valid` is cleared. Clearing `data_valid` is important because the next `BusRd` must go back to backing memory instead of reusing stale directory stored data.

### EvictDirty

The dirty data is written to the normal backing memory address. The directory metadata is then invalidated and the stored directory data is cleared.

## 14. Important internal registers

```systemverilog
request_cache_q
request_addr_q
request_data_q
request_cmd_q
```

Hold the accepted request while the FSM processes it.

```systemverilog
line_state_q
line_sharers_q
line_owner_q
line_data_valid_q
line_data_q
```

Hold the current line state read from directory storage.

```systemverilog
pending_ack_cache_q
pending_ack_cmd_q
pending_ack_data_q
```

Hold the response that will be sent back to the requester.

```systemverilog
pending_snoop_cache_q
pending_snoop_cmd_q
```

Hold the snoop that will be sent to the other cache.

```systemverilog
pending_write_state_q
pending_write_sharers_q
pending_write_owner_q
pending_write_data_valid_q
pending_write_data_q
```

Hold the next metadata and stored data values before they are written back.

```systemverilog
pending_write_backing_q
pending_write_backing_data_q
```

Used when dirty data must also be written to backing memory.

```systemverilog
flush_seen_q
flush_data_q
```

Used while waiting for a snooped cache. If dirty data arrives before the final snoop acknowledgement, the controller remembers it.

## 15. What the standalone testbench verifies

The controller only testbench drives decoded requests directly into `directory_controller`. It does not instantiate `directory_interface` or the GF180 memory wrapper.

It verifies:

1. Cold reads from both cache sides
2. Dirty eviction and later readback
3. Several nonzero data patterns
4. Boundary addresses inside the 128 line directory range
5. Modified owner snooping in both directions
6. `BusRdx` ownership transfer in both directions
7. Shared line invalidation
8. `BusUpgr` with one sharer and with two sharers
9. Clean eviction as the last sharer
10. Clean eviction when one sharer remains
11. Repeated operations on the same line
12. Simultaneous requests from both cache sides
13. Seeded randomized dirty writeback and readback

## 16. What this module intentionally does not do

This module does not:

1. Serialize or deserialize packets
2. Track more than 128 coherent line addresses
3. Store address tags
4. Handle normal system memory addresses above 127 as directory coherent lines
5. Clear normal backing memory on reset
6. Process more than one request at a time

Those choices are intentional for the current project structure.

## 17. Quick debugging guide

If a cold read returns the wrong value, check whether the line previously had a dirty eviction. Normal backing memory may keep that value across resets.

If a read from address 128 aliases with address 0, that is expected for this controller. The controller only owns addresses 0 through 127.

If a snoop is never sent, check `line_state_q`, `line_owner_q`, and `line_sharers_q` after metadata read.

If a dirty value is lost, check the path through `StWriteBackingReq`, `StWriteBackingResp`, `StWriteMetaReq`, and `StWriteDirDataReq`.

If a clean eviction causes stale data to be reused, check that the final sharer case clears `pending_write_data_valid_d`.

## 18. Short summary

`directory_controller` is a two cache MSI directory controller for 128 coherent lines. It stores directory metadata in addresses 1792 through 1919 and stored directory data in addresses 1920 through 2047. It accepts decoded requests from `directory_interface`, performs snoops when needed, updates metadata, writes back dirty data, and returns decoded acknowledgements to the correct cache side.

