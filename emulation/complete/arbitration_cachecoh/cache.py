# types
from dataclasses import dataclass
from typing import Callable, Dict

from complete.axi_request import axi_request

from msi import (
    MSIState,
    ProcessorEvent,
    SnoopEvent,
    CoherenceCmd,
    pack_cmd,
    unpack_cmd,
    on_processor_event,
    on_snoop_event,
)


# ============================================================================
# Utility Functions
# ============================================================================

def apply_wstrb(old_value: int, new_value: int, wstrb: int) -> int:
    """
    Apply byte-level write strobe to merge new data with old data.
    
    This function implements byte-granular writes, allowing partial word updates.
    Each bit in wstrb controls whether the corresponding byte is updated.
    
    Args:
        old_value: Existing 32-bit value in cache
        new_value: New 32-bit value from CPU write
        wstrb: Write strobe mask (4 bits for 4 bytes)
               Bit 0 = byte 0 (bits [7:0])
               Bit 1 = byte 1 (bits [15:8])
               Bit 2 = byte 2 (bits [23:16])
               Bit 3 = byte 3 (bits [31:24])
    
    Returns:
        Merged 32-bit value with selected bytes updated
    
    Example:
        old = 0xAABBCCDD
        new = 0x11223344
        wstrb = 0b0101 (update bytes 0 and 2)
        result = 0xAABB3344
                      ^    ^^
                      |     └── Byte 0 updated (wstrb bit 0 = 1)
                      └──────── Byte 2 updated (wstrb bit 2 = 1)
    
    Hardware Note:
        In hardware, this would be implemented as a mux per byte:
        result[7:0]   = wstrb[0] ? new_value[7:0]   : old_value[7:0]
        result[15:8]  = wstrb[1] ? new_value[15:8]  : old_value[15:8]
        result[23:16] = wstrb[2] ? new_value[23:16] : old_value[23:16]
        result[31:24] = wstrb[3] ? new_value[31:24] : old_value[31:24]
    """
    result = old_value
    for i in range(4):  # 4 bytes in a 32-bit word
        if (wstrb >> i) & 1:  # Check if bit i is set
            # Update byte i
            byte_mask = 0xFF << (8 * i)  # Mask for byte i
            result = (result & ~byte_mask) | (new_value & byte_mask)
    return result


# ============================================================================
# Cache Line Data Structure
# ============================================================================

@dataclass
class CacheLine:
    """
    Represents a single cache line with MSI state and data.
    
    Fields:
        state: Current MSI state (INVALID, SHARED, or MODIFIED)
        data: Cached data value (32-bit word)
    
    Notes:
        - In a real cache, this would also include tag, valid bit, etc.
        - This simplified version uses the address as an implicit tag
        - Each address maps to its own CacheLine entry
    """
    state: MSIState = MSIState.INVALID  # Default: line is invalid
    data: int = 0                       # Default: data is zero


# ============================================================================
# Cache Controller
# ============================================================================

