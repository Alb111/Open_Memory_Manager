# types
from msi_data_types import (
    CoherenceCmd,
    MSIState,
    ProcessorEvent,
    TransitionResult,
    SnoopEvent,
)


# ============================================================================
# Command Packing/Unpacking
# ============================================================================

def pack_cmd(cmd: CoherenceCmd, core_id: int, payload: int = 0) -> int:
    """
    Pack a coherence command into a 32-bit word for transmission.
    
    Used when sending coherence commands via AXI (stored in mem_wdata).
    
    Bit Layout:
        [31:16] - payload (16 bits): Optional data (e.g., writeback data for evict)
        [15:8]  - core_id (8 bits): Requesting/snooping cache ID (0 or 1)
        [7:0]   - cmd (8 bits): CoherenceCmd value
    
    Args:
        cmd: Coherence command to pack
        core_id: ID of the cache issuing the command (0 or 1)
        payload: Optional 16-bit payload (e.g., for writeback data reference)
    
    Returns:
        Packed 32-bit integer suitable for mem_wdata field
    
    Example:
        # Cache 0 issues BusRd
        packed = pack_cmd(CoherenceCmd.BUS_RD, core_id=0)
        # Result: 0x00000001
        
        # Cache 1 evicts dirty line with data at address 0x1234
        packed = pack_cmd(CoherenceCmd.EVICT_DIRTY, core_id=1, payload=0x1234)
        # Result: 0x12340105
    """
    return (payload << 16) | ((core_id & 0xFF) << 8) | (int(cmd) & 0xFF)


def unpack_cmd(word: int) -> tuple[int, int, int]:
    """
    Unpack a coherence command from a 32-bit word.
    
    Reverses pack_cmd() to extract command, core ID, and payload.
    
    Args:
        word: Packed 32-bit command word (from mem_wdata)
    
    Returns:
        Tuple of (cmd, core_id, payload):
            cmd: CoherenceCmd value (as int)
            core_id: Cache ID (0 or 1)
            payload: Optional payload data
    
    Example:
        cmd, core_id, payload = unpack_cmd(0x12340105)
        # cmd = 5 (EVICT_DIRTY)
        # core_id = 1
        # payload = 0x1234
    """
    cmd = word & 0xFF              # Extract bits [7:0]
    core_id = (word >> 8) & 0xFF   # Extract bits [15:8]
    payload = word >> 16           # Extract bits [31:16]
    return cmd, core_id, payload


# ============================================================================
# MSI State Machine - Processor Events
# ============================================================================

def on_processor_event(state: MSIState, event: ProcessorEvent) -> TransitionResult:
    """
    MSI state transition for processor-initiated events (CPU operations).
    
    This function implements the core MSI protocol logic for CPU reads and writes.
    It determines:
    1. What the new cache state should be
    2. Whether a bus transaction needs to be issued to the directory
    
    State Transition Table:
    
    Current State | Event  | Next State | Bus Transaction | Notes
    --------------|--------|------------|-----------------|---------------------------
    INVALID       | PR_RD  | SHARED     | BUS_RD          | Read miss, fetch from memory
    INVALID       | PR_WR  | MODIFIED   | BUS_RDX         | Write miss, get exclusive
    SHARED        | PR_RD  | SHARED     | None            | Read hit, no action needed
    SHARED        | PR_WR  | MODIFIED   | BUS_UPGR        | Upgrade to exclusive, invalidate others
    MODIFIED      | PR_RD  | MODIFIED   | None            | Read hit, data already exclusive
    MODIFIED      | PR_WR  | MODIFIED   | None            | Write hit, data already exclusive
    
    Args:
        state: Current MSI state of the cache line
        event: Processor event (PR_RD or PR_WR)
    
    Returns:
        TransitionResult with next_state and optional issue_cmd
    
    Example Usage (in CacheController):
        line = self._line(addr)
        tr = on_processor_event(line.state, ProcessorEvent.PR_RD)
        
        # If command needs to be issued, send to directory
        if tr.issue_cmd is not None:
            line.data = self._send_dir_cmd(tr.issue_cmd, addr)
        
        # Update cache line state
        line.state = tr.next_state
    """
    
    # ---- INVALID State ----
    # Cache line not present - must fetch from memory/directory
    if state == MSIState.INVALID:
        if event == ProcessorEvent.PR_RD:
            # Read miss: Fetch data and transition to SHARED
            # Issue BUS_RD to directory to get data
            return TransitionResult(MSIState.SHARED, CoherenceCmd.BUS_RD, False)
        else:  # PR_WR
            # Write miss: Fetch data and transition to MODIFIED (exclusive)
            # Issue BUS_RDX to directory to get data and invalidate others
            return TransitionResult(MSIState.MODIFIED, CoherenceCmd.BUS_RDX, False)
    
    # ---- SHARED State ----
    # Cache line present in read-only form
    if state == MSIState.SHARED:
        if event == ProcessorEvent.PR_RD:
            # Read hit: Data already present, no action needed
            return TransitionResult(MSIState.SHARED, None, False)
        else:  # PR_WR
            # Write upgrade: Already have data, just need exclusive access
            # Issue BUS_UPGR to invalidate other sharers (no data transfer)
            return TransitionResult(MSIState.MODIFIED, CoherenceCmd.BUS_UPGR, False)
    
    # ---- MODIFIED State ----
    # Cache line present in exclusive/dirty form
    if state == MSIState.MODIFIED:
        # Both reads and writes hit - data is already exclusive
        # No bus transaction needed for either operation
        return TransitionResult(MSIState.MODIFIED, None, False)
    
    # Should never reach here if state is valid
    raise ValueError("invalid MSI state")


