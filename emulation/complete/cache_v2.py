# External 
from contextlib import redirect_stdout
from dataclasses import dataclass

# Data Types
from typing import (Callable, Awaitable, Dict, Required)
from axi_request import (axi_and_coherence_request, axi_request)
from msi_v2 import (MSIState, ProcessorEvent, SnoopEvent, CoherenceCmd, TransitionResult) 

# Functions
from msi_v2 import (on_processor_event, on_snoop_event)
from util import (apply_wstrb)

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



class CacheController:
    """
    Cache controller implementing MSI coherence protocol.
    Handles processor requests and directory snoops.
    Fully associative for simulation simplicity.
    """

    def __init__(self, core_id: int, directory_axi_handler: Callable[[axi_and_coherence_request], Awaitable[axi_request]]) -> None:
        """
        Create a cache controller for a single core.

        Args:
            core_id (int): Cache identifier.
            directory_axi_handler (Callable): Directory request interface.
        """

        self.core_id: int = core_id
        self.directory_port: Callable[[axi_and_coherence_request], Awaitable[axi_request]] = directory_axi_handler       

        self.lines: Dict[int, CacheLine] = {}
        # self.lines is a simplication in hadware the addr wont be directly mapped to Cache line it will more like this:  
         
        #        index
        #          ↓
        # +------------------+
        # |   TAG SRAM       |
        # | tag | state | V  |
        # +------------------+
        #          ↓ compare
        # +------------------+
        # |   DATA SRAM      |
        # |   64B line       |
        # +------------------+

    def _line(self, addr: int) -> CacheLine:
        """
        Get or create the cache line for an address.

        Args:
            addr (int): address.
        """

        if addr not in self.lines:
            self.lines[addr] = CacheLine()
        return self.lines[addr]

    
    async def _send_dir_cmd(self, cmd: CoherenceCmd, addr: int, payload: int = 0) -> axi_request:
        """
        Send a coherence command to the directory and returns its response.

        Args:
            cmd (CohereneceCmd: 3 bits): address.
            addr (32 bits): address of memory
            payload (32 bits): Optional payload containing data to write to main memory

        Returns:
            Response data from directory

        """

        # build axi + conherence request        
        req: axi_and_coherence_request = axi_and_coherence_request(
            mem_valid = True,
            mem_ready = False,
            mem_instr = False,
            mem_addr = addr,
            mem_wdata_or_msi_payload = payload,
            mem_wstrb = 0xF,  # All bytes valid
            mem_rdata = 0,
            coherence_cmd = cmd,
            core_id = self.core_id
        )

        # Send request to directory and get response
        resp: axi_request = await self.directory_port(req)
        
        # Verify directory acknowledged
        if not resp.mem_ready:
            raise RuntimeError(f"directory did not acknowledge core {self.core_id}")
        
        # Return data from directory (relevant for BUS_RD, BUS_RDX)
        return resp


    async def _handle_cpu_read(self, request: axi_request) -> axi_request:
        """
        Handles CPU read request, takes cachlines current state and figure out next one using state machine provisioned in on_processor event 
        
        Args:
            request: axi_request to read
        
        Returns:
            a axi_request repsone with handshake complete (connected to core.py)
        """

        line: CacheLine = self._line(request.mem_addr)
        
        # Ask state machine: what do we do for a read in current state?
        tr: TransitionResult = on_processor_event(line.state, ProcessorEvent.PR_RD)

        # If cache miss (or other condition requiring coherence transaction)
        if tr.issue_cmd is not None:
            # Fetch data from directory/memory and update cache line
            line.data = (await self._send_dir_cmd(tr.issue_cmd, request.mem_addr)).mem_rdata
            request.mem_rdata = line.data            

        # we have data in cache so just pipe it straight through
        else:
            request.mem_rdata = line.data
        
        request.mem_ready = True
            
        # Update cache line state based on state machine result
        line.state = tr.next_state
        
        # Return data to CPU
        return request 


    async def _handle_cpu_write(self, request: axi_request) -> axi_request:

        """
        Handles CPU write request, takes cachlines current state and figure out next one using state machine provisioned in on_processor event 

        Args:
            request: axi_request to write
        
        Returns:
            a axi_and_coherence_request repsone with handshake complete
            ie mem_ready and valid are both high         

        """

        line: CacheLine = self._line(request.mem_addr)
    
        # Ask state machine: what do we do for a write in current state?
        tr: TransitionResult = on_processor_event(line.state, ProcessorEvent.PR_WR)

        # If we need exclusive access or need to fetch data
        if tr.issue_cmd is not None:
            dir_resp: axi_request = await self._send_dir_cmd(tr.issue_cmd, request.mem_addr)

            if dir_resp.mem_ready != True:
                raise ValueError("directory response not right after read")

        # Update state (will be MODIFIED after any write)
        line.state = tr.next_state
        
        # Apply byte-level write to existing data
        # This allows partial word updates (e.g., writing only 1 byte)
        line.data = apply_wstrb(line.data, request.mem_wdata, request.mem_wstrb)
        
        # Return updated data
        request.mem_ready = True
        return request

    def _handle_snoop(self, request: axi_and_coherence_request) -> axi_and_coherence_request:

        """
        Handle snoop message from directory.
        
        Snoops occur when ANOTHER cache issues a coherence transaction that
        affects this cache's copy of the data. The directory sends snoop
        messages to coordinate between caches.
        
        Args:
            (pass in a axi_and_cohrence_request from it the following are used)
                addr: Memory address being snooped
                packed_cmd: Packed coherence command from directory
        
        Returns:
            Flushed data (if MODIFIED and flush required), else 0        

        """

        line: CacheLine = self._line(request.mem_addr)


        cmd: CoherenceCmd = request.coherence_cmd

        # Note: requester and payload are currently unused but may be useful later
        requester: int = request.core_id
        payload: int = request.mem_rdata

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
        tr: TransitionResult = on_snoop_event(line.state, event)
        
        # If flush requested, provide our dirty data
        # Otherwise return 0 (no data needed)
        request.mem_wdata_or_msi_payload = line.data if tr.flush else 0
        
        # Update state (may invalidate or downgrade to SHARED)
        line.state = tr.next_state
        
        # Return flush data to directory
        return request


    def evict(self, addr: int) -> None:

        """
        Currently not used (our emualted cache has no limit)
        
        Evict a cache line (e.g., due to capacity miss in a real cache).

        
        When evicting a line, we must inform the directory and write back
        dirty data if the line is MODIFIED.
        
        Args:
            addr: Address to evict
        
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


    async def handle_request(self, request):
        """
        Unified handler for:
          - axi_request (CPU traffic)
          - axi_and_coherence_request (Directory / snoop traffic)
        """

        # ---------------------------
        # AXI CPU REQUEST
        # ---------------------------
        if isinstance(request, axi_request):

            # Ignore invalid requests
            if not request.mem_valid:
                request.mem_ready = False
                return request

            # CPU read or write
            if request.mem_wstrb == 0:
                request = await self._handle_cpu_read(request)
            else:
                request = await self._handle_cpu_write(request)

            request.mem_ready = True
            return request

        # ---------------------------
        # AXI + COHERENCE REQUEST
        # ---------------------------
        elif isinstance(request, axi_and_coherence_request):

            if not request.mem_valid:
                request.mem_ready = False
                return request

            request = self._handle_snoop(request)
            return request

        # ---------------------------
        # Unknown request type
        # ---------------------------
        else:
            raise TypeError(f"Unsupported request type: {type(request)}")


    

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

    # async def axi_handler(self, request: axi_request ) -> axi_request:

    #     """
    #     Core's AXI request handler - routes requests to appropriate handlers.
    #     This is the primary entry point for all communication with the cache and core.
        
    #     1. CPU Memory Traffic (axi_request):
    #        - Read: mem_wstrb == 0
    #        - Write: mem_wstrb != 0
    #        Routes to: _cpu_read() or _cpu_write()
        
    #     Args:
    #         request:
    #         AXI request from CPU
        
    #     Returns:
    #         AXI response with mem_ready=True and appropriate data to the core        

    #     """
        
    #     # Ignore invalid requests
    #     if not request.mem_valid:
    #         request.mem_ready = False
    #         return request

    #     # CPU memory traffic: read or write
    #     if request.mem_wstrb == 0:
    #         # CPU read (write strobe = 0)
    #         request = await self._handle_cpu_read(request)
    #     else:
    #         # CPU write (write strobe != 0)
    #         request = await self._handle_cpu_write(request)

    #     # Mark response as ready
    #     request.mem_ready = True
    #     return request




    # def axi_and_coherence_handler(self, request: axi_and_coherence_request ) -> axi_and_coherence_request:

    #     """
    #     Core's axi+coherence request handler - routes requests to appropriate handlers.

    #     This is the primary entry point for all communication with the directory mainly just used for snoop requests.

    #     Args:
    #         AXI + Cohrence Cmd from directory

    #     Returns:
    #         AXI + Cohrence Cmd with mem_ready=True and appropriate data to the core        
    #     """

    #     # Coherence traffic: snoop from directory
        
    #     # Error Handling 
    #     if not request.mem_valid:
    #         request.mem_ready = False
    #         return request

    #     request = self._handle_snoop(request)
    #     # request.mem_ready = True  We shouldnt need this
    #     return request

