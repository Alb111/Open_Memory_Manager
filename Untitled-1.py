"""
MESI cache coherence model (snooping bus)

This file models a small shared memory system with multiple private caches
that maintain coherence using the MESI protocol:

I  Invalid
S  Shared
E  Exclusive
M  Modified

Core ideas
1. Reads use BusRd
   If no other cache has the line, requester gets E
   If any other cache has the line, requester gets S and others become or stay S
   If some other cache has M, it must write back before sharing

2. Writes use either BusUpgr or BusRdX
   If writer already has the line in S, it issues BusUpgr to invalidate others and becomes M
   If writer misses or does not have the line, it issues BusRdX to fetch and invalidate others and becomes M
   If some other cache had M, it must write back before being invalidated

Writeback policy
This model is write back with write allocate.
Main memory is updated only on writeback events:
1. A cache in M responds to BusRd or BusRdX (it writes back before downgrade or invalidation)
2. A cache evicts an M line

This model is not a timing accurate simulator.
It is a functional coherence model meant for correctness checks and unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, List, Tuple, Optional


class State(Enum):
    """
    MESI states for a cache line.
    """
    I = auto()
    S = auto()
    E = auto()
    M = auto()


@dataclass
class Line:
    """
    One cache line tracked by a cache.

    base  aligned address of the line, for example 0x1000 for a line_size of 8
    data  bytearray holding the entire cache line
    state MESI state for this line
    """
    base: int
    data: bytearray
    state: State


class Bus:
    """
    Shared snooping bus.

    The bus is responsible for broadcasting coherence transactions:
    BusRd   for reads on a miss
    BusRdX  for writes on a miss (read for ownership, invalidate others)
    BusUpgr for writes on a hit in S (upgrade to ownership, invalidate others)

    It also tracks stats so the testbench can verify events occurred.
    """

    def __init__(self, memory, line_size: int = 8, verbose: bool = False):
        self.memory = memory
        self.line_size = line_size
        self.verbose = verbose
        self.caches: List["Cache"] = []

        # Bus level event counters used by tests
        self._stats = {
            "busrd": 0,
            "busrdx": 0,
            "busupgr": 0,
            "invalidations": 0,
            "writebacks": 0,
        }

    def attach(self, cache: "Cache") -> None:
        """
        Attach a cache to the bus so it can snoop transactions.
        """
        self.caches.append(cache)

    def _others(self, requester: "Cache") -> List["Cache"]:
        """
        Return all caches except the requester.
        """
        return [c for c in self.caches if c is not requester]

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    def get_stats(self) -> Dict[str, int]:
        """
        Return a copy of bus stats for testbench assertions.
        """
        return dict(self._stats)

    def busrd(self, requester: "Cache", line_base: int) -> Tuple[bytes, bool]:
        """
        BusRd: request a line for reading on a miss.

        Snooping effects on other caches:
        If another cache has M, it must write back, and downgrade to S.
        If another cache has E, it downgrades to S.
        If another cache has S, it stays S.
        If no other cache has the line in any non I state, requester can take E.

        Returns (line_data, shared)
        shared is True if any other cache had a valid copy.
        """
        self._stats["busrd"] += 1
        self._log(f"[BUS] BusRd from {requester.name} for {hex(line_base)}")

        shared = False

        for c in self._others(requester):
            line = c.lines.get(line_base)
            if not line or line.state is State.I:
                continue

            shared = True

            if line.state is State.M:
                # M must be written back before anyone can share clean data
                self._log(f"[BUS] {c.name} has M, writeback then downgrade to S")
                self.memory.write(line_base, bytes(line.data))
                self._stats["writebacks"] += 1
                line.state = State.S

            elif line.state is State.E:
                # E downgrades to S when another reader appears
                self._log(f"[BUS] {c.name} has E, downgrade to S")
                line.state = State.S

            elif line.state is State.S:
                # S stays S
                self._log(f"[BUS] {c.name} has S, stays S")

        data = self.memory.read(line_base, self.line_size)
        return data, shared

    def busrdx(self, requester: "Cache", line_base: int) -> bytes:
        """
        BusRdX: request a line for writing on a miss, also called read for ownership.

        Snooping effects on other caches:
        If another cache has M, it must write back before invalidation.
        If another cache has E or S, it is invalidated.
        After BusRdX, requester is the only valid owner and will go to M.

        Returns line_data read from memory after any required writebacks.
        """
        self._stats["busrdx"] += 1
        self._log(f"[BUS] BusRdX from {requester.name} for {hex(line_base)}")

        for c in self._others(requester):
            line = c.lines.get(line_base)
            if not line or line.state is State.I:
                continue

            if line.state is State.M:
                # Write back modified data before invalidation
                self._log(f"[BUS] {c.name} has M, writeback then invalidate")
                self.memory.write(line_base, bytes(line.data))
                self._stats["writebacks"] += 1
            else:
                self._log(f"[BUS] {c.name} has {line.state.name}, invalidate")

            # Invalidate the other cache copy
            line.state = State.I
            self._stats["invalidations"] += 1

        data = self.memory.read(line_base, self.line_size)
        return data

    def busupgr(self, requester: "Cache", line_base: int) -> None:
        """
        BusUpgr: upgrade a shared line to exclusive ownership for writing.

        This transaction is only valid when the requester already holds the line in S.
        It does not need to read memory, it only invalidates other S copies.
        """
        self._stats["busupgr"] += 1
        self._log(f"[BUS] BusUpgr from {requester.name} for {hex(line_base)}")

        for c in self._others(requester):
            line = c.lines.get(line_base)
            # Only S copies are expected here, but we handle defensively
            if line and line.state is not State.I:
                self._log(f"[BUS] invalidate line in {c.name} state {line.state.name}")
                line.state = State.I
                self._stats["invalidations"] += 1


class Cache:
    """
    Private cache attached to the shared bus.

    Capacity is modeled as a number of cache lines and an LRU eviction policy.
    Only byte reads and writes are exposed to keep the model simple.

    This cache implements:
    Read miss handling via BusRd
    Write miss handling via BusRdX
    Write hit upgrades via BusUpgr (S to M) or silent (E to M)
    Writeback on eviction of M lines
    """

    def __init__(
        self,
        name: str,
        bus: Bus,
        base_addr: int,
        line_size: int = 8,
        capacity_lines: int = 8,
        verbose: bool = False,
    ):
        self.name = name
        self.bus = bus
        self.base_addr = base_addr
        self.line_size = line_size
        self.capacity_lines = capacity_lines
        self.verbose = verbose

        # lines maps line_base to Line
        self.lines: Dict[int, Line] = {}

        # lru holds line_bases in least recent to most recent order
        self.lru: List[int] = []

        # Cache side stats used by tests
        self._stats = {
            "evictions": 0,
            "eviction_writebacks": 0,
            "read_hits": 0,
            "read_misses": 0,
            "write_hits": 0,
            "write_misses": 0,
        }

        bus.attach(self)

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg)

    def get_stats(self) -> Dict[str, int]:
        """
        Return a copy of cache stats for testbench assertions.
        """
        return dict(self._stats)

    def _align_base(self, addr: int) -> int:
        """
        Align an address to its cache line base.

        Example
        base_addr 0x1000, line_size 8
        addr 0x100B belongs to line base 0x1008
        """
        return self.base_addr + ((addr - self.base_addr) // self.line_size) * self.line_size

    def _touch(self, base: int) -> None:
        """
        Update LRU ordering when a line is accessed.
        """
        if base in self.lru:
            self.lru.remove(base)
        self.lru.append(base)

    def _evict_if_needed(self) -> None:
        """
        Evict one line if the cache is at capacity.

        Important behavior
        If the victim is in M, write it back to memory to preserve correctness.
        """
        if len(self.lines) < self.capacity_lines:
            return

        evict_base = self.lru.pop(0)
        victim = self.lines.pop(evict_base)
        self._stats["evictions"] += 1

        if victim.state is State.M:
            self._log(f"[{self.name}] evict M line {hex(evict_base)} writeback")
            self.bus.memory.write(evict_base, bytes(victim.data))
            self._stats["eviction_writebacks"] += 1
        else:
            self._log(f"[{self.name}] evict {victim.state.name} line {hex(evict_base)}")

    def _install_line(self, base: int, data: bytes, state: State) -> Line:
        """
        Install a new line into the cache.

        The install path is separated so that all miss handlers share:
        eviction decision
        initial allocation
        consistent LRU update
        """
        self._evict_if_needed()
        line = Line(base=base, data=bytearray(data), state=state)
        self.lines[base] = line
        self._touch(base)
        return line

    def peek_state(self, addr: int) -> State:
        """
        Convenience function used by the testbench.

        It returns the MESI state of the line that contains addr.
        If the line is not present, treat it as I.
        """
        base = self._align_base(addr)
        line = self.lines.get(base)
        if not line:
            return State.I
        return line.state

    def _get_line_for_read(self, addr: int) -> Line:
        """
        Read path line acquisition.

        Hit behavior
        If the line exists and is not I, it is a hit and returns immediately.

        Miss behavior
        Issue BusRd, then install as
        E if no other cache shared it
        S if some other cache had a copy
        """
        base = self._align_base(addr)
        line = self.lines.get(base)

        if line and line.state is not State.I:
            self._stats["read_hits"] += 1
            self._touch(base)
            self._log(f"[{self.name}] read hit {hex(base)} state {line.state.name}")
            return line

        self._stats["read_misses"] += 1
        self._log(f"[{self.name}] read miss {hex(base)}")

        data, shared = self.bus.busrd(self, base)
        new_state = State.S if shared else State.E
        self._log(f"[{self.name}] install {hex(base)} state {new_state.name}")
        return self._install_line(base, data, new_state)

    def _get_line_for_write(self, addr: int) -> Line:
        """
        Write path line acquisition.

        Hit behavior
        If the line exists and is not I:
        S  issue BusUpgr to invalidate others, then go to M
        E  silent upgrade to M
        M  remain M

        Miss behavior
        Issue BusRdX to invalidate others and fetch ownership, then install as M.
        """
        base = self._align_base(addr)
        line = self.lines.get(base)

        if line and line.state is not State.I:
            self._stats["write_hits"] += 1
            self._touch(base)
            self._log(f"[{self.name}] write hit {hex(base)} state {line.state.name}")

            if line.state is State.S:
                self.bus.busupgr(self, base)
                line.state = State.M
            elif line.state is State.E:
                line.state = State.M

            return line

        self._stats["write_misses"] += 1
        self._log(f"[{self.name}] write miss {hex(base)}")

        data = self.bus.busrdx(self, base)
        self._log(f"[{self.name}] install {hex(base)} state M")
        return self._install_line(base, data, State.M)

    def read_byte(self, addr: int) -> int:
        """
        Public read interface used by tests and potential simulators.

        It returns a single byte at addr.
        """
        line = self._get_line_for_read(addr)
        off = addr - line.base
        return line.data[off]

    def write_byte(self, addr: int, value: int) -> None:
        """
        Public write interface used by tests and potential simulators.

        It writes a single byte at addr, updating MESI state to M.
        """
        line = self._get_line_for_write(addr)
        off = addr - line.base
        line.data[off] = value & 0xFF
        line.state = State.M
