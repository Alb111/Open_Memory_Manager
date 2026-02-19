"""
Directory Controller Module for MSI Cache Coherence Protocol

This module implements the central directory controller that coordinates cache
coherence across multiple caches. The directory tracks which caches have copies
of each memory block and in what state, then enforces the MSI protocol invariants.

Architecture:
    Cache 0 ─┐
             ├──→ DirectoryController ──→ Memory
    Cache 1 ─┘

Key Responsibilities:
1. Track cache line ownership and sharing (directory state)
2. Handle coherence requests from caches (BUS_RD, BUS_RDX, BUS_UPGR)
3. Send snoop messages to caches to maintain coherence
4. Manage memory reads/writes
5. Handle cache evictions (clean and dirty)

Directory State Per Address:
    - MSI State: INVALID, SHARED, or MODIFIED
    - Sharers Bitmask: Which caches have copies (bit per cache)

Integration Points:
- Receives coherence commands from CacheControllers (mem_instr=True)
- Sends snoop messages to CacheControllers via registered ports
- Handles normal memory traffic (mem_instr=False)

Author: Rishi & Nick
Date: 2/8/25
"""

from dataclasses import dataclass
from typing import Callable, Dict, Optional

from msi import (
    MSIState,
    CoherenceCmd,
    axi_request,
    pack_cmd,
    unpack_cmd,
)


# ============================================================================
# Utility Functions
# ============================================================================

def apply_wstrb(old_value: int, new_value: int, wstrb: int) -> int:
    """
    Apply byte-level write strobe to merge new data with old data.
    
    Identical to the function in cache_controller.py - enables byte-granular
    writes to memory.
    
    Args:
        old_value: Existing 32-bit value in memory
        new_value: New 32-bit value from write request
        wstrb: Write strobe mask (4 bits for 4 bytes)
    
    Returns:
        Merged 32-bit value
    
    Example:
        old = 0x12345678
        new = 0xAABBCCDD
        wstrb = 0b1010 (update bytes 1 and 3)
        result = 0xAA34CC78
                  ^^  ^^
                  |   └── Byte 3 updated
                  └────── Byte 1 updated
    """
    result = old_value
    for i in range(4):
        if (wstrb >> i) & 1:
            byte_mask = 0xFF << (8 * i)
            result = (result & ~byte_mask) | (new_value & byte_mask)
    return result


# ============================================================================
# Directory Entry
# ============================================================================

@dataclass
class DirectoryEntry:
    """
    Directory state for a single memory address.
    
    The directory maintains coherence by tracking:
    1. What state the line is in globally (INVALID, SHARED, or MODIFIED)
    2. Which caches have copies (sharers bitmask)
    
    Fields:
        state: Global MSI state for this address
               - INVALID: No cache has a copy
               - SHARED: One or more caches have read-only copies
               - MODIFIED: Exactly one cache has exclusive/dirty copy
        
        sharers: Bitmask indicating which caches have copies
                 Bit 0 = cache 0, Bit 1 = cache 1, etc.
                 Example: 0b11 = both cache 0 and 1 have copies
                          0b01 = only cache 0 has copy
    
    Encoding Efficiency:
        For 2 cores: 2 bits (state) + 2 bits (sharers) = 4 bits total per line
        Very compact directory representation!
    
    Example States:
        DirectoryEntry(INVALID, 0b00): No cache has copy
        DirectoryEntry(SHARED, 0b01): Cache 0 has shared copy
        DirectoryEntry(SHARED, 0b11): Both caches have shared copies
        DirectoryEntry(MODIFIED, 0b10): Cache 1 has exclusive/dirty copy
    """
    state: MSIState = MSIState.INVALID  # Global state
    sharers: int = 0                    # Bitmask of caches with copies

    def owner(self) -> Optional[int]:
        """
        Get the owner cache ID if this line is in MODIFIED state.
        
        In MODIFIED state, exactly one cache should have the line.
        This function extracts which cache owns it.
        
        Returns:
            Cache ID (0, 1, ...) if MODIFIED with single owner
            None if not MODIFIED, no sharers, or multiple sharers (error)
        
        Algorithm:
            1. Check if state is MODIFIED (only relevant for MODIFIED)
            2. Check if sharers != 0 (must have an owner)
            3. Check if only one bit is set (sharers & (sharers-1) == 0)
            4. Return which bit is set (bit_length() - 1)
        
        Example:
            sharers = 0b0001 → owner() = 0 (cache 0)
            sharers = 0b0010 → owner() = 1 (cache 1)
            sharers = 0b0011 → owner() = None (multiple sharers, invalid)
            sharers = 0b0000 → owner() = None (no sharers)
        
        Bit Tricks:
            - sharers & (sharers-1): Clear lowest set bit
              If result is 0, only one bit was set (power of 2)
            - bit_length() - 1: Get position of highest set bit
              0b0001.bit_length() = 1 → owner = 0
              0b0010.bit_length() = 2 → owner = 1
        """
        # Only MODIFIED state has an owner
        if self.state != MSIState.MODIFIED:
            return None
        
        # Must have at least one sharer
        if self.sharers == 0:
            return None
        
        # Must have exactly one sharer (power of 2 check)
        if self.sharers & (self.sharers - 1):
            return None  # Multiple bits set
        
        # Return which bit is set (cache ID)
        return self.sharers.bit_length() - 1


