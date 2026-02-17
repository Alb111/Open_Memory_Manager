from enum import IntEnum
from dataclasses import dataclass
from typing import Optional



class MSIState(IntEnum):
    """
    MSI cache coherence states of a cache line
    
    State Meanings:
    - INVALID: Cache line not present or invalidated (no copy exists)
    - SHARED: Read-only copy, may be shared with other caches
    - MODIFIED: Exclusive, dirty copy (must write back on eviction)
    
    State Invariants:
    1. At most one cache can be in MODIFIED for any address
    2. If one cache is MODIFIED, all others must be INVALID
    3. Multiple caches can be SHARED simultaneously
    """

    INVALID = 0   # No valid copy in this cache
    SHARED = 1    # Read-only copy (clean)
    MODIFIED = 2  # Read-write copy (dirty)


class ProcessorEvent(IntEnum):
    """
    Processor-initiated events (CPU → Cache).
    
    These represent CPU memory operations that trigger cache state transitions.
    
    PR_RD: Processor Read
        - CPU wants to read from this address
        - May cause cache miss (state transition)
    
    PR_WR: Processor Write
        - CPU wants to write to this address
        - May require exclusive access (upgrade or miss)
    """

    PR_RD = 0  # Processor read request
    PR_WR = 1  # Processor write request


class SnoopEvent(IntEnum):
    """
    Snoop events (Directory → Cache via snoop messages).
    
    These represent coherence operations from other caches that this cache
    must respond to. Snoops are triggered by the directory when another
    cache issues a bus transaction.
    
    BUS_RD: Another cache is reading (BusRd transaction)
        - This cache may need to share if in MODIFIED state
    
    BUS_RDX: Another cache is writing (BusRdX transaction)
        - This cache must invalidate and possibly flush dirty data
    
    BUS_UPGR: Another cache is upgrading from SHARED to MODIFIED
        - This cache must invalidate (no flush needed - data already shared)
    """

    BUS_RD = 0     # Another cache issued BusRd (read miss)
    BUS_RDX = 1    # Another cache issued BusRdX (write miss)
    BUS_UPGR = 2   # Another cache issued BusUpgr (write hit in Shared)


class CoherenceCmd(IntEnum):
    """
    Coherence command types for cache-directory communication.
    
    Commands are divided into two categories:
    
    1. Cache → Directory (bus transactions):
       - BUS_RD: Read miss, need data
       - BUS_RDX: Write miss, need exclusive access
       - BUS_UPGR: Upgrade from SHARED to MODIFIED (already have data)
       - EVICT_CLEAN: Evicting SHARED line (no writeback needed)
       - EVICT_DIRTY: Evicting MODIFIED line (writeback included)
    
    2. Directory → Cache (snoop commands):
       - SNOOP_BUS_RD: Another cache is reading, share if MODIFIED
       - SNOOP_BUS_RDX: Another cache is writing, invalidate and flush if MODIFIED
       - SNOOP_BUS_UPGR: Another cache is upgrading, invalidate
    
    Note: Values are chosen to avoid conflicts (snoops start at 17)
    """
    # Cache-to-Directory commands (values 1-5)
    BUS_RD = 1        # Read request (cache miss on read)
    BUS_RDX = 2       # Read-exclusive request (cache miss on write)
    BUS_UPGR = 3      # Upgrade request (cache hit on write in SHARED state)
    EVICT_CLEAN = 4   # Evict SHARED line (no data)
    EVICT_DIRTY = 5   # Evict MODIFIED line (includes writeback data)
    
    # Directory-to-Cache commands (values 17-19, offset to avoid conflicts)
    SNOOP_BUS_RD = 17    # Snoop: another cache reading
    SNOOP_BUS_RDX = 18   # Snoop: another cache writing
    SNOOP_BUS_UPGR = 19  # Snoop: another cache upgrading

