# MSI Cache Coherence System — Module Documentation

**Project:** Multi-Core Shared Memory CPU System  
**Modules:** `msi.py`, `cache.py`, `directory.py`  
**Protocol:** MSI (Modified-Shared-Invalid) Directory-Based Cache Coherence  

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Module: msi.py — Protocol Core](#2-module-msipy--protocol-core)
3. [Module: cache.py — Cache Controller](#3-module-cachepy--cache-controller)
4. [Module: directory.py — Directory Controller](#4-module-directorypy--directory-controller)
5. [MSI State Machine — Full Transition Tables](#5-msi-state-machine--full-transition-tables)
6. [Inter-Module Communication](#6-inter-module-communication)
7. [Transaction Payload Specification](#7-transaction-payload-specification)
8. [End-to-End Transaction Walkthroughs](#8-end-to-end-transaction-walkthroughs)
9. [Implementation Notes and Limitations](#9-implementation-notes-and-limitations)

---

## 1. System Overview

This system implements a two-core (extensible to N-core) shared-memory multiprocessor with directory-based MSI cache coherence. Each CPU core has a private cache managed by a `CacheController`. A single `DirectoryController` acts as the home node for all memory addresses, tracking global cache state and arbitrating coherence.

All communication between modules uses the `axi_request` structure defined in `msi.py`. The `mem_instr` flag distinguishes coherence traffic (`True`) from normal CPU memory traffic (`False`).

---

## 2. Module: `msi.py` — Protocol Core

This module is the shared foundation for the entire coherence system. It defines all data structures, enumerations, and the state machine logic consumed by both `cache.py` and `directory.py`.

### 2.1 `axi_request` — Unified Communication Structure

All inter-module communication passes through this dataclass. It is used for CPU-to-cache requests, cache-to-directory coherence commands, and directory-to-cache snoop messages.

| Field | Type | Description |
|---|---|---|
| `mem_valid` | bool | Initiator asserts this to mark the request as valid |
| `mem_instr` | bool | `True` = coherence traffic; `False` = normal memory access |
| `mem_ready` | bool | Responder asserts this to acknowledge the request |
| `mem_addr` | int | Word-aligned memory address |
| `mem_wdata` | int | Write data, or a packed coherence command word |
| `mem_wstrb` | int | Byte-enable mask (0x0 = read; 0xF = full-word write) |
| `mem_rdata` | int | Read data, or coherence response data (e.g., flush data) |

### 2.2 `MSIState` — Cache Line States

| Value | Name | Meaning |
|---|---|---|
| 0 | `INVALID` | No valid copy in this cache |
| 1 | `SHARED` | Read-only copy; may be held by multiple caches simultaneously |
| 2 | `MODIFIED` | Exclusive, dirty copy; no other cache may hold this line |

**Protocol Invariants:**
- At most one cache may hold a line in `MODIFIED` state at any time.
- If any cache is `MODIFIED`, all other caches must be `INVALID` for that address.
- Multiple caches may simultaneously hold `SHARED` state for the same address.

### 2.3 `ProcessorEvent` — CPU-Initiated Triggers

| Value | Name | Description |
|---|---|---|
| 0 | `PR_RD` | CPU read request |
| 1 | `PR_WR` | CPU write request |

### 2.4 `SnoopEvent` — Directory-Initiated Triggers

| Value | Name | Description |
|---|---|---|
| 0 | `BUS_RD` | Another cache issued a read miss |
| 1 | `BUS_RDX` | Another cache issued a write miss |
| 2 | `BUS_UPGR` | Another cache is upgrading from Shared to Modified |

### 2.5 `CoherenceCmd` — Command Encoding

Commands are encoded as integers and multiplexed through `mem_wdata` using `pack_cmd` / `unpack_cmd`.

**Cache → Directory:**

| Value | Name | Description |
|---|---|---|
| 1 | `BUS_RD` | Read miss; request data from directory |
| 2 | `BUS_RDX` | Write miss; request data and exclusive ownership |
| 3 | `BUS_UPGR` | Upgrade request; already have data, request exclusive ownership |
| 4 | `EVICT_CLEAN` | Evicting a Shared line; no writeback required |
| 5 | `EVICT_DIRTY` | Evicting a Modified line; dirty data included |

**Directory → Cache (Snoops):**

| Value | Name | Description |
|---|---|---|
| 17 | `SNOOP_BUS_RD` | Another cache is reading; share if Modified |
| 18 | `SNOOP_BUS_RDX` | Another cache is writing; invalidate and flush if Modified |
| 19 | `SNOOP_BUS_UPGR` | Another cache is upgrading; invalidate |

Snoop values are offset to 17+ to avoid collision with cache-to-directory command values in the packed word.

### 2.6 `pack_cmd` / `unpack_cmd` — Command Word Encoding

Coherence commands are packed into a single 32-bit word placed in `mem_wdata`:

```
Bit layout of mem_wdata:
  [31:16]  payload   — 16-bit optional data (e.g., writeback reference)
  [15:8]   core_id   — 8-bit cache ID of the issuing/requesting cache
  [7:0]    cmd       — 8-bit CoherenceCmd value
```

`pack_cmd(cmd, core_id, payload=0)` assembles this word. `unpack_cmd(word)` returns `(cmd, core_id, payload)`.

### 2.7 `TransitionResult` — State Machine Output

Returned by both state machine functions to describe what the cache must do next.

| Field | Type | Description |
|---|---|---|
| `next_state` | `MSIState` | The state the cache line transitions into |
| `issue_cmd` | `Optional[CoherenceCmd]` | Command to send to directory, or `None` if no action needed |
| `flush` | bool | If `True`, the cache must return its dirty data to the directory |

### 2.8 `on_processor_event` — Processor State Machine

Accepts the current cache line state and a `ProcessorEvent`, returns a `TransitionResult`. Called by `CacheController` on every CPU read or write.

### 2.9 `on_snoop_event` — Snoop State Machine

Accepts the current cache line state and a `SnoopEvent`, returns a `TransitionResult`. Called by `CacheController` when the directory issues a snoop.

---

## 3. Module: `cache.py` — Cache Controller

Each CPU core has one `CacheController` instance. It manages local cache storage, consults the MSI state machine for all state transitions, issues coherence commands to the directory when needed, and responds to incoming snoop requests from the directory.

### 3.1 `CacheLine` — Per-Address Cache Storage

| Field | Type | Default | Description |
|---|---|---|---|
| `state` | `MSIState` | `INVALID` | Current MSI state of this line |
| `data` | int | 0 | Cached 32-bit data value |

Cache lines are allocated lazily: a new `CacheLine` in `INVALID` state is created on first access to any address. The implementation uses a fully-associative dictionary (`addr → CacheLine`), so there is no set-associativity or replacement policy — every address gets its own entry.

### 3.2 Constructor

```python
CacheController(core_id: int, directory_axi_handler: Callable[[axi_request], axi_request])
```

| Parameter | Description |
|---|---|
| `core_id` | Unique integer identifier for this cache (e.g., 0 or 1) |
| `directory_axi_handler` | Reference to `DirectoryController.axi_handler`; used to send coherence commands |

### 3.3 `axi_handler` — Main Entry Point

The primary interface for all inbound traffic. Demultiplexes on `mem_instr`:

- `mem_instr = False`: CPU memory traffic. If `mem_wstrb == 0`, routes to `_cpu_read`; otherwise routes to `_cpu_write`.
- `mem_instr = True`: Coherence traffic from the directory. Routes to `_handle_snoop`.

All responses set `mem_ready = True` on completion.

### 3.4 `_cpu_read(addr)` — CPU Read Path

1. Retrieves or creates the `CacheLine` for `addr`.
2. Calls `on_processor_event(line.state, PR_RD)` to determine the required action.
3. If `issue_cmd` is not `None` (i.e., a miss occurred in `INVALID` state), sends `BUS_RD` to the directory via `_send_dir_cmd` and stores the returned data into the cache line.
4. Updates `line.state` to `next_state`.
5. Returns `line.data` to the CPU.

### 3.5 `_cpu_write(addr, wdata, wstrb)` — CPU Write Path

1. Retrieves or creates the `CacheLine` for `addr`.
2. Calls `on_processor_event(line.state, PR_WR)`.
3. If `issue_cmd` is not `None`, sends the required command to the directory:
   - From `INVALID`: sends `BUS_RDX` to fetch data and acquire exclusive ownership.
   - From `SHARED`: sends `BUS_UPGR` to invalidate other sharers without a data transfer.
4. Updates `line.state` to `MODIFIED`.
5. Applies byte-level write strobe via `apply_wstrb` to merge `wdata` into the existing `line.data`.
6. Returns the updated data.

### 3.6 `_send_dir_cmd(cmd, addr, payload=0)` — Coherence Command Dispatch

Packages a coherence command into an `axi_request` and calls the directory's `axi_handler` synchronously. Sets `mem_instr = True` to identify this as coherence traffic. Returns `mem_rdata` from the directory response (carries fetched data for `BUS_RD`/`BUS_RDX`).

### 3.7 `_handle_snoop(addr, packed_cmd)` — Snoop Response

Processes a snoop request from the directory:

1. Unpacks the command word to extract the `CoherenceCmd`.
2. Maps the command to the corresponding `SnoopEvent`.
3. Calls `on_snoop_event(line.state, event)`.
4. If `tr.flush` is `True`, sets `flush_data = line.data`; otherwise `flush_data = 0`.
5. Updates `line.state`.
6. Returns `flush_data` in `mem_rdata` back to the directory.

### 3.8 `evict(addr)` — Cache Line Eviction

Handles capacity-driven eviction (for future integration with a realistic set-associative cache):

- `INVALID`: No action.
- `SHARED`: Sends `EVICT_CLEAN` to the directory; no data transferred.
- `MODIFIED`: Sends `EVICT_DIRTY` with `line.data` as payload; data is written back to memory.

In all cases, the line state is set to `INVALID` after eviction.

### 3.9 `apply_wstrb(old, new, wstrb)` — Byte-Granular Write

Applies a 4-bit write strobe mask to merge `new` data into `old` data at byte granularity. Bit `i` of `wstrb` enables update of byte `i` (bits `[8i+7 : 8i]`). This function is duplicated identically in `directory.py` for use during memory writebacks.

---

## 4. Module: `directory.py` — Directory Controller

The `DirectoryController` is the central coherence authority of the system. It tracks the global MSI state and sharer set for every memory address, arbitrates coherence requests from caches, issues snoops to other caches on their behalf, and stores the backing memory.

### 4.1 `DirectoryEntry` — Per-Address Directory State

| Field | Type | Default | Description |
|---|---|---|---|
| `state` | `MSIState` | `INVALID` | Global coherence state for this address |
| `sharers` | int | 0 | Bitmask: bit `i` = 1 means core `i` holds this line |

**Example encodings (2-core system):**

| `state` | `sharers` | Meaning |
|---|---|---|
| `INVALID` | `0b00` | No cache holds this line |
| `SHARED` | `0b01` | Only core 0 holds a shared copy |
| `SHARED` | `0b11` | Both cores hold shared copies |
| `MODIFIED` | `0b10` | Core 1 holds exclusive, dirty ownership |

Directory entries are lazily allocated on first access to an address.

**`owner()` method:** Returns the cache ID of the single owner when `state == MODIFIED`. Uses a power-of-two check (`sharers & (sharers - 1) == 0`) to confirm exactly one sharer. Returns `None` if not in `MODIFIED` state, no sharers exist, or multiple sharers are set (protocol error).

**Storage overhead:** 2 bits for state + 1 bit per core for sharers. For a 2-core system, this is 4 bits per cache line.

### 4.2 Constructor

```python
DirectoryController(num_cores: int = 2)
```

Initializes three internal structures:
- `entries: Dict[int, DirectoryEntry]` — directory state table
- `memory: Dict[int, int]` — backing memory (word-addressed)
- `cache_ports: Dict[int, Callable]` — registered AXI handlers for each cache

### 4.3 `register_cache(core_id, cache_axi_handler)` — Cache Port Registration

Stores a reference to each cache's `axi_handler` so the directory can send snoops back to caches. Must be called for every cache after instantiation.

### 4.4 `axi_handler` — Main Entry Point

Demultiplexes inbound traffic on `mem_instr`:

- `mem_instr = True`: Coherence command from a cache. Routes to `_handle_coherence`.
- `mem_instr = False, mem_wstrb == 0`: Direct memory read (non-coherent, for DMA/init).
- `mem_instr = False, mem_wstrb != 0`: Direct memory write (non-coherent, for DMA/init).

### 4.5 `_handle_coherence(addr, packed_cmd)` — Command Dispatcher

Unpacks the command word and routes to the appropriate internal handler:

| Command | Handler |
|---|---|
| `BUS_RD` | `_bus_rd` |
| `BUS_RDX` | `_bus_rdx` |
| `BUS_UPGR` | `_bus_upgr` |
| `EVICT_CLEAN` | `_evict_clean` |
| `EVICT_DIRTY` | `_evict_dirty` |

### 4.6 `_bus_rd(requester, addr)` — Read Miss Handler

| Current Dir State | Action | Next Dir State |
|---|---|---|
| `INVALID` | Serve data from memory; add requester to sharers | `SHARED` |
| `SHARED` | Serve data from memory; add requester to sharers | `SHARED` |
| `MODIFIED` | Snoop owner with `SNOOP_BUS_RD`; owner flushes data; update memory; add both owner and requester to sharers | `SHARED` |

Returns the data value to be sent back to the requesting cache.

### 4.7 `_bus_rdx(requester, addr)` — Write Miss Handler

| Current Dir State | Action | Next Dir State |
|---|---|---|
| `INVALID` | Grant exclusive ownership | `MODIFIED` |
| `SHARED` | Snoop all other sharers with `SNOOP_BUS_RDX`; they invalidate; grant exclusive to requester | `MODIFIED` |
| `MODIFIED` | Snoop current owner with `SNOOP_BUS_RDX`; owner flushes data and invalidates; update memory; transfer ownership to requester | `MODIFIED` |

Returns data to the requesting cache.

### 4.8 `_bus_upgr(requester, addr)` — Upgrade Handler

The requesting cache already holds the data in `SHARED` state and only needs exclusive ownership.

| Current Dir State | Action | Next Dir State |
|---|---|---|
| `SHARED` | Snoop all other sharers with `SNOOP_BUS_UPGR`; they invalidate; grant exclusive to requester | `MODIFIED` |
| Other | Fallback to `_bus_rdx` to handle the request correctly | `MODIFIED` |

No data transfer occurs in the normal `SHARED` case — the requester already holds valid data.

### 4.9 `_evict_clean(requester, addr)` — Clean Eviction Handler

Removes the requester from the `sharers` bitmask. If no sharers remain, transitions directory state to `INVALID`. No data is transferred.

### 4.10 `_evict_dirty(requester, addr, data)` — Dirty Eviction Handler

Writes the provided dirty data into `memory[addr]`, then calls `_evict_clean` to remove the requester from sharers and update directory state.

### 4.11 `_send_snoop(target_core, addr, snoop_cmd, requester)` — Snoop Dispatch

Constructs an `axi_request` with `mem_instr = True` and a packed snoop command word, then calls the target cache's registered `axi_handler` synchronously. Returns `mem_rdata` from the cache response, which carries dirty flush data if the cache was in `MODIFIED` state.

---

## 5. MSI State Machine — Full Transition Tables

### 5.1 Processor Event Transitions (Cache-Local)

These transitions occur inside `CacheController` whenever the CPU reads or writes.

| Current State | Event | Next State | Command to Directory | Notes |
|---|---|---|---|---|
| `INVALID` | `PR_RD` | `SHARED` | `BUS_RD` | Read miss; fetch data from directory |
| `INVALID` | `PR_WR` | `MODIFIED` | `BUS_RDX` | Write miss; fetch data and acquire exclusive ownership |
| `SHARED` | `PR_RD` | `SHARED` | None | Read hit; return cached data directly |
| `SHARED` | `PR_WR` | `MODIFIED` | `BUS_UPGR` | Write hit; invalidate other sharers, no data transfer |
| `MODIFIED` | `PR_RD` | `MODIFIED` | None | Read hit; data already exclusive |
| `MODIFIED` | `PR_WR` | `MODIFIED` | None | Write hit; data already exclusive |

### 5.2 Snoop Event Transitions (Cache Responding to Directory)

These transitions occur inside `CacheController._handle_snoop` when the directory snoops this cache on behalf of another cache.

| Current State | Snoop Event | Next State | Flush Data? | Notes |
|---|---|---|---|---|
| `INVALID` | `BUS_RD` | `INVALID` | No | No copy; ignore |
| `INVALID` | `BUS_RDX` | `INVALID` | No | No copy; ignore |
| `INVALID` | `BUS_UPGR` | `INVALID` | No | No copy; ignore |
| `SHARED` | `BUS_RD` | `SHARED` | No | Other cache reading; data clean in memory; stay shared |
| `SHARED` | `BUS_RDX` | `INVALID` | No | Other cache writing; invalidate our copy |
| `SHARED` | `BUS_UPGR` | `INVALID` | No | Other cache upgrading; invalidate our copy |
| `MODIFIED` | `BUS_RD` | `SHARED` | **Yes** | Other cache reading; flush dirty data; downgrade to shared |
| `MODIFIED` | `BUS_RDX` | `INVALID` | **Yes** | Other cache writing; flush dirty data; invalidate |
| `MODIFIED` | `BUS_UPGR` | `MODIFIED` | No | Protocol violation (cannot be Modified while another is Shared); handled gracefully |

### 5.3 Directory State Transitions (Global View)

These represent how the directory entry for a given address evolves in response to cache requests.

| Dir State | Command Received | From | Next Dir State | Sharers After | Action |
|---|---|---|---|---|---|
| `INVALID` | `BUS_RD` | Any | `SHARED` | `{requester}` | Serve from memory |
| `INVALID` | `BUS_RDX` | Any | `MODIFIED` | `{requester}` | Serve from memory |
| `SHARED` | `BUS_RD` | Any | `SHARED` | `{existing} ∪ {requester}` | Serve from memory |
| `SHARED` | `BUS_RDX` | Any | `MODIFIED` | `{requester}` | Snoop all others with `SNOOP_BUS_RDX`; they invalidate |
| `SHARED` | `BUS_UPGR` | Sharer | `MODIFIED` | `{requester}` | Snoop all others with `SNOOP_BUS_UPGR`; they invalidate |
| `MODIFIED` | `BUS_RD` | Non-owner | `SHARED` | `{owner} ∪ {requester}` | Snoop owner with `SNOOP_BUS_RD`; owner flushes; update memory |
| `MODIFIED` | `BUS_RDX` | Non-owner | `MODIFIED` | `{requester}` | Snoop owner with `SNOOP_BUS_RDX`; owner flushes and invalidates |
| `SHARED` | `EVICT_CLEAN` | Sharer | `SHARED` or `INVALID` | `{existing} \ {requester}` | Remove from sharers; if empty → `INVALID` |
| `MODIFIED` | `EVICT_DIRTY` | Owner | `INVALID` | `{}` | Writeback to memory; remove owner |

---

## 6. Inter-Module Communication

### 6.1 System Initialization

The modules are wired together as follows. The circular dependency (each cache needs the directory; the directory needs each cache) is resolved by registering caches after construction:

```python
directory = DirectoryController(num_cores=2)
cache0 = CacheController(core_id=0, directory_axi_handler=directory.axi_handler)
cache1 = CacheController(core_id=1, directory_axi_handler=directory.axi_handler)

directory.register_cache(0, cache0.axi_handler)
directory.register_cache(1, cache1.axi_handler)
```

### 6.2 CPU → Cache → Directory Flow (Coherence Request)

When the CPU issues a memory operation that requires a coherence transaction:

1. CPU calls `cache.axi_handler(request)` with `mem_instr = False`.
2. Cache calls `on_processor_event` to determine if a coherence command is required.
3. If required, cache calls `_send_dir_cmd`, which constructs an `axi_request` with `mem_instr = True` and a packed command in `mem_wdata`.
4. This request is passed to `directory.axi_handler`.
5. Directory calls `_handle_coherence`, unpacks the command, and executes the appropriate handler.
6. If the handler requires snooping another cache, the directory calls `_send_snoop`.
7. Directory returns data in `mem_rdata`; cache stores it and updates line state.

### 6.3 Directory → Cache Flow (Snoop)

When the directory needs to snoop a cache:

1. Directory calls `_send_snoop(target_core, addr, snoop_cmd, requester)`.
2. This constructs an `axi_request` with `mem_instr = True` and a packed snoop command.
3. The request is delivered to the target cache via `cache_ports[target_core](req)`.
4. Cache's `axi_handler` receives it, sees `mem_instr = True`, and routes to `_handle_snoop`.
5. Cache calls `on_snoop_event`, updates its line state, and returns any flush data in `mem_rdata`.
6. The directory receives the response and uses the returned data as needed (e.g., updating memory, forwarding to requesting cache).

### 6.4 Data Flow Summary

```
CPU Read (miss):
  CPU → cache.axi_handler (mem_instr=False, wstrb=0)
      → _cpu_read → on_processor_event → BUS_RD
      → _send_dir_cmd → directory.axi_handler (mem_instr=True)
      → _bus_rd → memory.get(addr)
      → mem_rdata = data back to cache
      → cache stores data, line → SHARED

CPU Write (Shared hit):
  CPU → cache.axi_handler (mem_instr=False, wstrb≠0)
      → _cpu_write → on_processor_event → BUS_UPGR
      → _send_dir_cmd → directory.axi_handler (mem_instr=True)
      → _bus_upgr → _send_snoop(other, SNOOP_BUS_UPGR)
          → other_cache.axi_handler → _handle_snoop → INVALID
      → directory: sharers = {requester}, state = MODIFIED
      → cache: line → MODIFIED, apply wstrb

Dirty Eviction:
  cache.evict(addr) → line is MODIFIED
      → _send_dir_cmd(EVICT_DIRTY, addr, line.data)
      → directory._evict_dirty → memory[addr] = data
      → directory entry → INVALID
      → cache: line → INVALID
```

---

## 7. Transaction Payload Specification

All coherence messages are carried over `axi_request`. The `mem_wdata` field carries either a packed command word (for coherence) or raw write data (for direct memory access). Below is the complete payload specification per transaction type.

### 7.1 Cache → Directory

| Command | `mem_addr` | `mem_wdata` | `mem_rdata` (response) |
|---|---|---|---|
| `BUS_RD` | Target address | `metadata` (cmd, core_id) | — |
| `BUS_RDX` | Target address | `metadata` (cmd, core_id) | — |
| `BUS_UPGR` | Target address | `metadata` (cmd, core_id) | — |
| `EVICT_CLEAN` | Target address | `metadata` (cmd, core_id) | — |
| `EVICT_DIRTY` | Target address | `metadata + wdata[15:0]` (cmd, core_id, data in payload[31:16]) | — |
| `SNOOP_BUS_RD_Ack` | — | — | `wdata` (flush data via `mem_rdata`) |

### 7.2 Directory → Cache

| Command | `mem_addr` | `mem_wdata` | `mem_rdata` (response) |
|---|---|---|---|
| `SNOOP_BUS_RD` | Target address | `metadata` (cmd, requester core_id) | — |
| `SNOOP_BUS_RDX` | Target address | `metadata` (cmd, requester core_id) | — |
| `SNOOP_BUS_UPGR` | Target address | `metadata` (cmd, requester core_id) | — |
| `BUS_RD_Ack` | — | — | `rdata` |
| `BUS_RDX_Ack` | — | — | `rdata` |
| `BUS_UPGR_Ack` | — | — | (none) |
| `EVICT_CLEAN_Ack` | — | — | (none) |
| `EVICT_DIRTY_Ack` | — | — | (none) |

All acknowledgements are delivered implicitly as the synchronous return of `axi_request` with `mem_ready = True`. Commands carrying `(none)` in `mem_rdata` signal completion through `mem_ready` alone with no data payload.

---

## 8. End-to-End Transaction Walkthroughs

### 8.1 Read Miss (Cold Cache)

**Scenario:** Cache 0 reads address `0x100`; neither cache has it.

1. CPU calls `cache0.axi_handler(addr=0x100, mem_instr=False, wstrb=0)`.
2. `_cpu_read` finds line state = `INVALID`. `on_processor_event` returns `{next=SHARED, cmd=BUS_RD}`.
3. Cache 0 sends `BUS_RD` to directory. Directory sees `entry.state = INVALID`.
4. Directory sets `entry.state = SHARED`, `entry.sharers = 0b01` (core 0).
5. Directory returns `memory[0x100]` (= 0 if never written) in `mem_rdata`.
6. Cache 0 stores data; line transitions to `SHARED`.

### 8.2 Write Miss from Modified Owner (Ownership Transfer)

**Scenario:** Cache 0 owns `0x200` in `MODIFIED`. Cache 1 issues a write miss.

1. Cache 1 CPU writes → `_cpu_write` → line `INVALID` → `on_processor_event` → `BUS_RDX`.
2. Cache 1 sends `BUS_RDX` to directory.
3. Directory sees `entry.state = MODIFIED`, `owner = 0`.
4. Directory calls `_send_snoop(target=0, cmd=SNOOP_BUS_RDX, requester=1)`.
5. Cache 0 receives snoop → `on_snoop_event(MODIFIED, BUS_RDX)` → `{next=INVALID, flush=True}`.
6. Cache 0 returns `line.data` (dirty data) in `mem_rdata`; transitions to `INVALID`.
7. Directory writes flushed data to `memory[0x200]`.
8. Directory sets `entry.state = MODIFIED`, `entry.sharers = 0b10` (core 1 only).
9. Directory returns data to Cache 1.
10. Cache 1 applies write strobe, line transitions to `MODIFIED`.

### 8.3 Upgrade (Shared to Modified)

**Scenario:** Both caches hold `0x300` in `SHARED`. Cache 0 writes.

1. Cache 0 CPU writes → `_cpu_write` → line `SHARED` → `on_processor_event` → `BUS_UPGR`.
2. Cache 0 sends `BUS_UPGR` to directory.
3. Directory sees `entry.state = SHARED`, `sharers = 0b11`.
4. Directory iterates sharers: core 1 ≠ requester → `_send_snoop(target=1, cmd=SNOOP_BUS_UPGR, requester=0)`.
5. Cache 1 receives snoop → `on_snoop_event(SHARED, BUS_UPGR)` → `{next=INVALID, flush=False}`.
6. Cache 1 invalidates; returns 0.
7. Directory sets `entry.state = MODIFIED`, `entry.sharers = 0b01` (core 0 only).
8. No data is transferred back to Cache 0 (it already has valid data).
9. Cache 0 applies write strobe, line transitions to `MODIFIED`.

### 8.4 Dirty Eviction

**Scenario:** Cache 1 needs to evict `0x400` which is in `MODIFIED` state.

1. `cache1.evict(0x400)` detects `line.state = MODIFIED`.
2. Calls `_send_dir_cmd(EVICT_DIRTY, 0x400, line.data)`.
3. Directory receives `EVICT_DIRTY` → `_evict_dirty(requester=1, addr=0x400, data)`.
4. Directory writes data to `memory[0x400]`.
5. Directory calls `_evict_clean`: removes core 1 from sharers; sharers → 0 → state → `INVALID`.
6. Cache 1 sets line state to `INVALID`.

---

## 9. Implementation Notes and Limitations

**Synchronous protocol.** All snoop and directory interactions are synchronous function calls. There is no pipelining, queuing, or split-transaction support. In hardware, these would be asynchronous message-passing events with ordering constraints.

**16-bit payload limitation in `pack_cmd`.** The `payload` field in `pack_cmd` is only 16 bits wide (bits [31:16] of `mem_wdata`). For `EVICT_DIRTY`, only the lower 16 bits of a 32-bit cache word survive encoding. A production implementation would require a separate data channel or an extended encoding for full 32-bit writebacks.

**Write strobe not transmitted with dirty evictions.** In the current implementation, `mem_wstrb` is always `0xF` for coherence traffic from the cache. The write strobe for dirty evictions is not selectively encoded — the directory assumes all bytes are valid. A refined protocol would encode and apply a per-byte strobe during writebacks.

**Snoop acknowledgement is implicit.** There are no explicit `*_Ack` message types in the implementation. Acknowledgements are delivered as the return value of the synchronous `axi_handler` call with `mem_ready = True`. This simplifies the model but diverges from real hardware where acks are separate bus transactions.

**No NACK or stall handling.** If a cache does not acknowledge a snoop (`mem_ready = False`), the directory raises a `RuntimeError`. There is no retry mechanism or timeout.

**Fully-associative cache model.** The cache is implemented as a Python dictionary mapping every address to its own `CacheLine`. There is no capacity limit, set-associativity, or replacement policy. The `evict` method exists for protocol completeness but will not be triggered organically by the current implementation.

**`BUS_UPGR` fallback.** If the directory receives `BUS_UPGR` for a line that is not in `SHARED` state (e.g., due to a race condition or protocol anomaly), it falls back to executing `_bus_rdx` to handle the request safely.

**`MODIFIED + BUS_UPGR` snoop is a protocol violation.** `BUS_UPGR` is only issued from `SHARED` state. If a cache in `MODIFIED` state receives `SNOOP_BUS_UPGR`, it indicates a coherence protocol error. The implementation handles this gracefully by remaining in `MODIFIED` and not flushing, rather than raising an exception.