# ============================================================================
# Directory Controller
# ============================================================================

class DirectoryController:
    """
    Central directory controller for MSI cache coherence.
    
    The directory is the "home node" for all memory addresses. It:
    1. Maintains directory entries tracking cache states
    2. Stores memory data
    3. Coordinates coherence by sending snoops to caches
    4. Responds to coherence requests from caches
    
    Communication Protocol:
        mem_instr = False: Normal memory read/write
        mem_instr = True: Coherence command (BUS_RD, BUS_RDX, etc.)
    
    Attributes:
        num_cores: Number of caches in the system
        entries: Directory state (address → DirectoryEntry)
        memory: Main memory storage (address → data)
        cache_ports: Cache AXI handlers (cache_id → axi_handler function)
    """

    def __init__(self, num_cores: int = 2):
        """
        Initialize directory controller.
        
        Args:
            num_cores: Number of caches/cores in the system (default 2)
        
        Example:
            dir_controller = DirectoryController(num_cores=2)
            
            # Register caches
            dir_controller.register_cache(0, cache0.axi_handler)
            dir_controller.register_cache(1, cache1.axi_handler)
        """
        self.num_cores = num_cores
        
        # Directory state: lazy allocation (created on first access)
        self.entries: Dict[int, DirectoryEntry] = {}
        
        # Main memory storage
        self.memory: Dict[int, int] = {}

        # Cache communication ports
        # Maps cache_id → cache's axi_handler function
        self.cache_ports: Dict[int, Callable[[axi_request], axi_request]] = {}

    def register_cache(self, core_id: int, cache_axi_handler: Callable[[axi_request], axi_request]) -> None:
        """
        Register a cache controller's AXI handler for snoop communication.
        
        The directory needs to be able to send snoop messages to caches.
        This function registers each cache's handler so the directory can
        call it directly when snoops are needed.
        
        Args:
            core_id: Cache identifier (0, 1, ...)
            cache_axi_handler: Cache's axi_handler function
        
        Example System Setup:
            directory = DirectoryController(num_cores=2)
            cache0 = CacheController(core_id=0, directory.axi_handler)
            cache1 = CacheController(core_id=1, directory.axi_handler)
            
            # Register caches with directory
            directory.register_cache(0, cache0.axi_handler)
            directory.register_cache(1, cache1.axi_handler)
            
            # Now directory can send snoops:
            # directory._send_snoop(target_core=1, ...)
        """
        self.cache_ports[core_id] = cache_axi_handler

    @staticmethod
    def bits_per_line(num_cores: int = 2) -> int:
        """
        Calculate directory storage overhead per cache line.
        
        Directory needs to track:
        - State: 2 bits (INVALID=0, SHARED=1, MODIFIED=2)
        - Sharers: 1 bit per core
        
        Args:
            num_cores: Number of caches in system
        
        Returns:
            Total bits needed per directory entry
        
        Example:
            2 cores: 2 (state) + 2 (sharers) = 4 bits/line
            4 cores: 2 (state) + 4 (sharers) = 6 bits/line
            8 cores: 2 (state) + 8 (sharers) = 10 bits/line
        
        Hardware Impact:
            For 1MB of memory (256K lines of 4 bytes):
            - 2 cores: 256K * 4 bits = 128 KB directory overhead
            - 4 cores: 256K * 6 bits = 192 KB directory overhead
        """
        return 2 + num_cores  # 2 bits for state + num_cores bits for sharers

    def _entry(self, addr: int) -> DirectoryEntry:
        """
        Get directory entry for an address, creating if necessary.
        
        Lazy allocation: entries are created on first access to an address.
        New entries start in INVALID state with no sharers.
        
        Args:
            addr: Memory address
        
        Returns:
            DirectoryEntry for this address
        """
        if addr not in self.entries:
            self.entries[addr] = DirectoryEntry()
        return self.entries[addr]

    def _send_snoop(self, target_core: int, addr: int, snoop_cmd: CoherenceCmd, requester: int) -> int:
        """
        Send a snoop message to a specific cache.
        
        This is how the directory communicates coherence actions to caches.
        When one cache needs data or exclusive access, the directory snoops
        other caches that have copies.
        
        Args:
            target_core: Which cache to snoop (cache ID)
            addr: Memory address being snooped
            snoop_cmd: Type of snoop (SNOOP_BUS_RD, SNOOP_BUS_RDX, SNOOP_BUS_UPGR)
            requester: Which cache initiated the original request
        
        Returns:
            Flushed data from target cache (if it had dirty data)
            Otherwise returns 0
        
        Raises:
            RuntimeError: If target cache doesn't acknowledge snoop
        
        Snoop Flow Example:
            1. Cache 0 issues BUS_RD for address X
            2. Directory sees Cache 1 has X in MODIFIED state
            3. Directory calls: _send_snoop(target_core=1, addr=X, 
                                           cmd=SNOOP_BUS_RD, requester=0)
            4. Cache 1 receives snoop, returns dirty data
            5. Directory updates memory with flushed data
            6. Directory sends data to Cache 0
        
        Synchronous Protocol:
            This implementation is synchronous - the snoop completes immediately.
            In real hardware, this might be pipelined or split-transaction.
        """
        # Get target cache's AXI handler
        port = self.cache_ports[target_core]
        
        # Build snoop request
        req = axi_request(
            mem_valid=True,
            mem_instr=True,  # This is coherence traffic
            mem_addr=addr,
            mem_wdata=pack_cmd(snoop_cmd, requester),
            mem_wstrb=0xF,
        )
        
        # Send snoop to cache (synchronous call)
        resp = port(req)
        
        # Verify cache acknowledged
        if not resp.mem_ready:
            raise RuntimeError(f"snoop not acknowledged by core {target_core}")
        
        # Return any flushed data
        return resp.mem_rdata

    def _bus_rd(self, requester: int, addr: int) -> int:
        """
        Handle BUS_RD request (read miss from a cache).
        
        A cache issues BUS_RD when:
        - Cache line is INVALID (read miss)
        - Cache needs to fetch data
        
        Directory Action:
        - Provides data (from memory or owner cache)
        - Adds requester to sharers
        - Updates state to SHARED
        
        Args:
            requester: Cache ID issuing the request
            addr: Memory address to read
        
        Returns:
            Data value (from memory or owner cache)
        
        State Transitions:
        
        Case 1: Entry is INVALID (no cache has it)
            - Fetch data from memory
            - State: INVALID → SHARED
            - Sharers: 0 → requester bit set
        
        Case 2: Entry is SHARED (one or more caches have read-only copies)
            - Fetch data from memory (data is clean)
            - State: SHARED → SHARED (no change)
            - Sharers: Add requester bit
        
        Case 3: Entry is MODIFIED (one cache has exclusive/dirty copy)
            - Snoop owner cache to get dirty data
            - Owner flushes data and downgrades to SHARED
            - Update memory with flushed data
            - State: MODIFIED → SHARED
            - Sharers: Add both owner and requester
        
        Example Flow (Case 3 - most complex):
            Initial: Cache 0 has addr X in MODIFIED, sharers=0b01
            1. Cache 1 issues BUS_RD for addr X
            2. _bus_rd(requester=1, addr=X) called
            3. Directory sees state=MODIFIED, owner=0
            4. Directory snoops Cache 0 with SNOOP_BUS_RD
            5. Cache 0 returns dirty data and transitions to SHARED
            6. Directory updates memory[X] with flushed data
            7. Directory sets state=SHARED, sharers=0b11
            8. Return data to Cache 1
        """
        entry = self._entry(addr)

        # Case 1: INVALID - no cache has it
        if entry.state == MSIState.INVALID:
            # Fetch from memory (or default to 0 if never written)
            entry.state = MSIState.SHARED
            entry.sharers = 1 << requester  # Set requester bit
            return self.memory.get(addr, 0)

        # Case 2: SHARED - one or more caches have clean copies
        if entry.state == MSIState.SHARED:
            # Add requester to sharers
            entry.sharers |= 1 << requester
            # Data is clean in memory
            return self.memory.get(addr, 0)

        # Case 3: MODIFIED - one cache has dirty copy
        # Get owner cache ID
        owner = entry.owner()
        
        # If there's a valid owner and it's not the requester
        if owner is not None and owner != requester:
            # Snoop owner to get dirty data
            flushed = self._send_snoop(owner, addr, CoherenceCmd.SNOOP_BUS_RD, requester)
            
            # Update memory with flushed data
            self.memory[addr] = flushed
            
            # Keep owner in sharers (it downgrades to SHARED)
            entry.sharers |= 1 << owner

        # Transition to SHARED state
        entry.state = MSIState.SHARED
        
        # Add requester to sharers
        entry.sharers |= 1 << requester
        
        # Return data (now clean in memory)
        return self.memory.get(addr, 0)

    def _bus_rdx(self, requester: int, addr: int) -> int:
        """
        Handle BUS_RDX request (write miss from a cache).
        
        A cache issues BUS_RDX when:
        - Cache line is INVALID (write miss)
        - Cache needs data AND exclusive access
        
        Directory Action:
        - Provides data
        - Invalidates all other copies
        - Grants exclusive access to requester
        - Updates state to MODIFIED
        
        Args:
            requester: Cache ID issuing the request
            addr: Memory address to write
        
        Returns:
            Data value (from memory or owner cache)
        
        State Transitions:
        
        Case 1: Entry is INVALID
            - Fetch data from memory
            - State: INVALID → MODIFIED
            - Sharers: 0 → requester only
        
        Case 2: Entry is SHARED (one or more sharers)
            - Snoop all sharers except requester with SNOOP_BUS_RDX
            - All sharers invalidate their copies
            - Fetch data from memory (clean)
            - State: SHARED → MODIFIED
            - Sharers: All → requester only
        
        Case 3: Entry is MODIFIED (one cache has exclusive copy)
            - Snoop owner with SNOOP_BUS_RDX
            - Owner flushes data and invalidates
            - Update memory
            - State: MODIFIED → MODIFIED (ownership transfer)
            - Sharers: Old owner → requester
        
        Example Flow (Case 2):
            Initial: sharers=0b11 (Cache 0 and 1 both have SHARED)
            1. Cache 0 issues BUS_RDX for addr X (wants to write)
            2. _bus_rdx(requester=0, addr=X) called
            3. Directory snoops Cache 1 with SNOOP_BUS_RDX
            4. Cache 1 invalidates its copy
            5. Directory sets state=MODIFIED, sharers=0b01 (only Cache 0)
            6. Return data to Cache 0
        """
        entry = self._entry(addr)
        data = self.memory.get(addr, 0)

        # Case 1: INVALID - no cache has it
        if entry.state == MSIState.INVALID:
            # Grant exclusive access
            entry.state = MSIState.MODIFIED
            entry.sharers = 1 << requester
            return data

        # Case 2: SHARED - invalidate all other sharers
        if entry.state == MSIState.SHARED:
            # Snoop all sharers except requester
            for c in range(self.num_cores):
                if c != requester and ((entry.sharers >> c) & 1):
                    # Send invalidation
                    _ = self._send_snoop(c, addr, CoherenceCmd.SNOOP_BUS_RDX, requester)
            
            # Grant exclusive access
            entry.state = MSIState.MODIFIED
            entry.sharers = 1 << requester
            return data

        # Case 3: MODIFIED - transfer ownership
        owner = entry.owner()
        if owner is not None and owner != requester:
            # Get dirty data from owner
            flushed = self._send_snoop(owner, addr, CoherenceCmd.SNOOP_BUS_RDX, requester)
            
            # Update memory
            self.memory[addr] = flushed
            data = flushed

        # Grant exclusive access to requester
        entry.state = MSIState.MODIFIED
        entry.sharers = 1 << requester
        return data

    def _bus_upgr(self, requester: int, addr: int) -> int:
        """
        Handle BUS_UPGR request (upgrade from SHARED to MODIFIED).
        
        A cache issues BUS_UPGR when:
        - Cache line is SHARED (already has data)
        - CPU writes to the line
        - Cache needs exclusive access but ALREADY has the data
        
        Difference from BUS_RDX:
        - BUS_RDX: Need data + exclusive (cache miss on write)
        - BUS_UPGR: Already have data, just need exclusive (cache hit on write)
        
        Directory Action:
        - Invalidates all other sharers (not requester)
        - No data transfer needed (requester already has it)
        - Updates state to MODIFIED
        
        Args:
            requester: Cache ID issuing the request
            addr: Memory address being upgraded
        
        Returns:
            Data value from memory (for consistency, though requester has it)
        
        State Transition:
            Initial: state=SHARED, sharers includes requester
            1. Snoop all other sharers with SNOOP_BUS_UPGR
            2. Other sharers invalidate
            3. State: SHARED → MODIFIED
            4. Sharers: Multiple → requester only
        
        Optimization:
            BUS_UPGR doesn't transfer data - more efficient than BUS_RDX
            when cache already has a SHARED copy.
        
        Fallback:
            If state is not SHARED (e.g., INVALID), fall back to BUS_RDX
            to handle the request properly.
        
        Example:
            Initial: Cache 0 and 1 both have addr X in SHARED
            1. Cache 0 CPU writes to addr X
            2. Cache 0 issues BUS_UPGR
            3. Directory snoops Cache 1 with SNOOP_BUS_UPGR
            4. Cache 1 invalidates
            5. Cache 0 now has exclusive access (MODIFIED)
            6. Cache 0 performs write locally
        """
        entry = self._entry(addr)

        # Normal case: state is SHARED
        if entry.state == MSIState.SHARED:
            # Invalidate all other sharers
            for c in range(self.num_cores):
                if c != requester and ((entry.sharers >> c) & 1):
                    _ = self._send_snoop(c, addr, CoherenceCmd.SNOOP_BUS_UPGR, requester)
            
            # Grant exclusive access
            entry.state = MSIState.MODIFIED
            entry.sharers = 1 << requester
            return self.memory.get(addr, 0)

        # Fallback: if not SHARED, treat as BUS_RDX
        # This handles edge cases (e.g., race conditions, protocol violations)
        return self._bus_rdx(requester, addr)

    def _evict_clean(self, requester: int, addr: int) -> None:
        """
        Handle clean eviction (evicting a SHARED line).
        
        A cache issues EVICT_CLEAN when:
        - Evicting a line in SHARED state
        - No writeback needed (data is clean)
        
        Directory Action:
        - Remove cache from sharers list
        - If no more sharers, transition to INVALID
        - If MODIFIED and multiple sharers (error), downgrade to SHARED
        
        Args:
            requester: Cache ID evicting the line
            addr: Memory address being evicted
        
        State Transitions:
            Case 1: SHARED with multiple sharers
                sharers=0b11 → remove requester → sharers=0b10 or 0b01
                State remains SHARED
            
            Case 2: SHARED with only this sharer
                sharers=0b01 → remove requester → sharers=0b00
                State: SHARED → INVALID (no copies left)
            
            Case 3: MODIFIED (error recovery)
                If somehow multiple sharers in MODIFIED state
                Remove requester, downgrade to SHARED if owner is now unclear
        
        Note:
            No data is transferred - this is a clean eviction.
        """
        entry = self._entry(addr)
        
        # Remove requester from sharers
        entry.sharers &= ~(1 << requester)
        
        # If no sharers left, transition to INVALID
        if entry.sharers == 0:
            entry.state = MSIState.INVALID
        # Error recovery: MODIFIED but no valid single owner
        elif entry.state == MSIState.MODIFIED and entry.owner() is None:
            entry.state = MSIState.SHARED

    def _evict_dirty(self, requester: int, addr: int, data: int) -> None:
        """
        Handle dirty eviction (evicting a MODIFIED line).
        
        A cache issues EVICT_DIRTY when:
        - Evicting a line in MODIFIED state
        - Line has dirty data that must be written back
        
        Directory Action:
        - Write back data to memory
        - Remove cache from sharers
        - Update directory state appropriately
        
        Args:
            requester: Cache ID evicting the line
            addr: Memory address being evicted
            data: Dirty data to write back
        
        State Transition:
            Initial: state=MODIFIED, sharers=requester only
            1. Write data to memory
            2. Remove requester from sharers
            3. State: MODIFIED → INVALID (no owners left)
        
        Writeback Flow:
            Cache → EVICT_DIRTY(data) → Directory → memory[addr] = data
        
        Important:
            This is the only way modified data gets written back to memory
            in MSI protocol (besides snoops that flush data).
        """
        # Write back dirty data to memory
        self.memory[addr] = data
        
        # Clean up directory entry
        self._evict_clean(requester, addr)

    def _handle_coherence(self, addr: int, packed_cmd: int) -> int:
        """
        Dispatch coherence commands to appropriate handlers.
        
        This is the main dispatcher for all coherence protocol commands
        received from caches. It unpacks the command and routes to the
        appropriate handler.
        
        Args:
            addr: Memory address
            packed_cmd: Packed coherence command from cache
        
        Returns:
            Response data (relevant for BUS_RD, BUS_RDX, BUS_UPGR)
        
        Command Routing:
            BUS_RD → _bus_rd()
            BUS_RDX → _bus_rdx()
            BUS_UPGR → _bus_upgr()
            EVICT_CLEAN → _evict_clean()
            EVICT_DIRTY → _evict_dirty()
        
        Raises:
            ValueError: If command is not recognized
        """
        # Unpack command
        cmd, requester, payload = unpack_cmd(packed_cmd)

        # Route to appropriate handler
        if cmd == int(CoherenceCmd.BUS_RD):
            return self._bus_rd(requester, addr)
        
        if cmd == int(CoherenceCmd.BUS_RDX):
            return self._bus_rdx(requester, addr)
        
        if cmd == int(CoherenceCmd.BUS_UPGR):
            return self._bus_upgr(requester, addr)
        
        if cmd == int(CoherenceCmd.EVICT_CLEAN):
            self._evict_clean(requester, addr)
            return 0
        
        if cmd == int(CoherenceCmd.EVICT_DIRTY):
            self._evict_dirty(requester, addr, payload)
            return 0

        # Unknown command
        raise ValueError(f"unknown coherence cmd {cmd}")

    def axi_handler(self, request: axi_request) -> axi_request:
        """
        Main AXI request handler for directory controller.
        
        Routes requests based on mem_instr flag:
        - mem_instr=True: Coherence traffic (BUS_RD, evictions, etc.)
        - mem_instr=False: Normal memory read/write
        
        Args:
            request: AXI request from cache or CPU
        
        Returns:
            AXI response with data and mem_ready=True
        
        Request Types:
        
        1. Coherence Request (mem_instr=True):
           - From cache controller
           - mem_wdata contains packed coherence command
           - Routes to _handle_coherence()
           - Returns data for BUS_RD/BUS_RDX/BUS_UPGR
        
        2. Memory Read (mem_instr=False, wstrb=0):
           - Direct memory access (bypasses coherence)
           - Returns data from memory
           - Use case: DMA, I/O, or system initialization
        
        3. Memory Write (mem_instr=False, wstrb!=0):
           - Direct memory access (bypasses coherence)
           - Merges data using write strobe
           - Returns final memory value
           - Use case: DMA, I/O, or system initialization
        
        Note on Direct Memory Access:
            Normal CPU traffic goes through caches, not directly here.
            Direct memory access (mem_instr=False) might be used by:
            - DMA engines
            - I/O devices
            - System initialization before caches are enabled
            
            In a real system, you'd need to ensure coherence between
            DMA and cached data (flush caches before DMA, etc.)
        """
        # Ignore invalid requests
        if not request.mem_valid:
            request.mem_ready = False
            return request

        # Route based on traffic type
        if request.mem_instr:
            # Coherence command from cache
            request.mem_rdata = self._handle_coherence(request.mem_addr, request.mem_wdata)
            request.mem_ready = True
            return request

        # Direct memory access (non-coherent)
        if request.mem_wstrb == 0:
            # Memory read
            request.mem_rdata = self.memory.get(request.mem_addr, 0)
        else:
            # Memory write (with byte-level granularity)
            old_value = self.memory.get(request.mem_addr, 0)
            self.memory[request.mem_addr] = apply_wstrb(
                old_value,
                request.mem_wdata,
                request.mem_wstrb
            )
            request.mem_rdata = self.memory[request.mem_addr]

        request.mem_ready = True
        return request