class CacheController:
    """
    Cache controller implementing MSI coherence protocol.
    
    This controller manages cache storage and coherence for a single CPU core.
    It uses a simple fully-associative cache structure where each address
    maps to its own cache line.
    
    Communication Patterns:
    
    1. CPU Read/Write Path (mem_instr=False):
       CPU → CacheController.axi_handler()
                ↓
           _cpu_read() or _cpu_write()
                ↓
           on_processor_event() [state machine]
                ↓
           _send_dir_cmd() [if cache miss or upgrade needed]
                ↓
           DirectoryController
    
    2. Directory Snoop Path (mem_instr=True):
       DirectoryController → CacheController.axi_handler()
                                  ↓
                            _handle_snoop()
                                  ↓
                            on_snoop_event() [state machine]
                                  ↓
                            Return flush data (if needed)
    
    Attributes:
        core_id: ID of this cache (0 or 1)
        directory_port: Function to send AXI requests to directory
        lines: Dictionary mapping addresses to CacheLine objects
    """

    def __init__(self, core_id: int, directory_axi_handler: Callable[[axi_request], axi_request]):
        """
        Initialize cache controller.
        
        Args:
            core_id: Unique identifier for this cache (0 or 1 in 2-core system)
            directory_axi_handler: Function to send coherence requests to directory
                                  Signature: axi_request → axi_request
        
        Example:
            # In system setup:
            directory = DirectoryController(num_cores=2)
            cache0 = CacheController(core_id=0, directory_axi_handler=directory.axi_handler)
            cache1 = CacheController(core_id=1, directory_axi_handler=directory.axi_handler)
        """
        self.core_id = core_id
        self.directory_port = directory_axi_handler
        
        # Cache storage: address → CacheLine
        # Fully associative cache (each address can be cached independently)
        self.lines: Dict[int, CacheLine] = {}

        

    def _line(self, addr: int) -> CacheLine:
        """
        Get cache line for an address, creating if necessary.
        
        This implements lazy allocation - cache lines are created on-demand
        when first accessed. New lines start in INVALID state.
        
        Args:
            addr: Memory address
        
        Returns:
            CacheLine object for this address
        
        Note:
            In hardware, this would be implemented as a CAM (Content Addressable
            Memory) lookup or set-associative indexing. Here we use a simple
            dictionary for clarity.
        """

        if addr not in self.lines:
            self.lines[addr] = CacheLine()
        return self.lines[addr]

    def _send_dir_cmd(self, cmd: CoherenceCmd, addr: int, payload: int = 0) -> int:
        """
        Send a coherence command to the directory controller.
        
        This is the cache's interface to the coherence system. It packages
        coherence commands (BUS_RD, BUS_RDX, BUS_UPGR, evictions) into AXI
        requests and sends them to the directory.
        
        Args:
            cmd: Coherence command to send
            addr: Memory address
            payload: Optional payload (e.g., data for EVICT_DIRTY)
        
        Returns:
            Response data from directory (e.g., fetched data for BUS_RD/BUS_RDX)
        
        Raises:
            RuntimeError: If directory doesn't acknowledge the request
        
        Example Flow:
            1. Cache misses on read
            2. _send_dir_cmd(BUS_RD, addr) is called
            3. Directory fetches data from memory or another cache
            4. Directory returns data in mem_rdata
            5. Cache stores data and transitions to SHARED
        
        AXI Request Structure:
            mem_valid = True
            mem_instr = True (coherence traffic, not CPU traffic)
            mem_addr = target address
            mem_wdata = packed command [cmd | core_id | payload]
            mem_wstrb = 0xF (all bytes valid for command)
        """
        # Pack coherence command into mem_wdata field
        req = axi_request(
            mem_valid=True,
            mem_instr=True,  # This is coherence traffic
            mem_addr=addr,
            mem_wdata=pack_cmd(cmd, self.core_id, payload),
            mem_wstrb=0xF,  # All bytes valid
        )
        
        # Send request to directory and get response
        resp = self.directory_port(req)
        
        # Verify directory acknowledged
        if not resp.mem_ready:
            raise RuntimeError(f"directory did not acknowledge core {self.core_id}")
        
        # Return data from directory (relevant for BUS_RD, BUS_RDX)
        return resp.mem_rdata

    def _cpu_read(self, addr: int) -> int:
        """
        Handle CPU read request.
        
        This implements the processor read path, checking cache state and
        issuing coherence transactions as needed.
        
        State Transition Logic:
            INVALID → SHARED: Issue BUS_RD to fetch data
            SHARED → SHARED: Read hit, return cached data
            MODIFIED → MODIFIED: Read hit, return cached data
        
        Args:
            addr: Memory address to read
        
        Returns:
            Data value (from cache or fetched from directory)
        
        Detailed Flow:
            1. Get cache line for this address
            2. Query state machine: what happens on PR_RD in current state?
            3. If state machine says issue command (e.g., BUS_RD on miss):
               - Send command to directory
               - Directory returns data
               - Store data in cache line
            4. Update cache line state
            5. Return data to CPU
        """
        line = self._line(addr)
        
        # Ask state machine: what do we do for a read in current state?
        tr = on_processor_event(line.state, ProcessorEvent.PR_RD)

        # If cache miss (or other condition requiring coherence transaction)
        if tr.issue_cmd is not None:
            # Fetch data from directory/memory
            # Directory will handle getting data from memory or another cache
            line.data = self._send_dir_cmd(tr.issue_cmd, addr)

        # Update cache line state based on state machine result
        line.state = tr.next_state
        
        # Return data to CPU
        return line.data

    def _cpu_write(self, addr: int, wdata: int, wstrb: int) -> int:
        """
        Handle CPU write request.
        
        This implements the processor write path, ensuring the cache has
        exclusive access before allowing the write.
        
        State Transition Logic:
            INVALID → MODIFIED: Issue BUS_RDX to get exclusive access
            SHARED → MODIFIED: Issue BUS_UPGR to invalidate other sharers
            MODIFIED → MODIFIED: Write hit, update data directly
        
        Args:
            addr: Memory address to write
            wdata: Write data value
            wstrb: Write strobe (byte enable mask)
        
        Returns:
            Final data value after write (with byte merging)
        
        Detailed Flow:
            1. Get cache line for this address
            2. Query state machine: what happens on PR_WR in current state?
            3. If state machine says issue command:
               - INVALID → BUS_RDX (fetch data + exclusive access)
               - SHARED → BUS_UPGR (just invalidate others, already have data)
            4. Update cache line state to MODIFIED
            5. Merge write data with existing data (byte-granular)
            6. Return updated data to CPU
        
        Note on BUS_UPGR vs BUS_RDX:
            - BUS_UPGR: Cache already has data (SHARED), just needs exclusive access
              No data transfer needed, only invalidation of other copies
            - BUS_RDX: Cache doesn't have data (INVALID), needs both data and exclusive
              Data transfer + invalidation
        """
        line = self._line(addr)
        
        # Ask state machine: what do we do for a write in current state?
        tr = on_processor_event(line.state, ProcessorEvent.PR_WR)

        # If we need exclusive access or need to fetch data
        if tr.issue_cmd is not None:
            # Send coherence command to directory
            # BUS_RDX: will return data and invalidate others
            # BUS_UPGR: will just invalidate others (we already have data)
            _ = self._send_dir_cmd(tr.issue_cmd, addr)

        # Update state (will be MODIFIED after any write)
        line.state = tr.next_state
        
        # Apply byte-level write to existing data
        # This allows partial word updates (e.g., writing only 1 byte)
        line.data = apply_wstrb(line.data, wdata, wstrb)
        
        # Return updated data
        return line.data

    def _handle_snoop(self, addr: int, packed_cmd: int) -> int:
        """
        Handle snoop message from directory.
        
        Snoops occur when ANOTHER cache issues a coherence transaction that
        affects this cache's copy of the data. The directory sends snoop
        messages to coordinate between caches.
        
        Snoop Types and Responses:
            SNOOP_BUS_RD (another cache reading):
                - SHARED → SHARED: No action
                - MODIFIED → SHARED: Flush data, downgrade to shared
            
            SNOOP_BUS_RDX (another cache writing):
                - SHARED → INVALID: Invalidate our copy
                - MODIFIED → INVALID: Flush data, invalidate
            
            SNOOP_BUS_UPGR (another cache upgrading):
                - SHARED → INVALID: Invalidate our copy
        
        Args:
            addr: Memory address being snooped
            packed_cmd: Packed coherence command from directory
        
        Returns:
            Flushed data (if MODIFIED and flush required), else 0
        
        Example Scenario:
            1. Cache 0 has address X in MODIFIED state
            2. Cache 1 issues BUS_RD for address X
            3. Directory sends SNOOP_BUS_RD to Cache 0
            4. Cache 0 calls _handle_snoop()
            5. State machine says: MODIFIED + BUS_RD → SHARED (flush=True)
            6. Cache 0 returns its dirty data in mem_rdata
            7. Directory updates memory and sends data to Cache 1
        """
        line = self._line(addr)
        
        # Unpack snoop command
        cmd, requester, payload = unpack_cmd(packed_cmd)
        # Note: requester and payload are currently unused but may be useful
        # for debugging or extended protocols (e.g., forwarding data directly)
        _ = requester
        _ = payload

        # Map coherence command to snoop event
        if cmd == int(CoherenceCmd.SNOOP_BUS_RD):
            event = SnoopEvent.BUS_RD
        elif cmd == int(CoherenceCmd.SNOOP_BUS_RDX):
            event = SnoopEvent.BUS_RDX
        elif cmd == int(CoherenceCmd.SNOOP_BUS_UPGR):
            event = SnoopEvent.BUS_UPGR
        else:
            raise ValueError(f"unknown snoop cmd {cmd}")

        # Ask state machine: how do we respond to this snoop?
        tr = on_snoop_event(line.state, event)
        
        # If flush requested, provide our dirty data
        # Otherwise return 0 (no data needed)
        flush_data = line.data if tr.flush else 0
        
        # Update state (may invalidate or downgrade to SHARED)
        line.state = tr.next_state
        
        # Return flush data to directory
        return flush_data

    def evict(self, addr: int) -> None:
        """
        Evict a cache line (e.g., due to capacity miss in a real cache).
        
        When evicting a line, we must inform the directory and write back
        dirty data if the line is MODIFIED.
        
        Eviction Flow:
            INVALID: No action needed (line not present)
            SHARED: Send EVICT_CLEAN (no writeback needed)
            MODIFIED: Send EVICT_DIRTY with data (writeback required)
        
        Args:
            addr: Address to evict
        
        Example Use Case:
            In a real set-associative cache, when a new line needs to be
            brought in but the set is full, an existing line must be evicted.
            This function would be called to properly handle the eviction
            with coherence protocol compliance.
        
        Note:
            This implementation uses a fully-associative cache (dict), so
            capacity evictions don't naturally occur. This function is
            provided for completeness and testing.
        """
        # Check if line exists in cache
        if addr not in self.lines:
            return

        line = self.lines[addr]
        
        # Handle eviction based on state
        if line.state == MSIState.MODIFIED:
            # Dirty data must be written back
            _ = self._send_dir_cmd(CoherenceCmd.EVICT_DIRTY, addr, line.data)
        elif line.state == MSIState.SHARED:
            # Clean data, just notify directory
            _ = self._send_dir_cmd(CoherenceCmd.EVICT_CLEAN, addr)
        # INVALID state: no action needed

        # Mark line as invalid after eviction
        line.state = MSIState.INVALID

    def axi_handler(self, request: axi_request) -> axi_request:
        """
        Main AXI request handler - routes requests to appropriate handlers.
        
        This is the primary entry point for all communication with the cache.
        It distinguishes between two types of traffic:
        
        1. CPU Memory Traffic (mem_instr=False):
           - Read: mem_wstrb == 0
           - Write: mem_wstrb != 0
           Routes to: _cpu_read() or _cpu_write()
        
        2. Coherence Traffic (mem_instr=True):
           - Snoop messages from directory
           Routes to: _handle_snoop()
        
        Args:
            request: AXI request (from CPU or directory)
        
        Returns:
            AXI response with mem_ready=True and appropriate data
        
        Request Flow Examples:
        
        CPU Read:
            request.mem_instr = False
            request.mem_wstrb = 0
            request.mem_addr = 0x1000
            ↓
            response.mem_rdata = _cpu_read(0x1000)
            response.mem_ready = True
        
        CPU Write:
            request.mem_instr = False
            request.mem_wstrb = 0xF
            request.mem_addr = 0x2000
            request.mem_wdata = 0xDEADBEEF
            ↓
            response.mem_rdata = _cpu_write(0x2000, 0xDEADBEEF, 0xF)
            response.mem_ready = True
        
        Directory Snoop:
            request.mem_instr = True
            request.mem_addr = 0x3000
            request.mem_wdata = pack_cmd(SNOOP_BUS_RD, requester=1)
            ↓
            response.mem_rdata = _handle_snoop(0x3000, packed_cmd)
            response.mem_ready = True
        """
        # Ignore invalid requests
        if not request.mem_valid:
            request.mem_ready = False
            return request

        # Route based on traffic type
        if request.mem_instr:
            # Coherence traffic: snoop from directory
            request.mem_rdata = self._handle_snoop(request.mem_addr, request.mem_wdata)
            # request.mem_ready = True  We shouldnt need this
            return request

        # CPU memory traffic: read or write
        if request.mem_wstrb == 0:
            # CPU read (write strobe = 0)
            request.mem_rdata = self._cpu_read(request.mem_addr)
        else:
            # CPU write (write strobe != 0)
            request.mem_rdata = self._cpu_write(
                request.mem_addr,
                request.mem_wdata,
                request.mem_wstrb
            )

        # Mark response as ready
        request.mem_ready = True
        return request
        
    def dump_cache(self) -> None:
        if not self.lines:
            print(f"  Cache{self.core_id}:  (empty)")
            return

        for addr, line in sorted(self.lines.items()):
            print(
                f"  Cache{self.core_id}:  addr=0x{addr:08X}| "
                f" state={line.state.name:<8}|"
                f" data=0x{line.data:08X}"
            )