# ============================================================================
# MSI State Machine - Snoop Events
# ============================================================================

def on_snoop_event(state: MSIState, event: SnoopEvent) -> TransitionResult:
    """
    MSI state transition for snoop events (coherence messages from directory).
    
    This function implements how a cache responds to coherence operations
    initiated by OTHER caches. The directory sends snoop commands when another
    cache needs to:
    - Read data (BUS_RD) - may need to share
    - Write data (BUS_RDX) - must invalidate
    - Upgrade to exclusive (BUS_UPGR) - must invalidate
    
    State Transition Table:
    
    Current State | Snoop Event | Next State | Flush Data? | Notes
    --------------|-------------|------------|-------------|---------------------------
    INVALID       | Any         | INVALID    | No          | No copy, ignore snoop
    SHARED        | BUS_RD      | SHARED     | No          | Other cache reading, stay shared
    SHARED        | BUS_RDX     | INVALID    | No          | Other cache writing, invalidate
    SHARED        | BUS_UPGR    | INVALID    | No          | Other cache upgrading, invalidate
    MODIFIED      | BUS_RD      | SHARED     | Yes         | Other cache reading, share data
    MODIFIED      | BUS_RDX     | INVALID    | Yes         | Other cache writing, flush & invalidate
    MODIFIED      | BUS_UPGR    | MODIFIED   | No          | Can't happen (would be SHARED)
    
    Args:
        state: Current MSI state of the cache line
        event: Snoop event (BUS_RD, BUS_RDX, or BUS_UPGR)
    
    Returns:
        TransitionResult with next_state and flush flag
        - flush=True means cache must provide data (send back in mem_rdata)
    
    Example Usage (in CacheController):
        line = self._line(addr)
        tr = on_snoop_event(line.state, SnoopEvent.BUS_RD)
        
        # If flush requested, include data in response
        flush_data = line.data if tr.flush else 0
        
        # Update state
        line.state = tr.next_state
        
        # Return flush data to directory
        return flush_data
    """
    
    # ---- INVALID State ----
    # No copy of this line - ignore all snoops
    if state == MSIState.INVALID:
        # Cache doesn't have this line, no action needed
        return TransitionResult(MSIState.INVALID, None, False)
    
    # ---- SHARED State ----
    # Read-only copy - may need to invalidate
    if state == MSIState.SHARED:
        if event == SnoopEvent.BUS_RD:
            # Another cache reading: stay SHARED (data is clean in memory)
            # No flush needed - data will come from memory
            return TransitionResult(MSIState.SHARED, None, False)
        else:  # BUS_RDX or BUS_UPGR
            # Another cache writing/upgrading: must invalidate our copy
            # No flush needed - data is clean (SHARED is read-only)
            return TransitionResult(MSIState.INVALID, None, False)
    
    # ---- MODIFIED State ----
    # Exclusive/dirty copy - may need to flush and downgrade/invalidate
    if state == MSIState.MODIFIED:
        if event == SnoopEvent.BUS_RD:
            # Another cache reading: must share
            # Flush dirty data, downgrade to SHARED
            # Directory will update memory and send data to requester
            return TransitionResult(MSIState.SHARED, None, True)
        
        if event == SnoopEvent.BUS_RDX:
            # Another cache writing: must invalidate
            # Flush dirty data and transition to INVALID
            # Directory will send data to new owner
            return TransitionResult(MSIState.INVALID, None, True)
        
        # BUS_UPGR while MODIFIED shouldn't happen in MSI protocol
        # BusUpgr is only issued from SHARED state, and only one cache
        # can be MODIFIED at a time. If we're MODIFIED, others must be INVALID.
        # This is a protocol violation, but we handle it gracefully by staying MODIFIED
        return TransitionResult(MSIState.MODIFIED, None, False)
    
    # Should never reach here if state is valid
    raise ValueError("invalid MSI state")
