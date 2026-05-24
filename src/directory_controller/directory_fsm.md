# Directory Controller State Machine Reference

This file describes only the `directory_controller` finite state machine logic. It does not cover packet serialization, deserialization, or the internal behavior of `directory_interface`.

## 1. Scope

The FSM accepts one decoded cache request at a time, reads the current directory state from memory, decides the MSI coherence action, optionally sends a snoop, sends an acknowledgement, and writes updated directory state back to memory.

## 2. Key Encodings

### Cache request commands

| Command | Value | Meaning |
|---|---:|---|
| `CacheCmdBusRd` | `00001` | Request a readable copy |
| `CacheCmdBusRdx` | `00010` | Request exclusive ownership and data |
| `CacheCmdBusUpgr` | `00100` | Upgrade a shared copy to writable |
| `CacheCmdEvictClean` | `01000` | Drop a clean shared copy |
| `CacheCmdEvictDirty` | `10000` | Write back and drop a dirty modified copy |

### Snoop acknowledgement commands

| Command | Value | Meaning |
|---|---:|---|
| `SnoopAckBusRd` | `001` | Response to a read snoop |
| `SnoopAckBusRdx` | `010` | Response to an ownership transfer snoop |
| `SnoopAckBusUpgr` | `100` | Response to an invalidation snoop |

### Directory response commands

| Command | Value | Meaning |
|---|---:|---|
| `DirCmdBusRdAck` | `000001` | Read acknowledgement |
| `DirCmdBusRdxAck` | `000010` | Exclusive read acknowledgement |
| `DirCmdBusUpgrAck` | `000100` | Upgrade acknowledgement |
| `DirCmdSnoopBusRd` | `001000` | Ask current owner for shared read data |
| `DirCmdSnoopBusRdx` | `010000` | Ask current owner to transfer ownership |
| `DirCmdSnoopBusUpgr` | `100000` | Ask another sharer to invalidate |

### Line states

| State | Value | Meaning |
|---|---:|---|
| `LineInvalid` | `00` | No valid directory entry |
| `LineShared` | `01` | One or both caches hold a clean copy |
| `LineModified` | `10` | One cache owns the dirty copy |

## 3. Dedicated Address Regions

The directory controller intentionally tracks 128 coherent line IDs. It does not store tags.

| Address range | Owner | Purpose |
|---:|---|---|
| `0` to `127` | Directory controller | Coherent tracked line IDs |
| `128` to `1791` | System memory path | Normal main memory outside this controller |
| `1792` to `1919` | Directory controller | Metadata words, one per tracked line |
| `1920` to `2047` | Directory controller | Stored data words, one per tracked line |

The directory index is:

```systemverilog
request_addr_q[6:0]
```

So the metadata and stored data addresses are:

```systemverilog
metadata_addr = 1792 + request_addr_q[6:0]
data_addr     = 1920 + request_addr_q[6:0]
```

## 4. Metadata Word Layout

| Bits | Field | Meaning |
|---:|---|---|
| `[1:0]` | `line_state` | Invalid, Shared, or Modified |
| `[3:2]` | `line_sharers` | Bit 0 is cache 0, bit 1 is cache 1 |
| `[4]` | `line_owner` | Modified owner, 0 for cache 0 and 1 for cache 1 |
| `[5]` | `line_data_valid` | Stored directory data is valid |
| `[31:6]` | unused | Reserved |

## 5. State Summary

| State | Purpose |
|---|---|
| `StInitMetaReq` | Start clearing one metadata word |
| `StInitMetaResp` | Hold metadata clear write stable |
| `StInitDataReq` | Start clearing one stored data word |
| `StInitDataResp` | Hold stored data clear write stable and advance initialization |
| `StIdle` | Wait for and accept one cache request |
| `StReadMetaReq` | Start metadata read for the selected line |
| `StReadMetaResp` | Capture metadata |
| `StReadDirDataReq` | Start stored directory data read |
| `StReadDirDataResp` | Capture stored data and decide whether backing memory is needed |
| `StReadBackingReq` | Start backing memory read |
| `StReadBackingResp` | Capture backing memory data |
| `StLookup` | Decide the coherence action |
| `StSendSnoop` | Send snoop command to the other cache |
| `StWaitSnoop` | Wait for snoop acknowledgement and optional dirty flush |
| `StSendAck` | Send final acknowledgement to requester |
| `StWriteBackingReq` | Start dirty writeback to backing memory |
| `StWriteBackingResp` | Hold dirty writeback stable |
| `StWriteMetaReq` | Start metadata write |
| `StWriteMetaResp` | Hold metadata write stable |
| `StWriteDirDataReq` | Start stored data write |
| `StWriteDirDataResp` | Hold stored data write stable |
| `StDone` | One cycle cleanup before returning idle |

## 6. Detailed State Transitions

### Initialization states

| State | Active outputs | Transition |
|---|---|---|
| `StInitMetaReq` | `dir_mem_valid_o = 1`, `dir_mem_addr_o = 1792 + init_index_q`, `dir_mem_wdata_o = 0`, `dir_mem_wstrb_o = 1111` | If `dir_mem_ready_i = 1`, go to `StInitMetaResp`; otherwise stay |
| `StInitMetaResp` | Same metadata clear write as `StInitMetaReq` | If `dir_mem_ready_i = 1`, go to `StInitDataReq`; otherwise stay |
| `StInitDataReq` | `dir_mem_valid_o = 1`, `dir_mem_addr_o = 1920 + init_index_q`, `dir_mem_wdata_o = 0`, `dir_mem_wstrb_o = 1111` | If `dir_mem_ready_i = 1`, go to `StInitDataResp`; otherwise stay |
| `StInitDataResp` | Same stored data clear write as `StInitDataReq` | If `dir_mem_ready_i = 0`, stay. If ready and `init_index_q != 127`, increment index and go to `StInitMetaReq`. If ready and `init_index_q == 127`, go to `StIdle` |

### Request accept and read states

| State | Active outputs | Transition |
|---|---|---|
| `StIdle` | If a selected request exists, assert that cache side `bus_ready_o` | If no request is selected, stay. If a request is selected, latch cache ID, address, data, and command, then go to `StReadMetaReq` |
| `StReadMetaReq` | `dir_mem_valid_o = 1`, `dir_mem_addr_o = 1792 + request_addr_q[6:0]`, `dir_mem_wstrb_o = 0000` | If `dir_mem_ready_i = 1`, go to `StReadMetaResp`; otherwise stay |
| `StReadMetaResp` | Same metadata read as `StReadMetaReq` | If `dir_mem_ready_i = 1`, capture state, sharers, owner, and data valid, then go to `StReadDirDataReq`; otherwise stay |
| `StReadDirDataReq` | `dir_mem_valid_o = 1`, `dir_mem_addr_o = 1920 + request_addr_q[6:0]`, `dir_mem_wstrb_o = 0000` | If `dir_mem_ready_i = 1`, go to `StReadDirDataResp`; otherwise stay |
| `StReadDirDataResp` | Same stored data read as `StReadDirDataReq` | If not ready, stay. If ready and `line_data_valid_q = 1`, capture data and go to `StLookup`. If ready and `line_data_valid_q = 0`, capture data and go to `StReadBackingReq` |
| `StReadBackingReq` | `dir_mem_valid_o = 1`, `dir_mem_addr_o = request_addr_q[10:0]`, `dir_mem_wstrb_o = 0000` | If `dir_mem_ready_i = 1`, go to `StReadBackingResp`; otherwise stay |
| `StReadBackingResp` | Same backing memory read as `StReadBackingReq` | If `dir_mem_ready_i = 1`, capture backing memory data and go to `StLookup`; otherwise stay |

### Lookup state

`StLookup` is the decision state. It chooses whether the controller can acknowledge immediately, must send a snoop first, or must write updated state directly.

| Request command | Condition | Next action |
|---|---|---|
| `CacheCmdBusRd` | Other cache is Modified owner | Snoop owner with `DirCmdSnoopBusRd`, then go to `StSendSnoop` |
| `CacheCmdBusRd` | No other Modified owner | Prepare `DirCmdBusRdAck`, make line Shared, add requester as sharer, mark stored data valid, then go to `StSendAck` |
| `CacheCmdBusRdx` | Other cache is Modified owner | Snoop owner with `DirCmdSnoopBusRdx`, then go to `StSendSnoop` |
| `CacheCmdBusRdx` | Line is Shared and other cache is a sharer | Snoop other sharer with `DirCmdSnoopBusUpgr`, then go to `StSendSnoop` |
| `CacheCmdBusRdx` | No conflicting owner or sharer | Prepare `DirCmdBusRdxAck`, make requester Modified owner, clear sharers, mark stored data valid, then go to `StSendAck` |
| `CacheCmdBusUpgr` | Line is Shared and other cache is a sharer | Snoop other sharer with `DirCmdSnoopBusUpgr`, then go to `StSendSnoop` |
| `CacheCmdBusUpgr` | No other sharer needs invalidation | Prepare `DirCmdBusUpgrAck`, make requester Modified owner, then go to `StSendAck` |
| `CacheCmdEvictClean` | Last sharer is removed | Make line Invalid, clear sharers, clear owner, clear stored data valid, then go to `StWriteMetaReq` |
| `CacheCmdEvictClean` | At least one sharer remains | Keep line Shared with remaining sharers, then go to `StWriteMetaReq` |
| `CacheCmdEvictDirty` | Dirty data is evicted | Mark backing write pending, invalidate metadata, clear stored data, then go to `StWriteBackingReq` |
| Default | Unknown command | Go to `StIdle` |

### Snoop states

| State | Active outputs | Transition |
|---|---|---|
| `StSendSnoop` | Selected cache `dir_valid_o = 1`, `dir_cmd_o = pending_snoop_cmd_q`, `dir_addr_o = request_addr_q`, `dir_data_o = line_data_q` | If selected cache `dir_ready_i = 1`, go to `StWaitSnoop`; otherwise stay |
| `StWaitSnoop` | Keep snoop packet visible while waiting. Assert bus ready if dirty flush is accepted. Assert snoop ready if snoop acknowledgement is accepted | If no dirty flush or snoop ack is accepted, stay. If dirty flush arrives first, remember the data and stay. If snoop ack arrives, prepare requester ack and updated metadata, then go to `StSendAck` |

### Snoop completion behavior

| Original request | Requester ack | New metadata |
|---|---|---|
| `CacheCmdBusRd` | `DirCmdBusRdAck` with latest data | Line becomes Shared. Requester and snooped cache are sharers. Owner clears to 0. Stored data becomes valid |
| `CacheCmdBusRdx` | `DirCmdBusRdxAck` with latest data | Line becomes Modified. Requester becomes owner. Sharers clear to 0. Stored data becomes valid |
| `CacheCmdBusUpgr` | `DirCmdBusUpgrAck` with data 0 | Line becomes Modified. Requester becomes owner. Sharers clear to 0. Existing stored data valid bit and stored data are preserved |

### Acknowledgement and writeback states

| State | Active outputs | Transition |
|---|---|---|
| `StSendAck` | Requester `dir_valid_o = 1`, `dir_cmd_o = pending_ack_cmd_q`, `dir_addr_o = request_addr_q`, `dir_data_o = pending_ack_data_q` | If requester is not ready, stay. If ready and no pending write, go to `StIdle`. If ready and backing write is pending, go to `StWriteBackingReq`. If ready and only directory update is pending, go to `StWriteMetaReq` |
| `StWriteBackingReq` | `dir_mem_valid_o = 1`, `dir_mem_addr_o = request_addr_q[10:0]`, `dir_mem_wdata_o = pending_write_backing_data_q`, `dir_mem_wstrb_o = 1111` | If `dir_mem_ready_i = 1`, go to `StWriteBackingResp`; otherwise stay |
| `StWriteBackingResp` | Same dirty backing write as `StWriteBackingReq` | If `dir_mem_ready_i = 1`, go to `StWriteMetaReq`; otherwise stay |
| `StWriteMetaReq` | `dir_mem_valid_o = 1`, `dir_mem_addr_o = 1792 + request_addr_q[6:0]`, `dir_mem_wdata_o = packed metadata`, `dir_mem_wstrb_o = 1111` | If `dir_mem_ready_i = 1`, go to `StWriteMetaResp`; otherwise stay |
| `StWriteMetaResp` | Same metadata write as `StWriteMetaReq` | If `dir_mem_ready_i = 1`, go to `StWriteDirDataReq`; otherwise stay |
| `StWriteDirDataReq` | `dir_mem_valid_o = 1`, `dir_mem_addr_o = 1920 + request_addr_q[6:0]`, `dir_mem_wdata_o = pending_write_data_q`, `dir_mem_wstrb_o = 1111` | If `dir_mem_ready_i = 1`, go to `StWriteDirDataResp`; otherwise stay |
| `StWriteDirDataResp` | Same stored data write as `StWriteDirDataReq` | If `dir_mem_ready_i = 1`, go to `StDone`; otherwise stay |
| `StDone` | No memory request and no cache response | Go to `StIdle` |

## 7. Important State Side Effects

| State | Side effects |
|---|---|
| `StIdle` | Clears pending write and flush seen state. Latches selected request. Updates round robin priority |
| `StReadMetaResp` | Updates `line_state_q`, `line_sharers_q`, `line_owner_q`, and `line_data_valid_q` |
| `StReadDirDataResp` | Updates `line_data_q` from reserved directory data |
| `StReadBackingResp` | Updates `line_data_q` from normal backing memory |
| `StLookup` | Sets pending ack, pending snoop, and pending write information |
| `StWaitSnoop` | Captures dirty flush data if it arrives before snoop ack |
| `StSendAck` | Waits until requester accepts final response before writing directory updates |
| `StWriteBackingResp` | Completes dirty writeback before metadata is invalidated |
| `StWriteMetaResp` | Completes metadata update before stored data update |
| `StWriteDirDataResp` | Completes stored data update before cleanup |

## 8. Short FSM Flow

Most requests follow this pattern:

```text
Idle
Read metadata
Read stored directory data
Optionally read backing memory
Lookup coherence action
Optionally send and wait for snoop
Send acknowledgement
Optionally write backing memory
Write metadata
Write stored directory data
Done
Idle
```

The request and response memory states are intentionally separated so the memory address and control signals remain stable while the memory path produces valid data or commits a write.

