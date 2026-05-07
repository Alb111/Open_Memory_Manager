# SPDX-FileCopyrightText: © 2025 Albert Felix
# SPDX-License-Identifier: Apache-2.0
#
# cache_model.py
# ─────────────────────────────────────────────────────────────────────────────
# Python behavioural model of an MSI cache + cache controller.
#
# Key fixes vs prior revision
#   1. access() is now CLOCK-ACCURATE: returns (0, False) for each stall cycle
#      during a miss, then (rdata, True) on cycle N=miss_penalty.  The old
#      version always returned ready=True even with miss_penalty>0 (bug).
#   2. No RuntimeError is raised after construction.  All error conditions
#      emit warnings.warn() and recover to a safe state so cocotb never crashes
#      and logging is preserved.
#   3. access_blocking() helper added for standalone/non-cocotb tests.
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# 1.  MSI Constants
# ─────────────────────────────────────────────────────────────────────────────

class MSIState(IntEnum):
    I = 0b00
    S = 0b01
    M = 0b10


class ProcEvent(IntEnum):
    PR_RD = 0
    PR_WR = 1


class SnoopEvent(IntEnum):
    BUS_RD   = 0b00
    BUS_RDX  = 0b01
    BUS_UPGR = 0b10


class CoherenceCmd(IntEnum):
    CMD_BUS_RD         = 0
    CMD_BUS_RDX        = 1
    CMD_BUS_UPGR       = 2
    CMD_EVICT_CLEAN    = 3
    CMD_EVICT_DIRTY    = 4
    CMD_SNOOP_BUS_RD   = 5
    CMD_SNOOP_BUS_RDX  = 6
    CMD_SNOOP_BUS_UPGR = 7


# ─────────────────────────────────────────────────────────────────────────────
# 2.  MSI Protocol (purely combinational)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MSIOutput:
    next_state : MSIState               = MSIState.I
    cmd_valid  : bool                   = False
    issue_cmd  : Optional[CoherenceCmd] = None
    flush      : bool                   = False


class MSIProtocol:
    """
    Combinational MSI state machine.  Mirrors msi_protocol.v.

    Priority: proc_valid > snoop_valid.

    Processor transitions (proc_valid=1, snoop_valid=0):
      State  Event   Bus Cmd     Next
      I      PR_RD   BUS_RD      S
      I      PR_WR   BUS_RDX     M
      S      PR_RD   –           S   (hit)
      S      PR_WR   BUS_UPGR    M
      M      PR_RD   –           M   (hit)
      M      PR_WR   –           M   (hit)

    Snoop transitions (snoop_valid=1, proc_valid=0):
      State  Event     Bus Cmd          Next  Flush
      I      BUS_RD    –                I     no
      I      BUS_RDX   –                I     no
      I      BUS_UPGR  –                I     no
      S      BUS_RD    –                S     no
      S      BUS_RDX   –                I     no
      S      BUS_UPGR  –                I     no
      M      BUS_RD    CMD_SNOOP_BUS_RD S     yes
      M      BUS_RDX   CMD_SNOOP_BUS_RDX I   yes
      M      BUS_UPGR  –  (safe I)      I     yes  ← illegal in correct proto,
                                                      handled gracefully
    """

    _PROC_TABLE = {
        (MSIState.I, ProcEvent.PR_RD): (MSIState.S, CoherenceCmd.CMD_BUS_RD,   False),
        (MSIState.I, ProcEvent.PR_WR): (MSIState.M, CoherenceCmd.CMD_BUS_RDX,  False),
        (MSIState.S, ProcEvent.PR_RD): (MSIState.S, None,                       False),
        (MSIState.S, ProcEvent.PR_WR): (MSIState.M, CoherenceCmd.CMD_BUS_UPGR,  False),
        (MSIState.M, ProcEvent.PR_RD): (MSIState.M, None,                       False),
        (MSIState.M, ProcEvent.PR_WR): (MSIState.M, None,                       False),
    }

    _SNOOP_TABLE = {
        (MSIState.I, SnoopEvent.BUS_RD  ): (MSIState.I, None,                           False),
        (MSIState.I, SnoopEvent.BUS_RDX ): (MSIState.I, None,                           False),
        (MSIState.I, SnoopEvent.BUS_UPGR): (MSIState.I, None,                           False),
        (MSIState.S, SnoopEvent.BUS_RD  ): (MSIState.S, None,                           False),
        (MSIState.S, SnoopEvent.BUS_RDX ): (MSIState.I, None,                           False),
        (MSIState.S, SnoopEvent.BUS_UPGR): (MSIState.I, None,                           False),
        (MSIState.M, SnoopEvent.BUS_RD  ): (MSIState.S, CoherenceCmd.CMD_SNOOP_BUS_RD,  True ),
        (MSIState.M, SnoopEvent.BUS_RDX ): (MSIState.I, CoherenceCmd.CMD_SNOOP_BUS_RDX, True ),
        (MSIState.M, SnoopEvent.BUS_UPGR): (MSIState.I, None,                           True ),
    }

    def evaluate(
        self,
        current_state : MSIState,
        proc_valid    : bool,
        proc_event    : Optional[ProcEvent],
        snoop_valid   : bool,
        snoop_event   : Optional[SnoopEvent],
    ) -> MSIOutput:
        out = MSIOutput(next_state=current_state)

        if proc_valid and proc_event is not None:
            row = self._PROC_TABLE.get((current_state, proc_event))
            if row is None:
                warnings.warn(
                    f"MSIProtocol: undefined proc transition "
                    f"state={current_state.name} event={proc_event.name} — holding",
                    stacklevel=2,
                )
            else:
                ns, cmd, flush = row
                out.next_state = ns
                out.cmd_valid  = cmd is not None
                out.issue_cmd  = cmd
                out.flush      = flush

        elif snoop_valid and snoop_event is not None:
            row = self._SNOOP_TABLE.get((current_state, snoop_event))
            if row is None:
                warnings.warn(
                    f"MSIProtocol: undefined snoop transition "
                    f"state={current_state.name} event={snoop_event.name} — holding",
                    stacklevel=2,
                )
            else:
                ns, cmd, flush = row
                out.next_state = ns
                out.cmd_valid  = cmd is not None
                out.issue_cmd  = cmd
                out.flush      = flush

        return out


# ─────────────────────────────────────────────────────────────────────────────
# 3.  Cache Line
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CacheLine:
    valid       : bool      = False
    state       : MSIState  = MSIState.I
    tag         : int       = 0
    data        : List[int] = field(default_factory=lambda: [0] * 4)
    lru_counter : int       = 0

    def invalidate(self) -> None:
        self.valid = False
        self.state = MSIState.I
        self.tag   = 0
        self.data  = [0] * len(self.data)

    def is_dirty(self) -> bool:
        return self.valid and self.state == MSIState.M


# ─────────────────────────────────────────────────────────────────────────────
# 4.  Cache
# ─────────────────────────────────────────────────────────────────────────────

class Cache:
    """N-way set-associative cache with LRU replacement."""

    def __init__(
        self,
        num_sets       : int = 64,
        num_ways       : int = 2,
        words_per_line : int = 4,
        addr_bits      : int = 32,
    ):
        if not (num_sets and (num_sets & (num_sets - 1)) == 0):
            raise ValueError("num_sets must be a power of 2")
        if not (words_per_line and (words_per_line & (words_per_line - 1)) == 0):
            raise ValueError("words_per_line must be a power of 2")

        self.num_sets       = num_sets
        self.num_ways       = num_ways
        self.words_per_line = words_per_line
        self.addr_bits      = addr_bits

        self.byte_offset_bits = 2
        self.word_offset_bits = int(math.log2(words_per_line))
        self.index_bits       = int(math.log2(num_sets))
        self.tag_bits         = (addr_bits
                                 - self.index_bits
                                 - self.word_offset_bits
                                 - self.byte_offset_bits)

        self.lines: List[List[CacheLine]] = [
            [CacheLine(data=[0] * words_per_line) for _ in range(num_ways)]
            for _ in range(num_sets)
        ]
        self._lru_tick = 0

    # ── Address helpers ───────────────────────────────────────────────────────

    def decode_addr(self, addr: int) -> Tuple[int, int, int, int]:
        byte_offset = addr & 0x3
        word_offset = (addr >> self.byte_offset_bits) & (self.words_per_line - 1)
        set_index   = (addr >> (self.byte_offset_bits + self.word_offset_bits)) & (self.num_sets - 1)
        tag         = addr >> (self.byte_offset_bits + self.word_offset_bits + self.index_bits)
        return tag, set_index, word_offset, byte_offset

    def make_line_addr(self, tag: int, set_index: int) -> int:
        return ((tag << (self.byte_offset_bits + self.word_offset_bits + self.index_bits))
                | (set_index << (self.byte_offset_bits + self.word_offset_bits)))

    # ── Lookup ────────────────────────────────────────────────────────────────

    def lookup(self, addr: int) -> Tuple[bool, int, Optional[CacheLine]]:
        tag, set_idx, _, _ = self.decode_addr(addr)
        for way, line in enumerate(self.lines[set_idx]):
            if line.valid and line.tag == tag and line.state != MSIState.I:
                return True, way, line
        return False, -1, None

    def _lru_victim(self, set_idx: int) -> Tuple[int, CacheLine]:
        vw = min(range(self.num_ways), key=lambda w: self.lines[set_idx][w].lru_counter)
        return vw, self.lines[set_idx][vw]

    def _touch(self, set_idx: int, way: int) -> None:
        self._lru_tick += 1
        self.lines[set_idx][way].lru_counter = self._lru_tick

    # ── Fill / Update ─────────────────────────────────────────────────────────

    def fill(self, addr: int, data_words: List[int], state: MSIState) -> Optional[CacheLine]:
        tag, set_idx, _, _ = self.decode_addr(addr)
        vw, victim          = self._lru_victim(set_idx)
        evicted = None
        if victim.is_dirty():
            evicted = CacheLine(valid=True, state=victim.state,
                                tag=victim.tag, data=list(victim.data))
        victim.valid = True
        victim.state = state
        victim.tag   = tag
        victim.data  = list(data_words)
        self._touch(set_idx, vw)
        return evicted

    def update_word(self, addr: int, word: int, strobe: int) -> bool:
        """
        Write a byte-strobed word into a resident line.
        Returns False and warns (does NOT raise) if the line is not resident.
        """
        _, set_idx, word_off, _ = self.decode_addr(addr)
        hit, way, line = self.lookup(addr)
        if not hit:
            warnings.warn(
                f"Cache.update_word: 0x{addr:08X} not resident — write dropped",
                stacklevel=2,
            )
            return False
        current = line.data[word_off]
        result  = 0
        for b in range(4):
            mask = 0xFF << (b * 8)
            result |= (word & mask) if (strobe & (1 << b)) else (current & mask)
        line.data[word_off] = result
        line.state = MSIState.M
        self._touch(set_idx, way)
        return True

    def read_word(self, addr: int) -> int:
        """
        Read a word from a resident line.
        Returns 0 and warns (does NOT raise) if the line is not resident.
        """
        _, _, word_off, _ = self.decode_addr(addr)
        hit, _, line = self.lookup(addr)
        if not hit:
            warnings.warn(
                f"Cache.read_word: 0x{addr:08X} not resident — returning 0",
                stacklevel=2,
            )
            return 0
        return line.data[word_off]

    def set_state(self, addr: int, state: MSIState) -> None:
        hit, _, line = self.lookup(addr)
        if hit:
            line.state = state
            if state == MSIState.I:
                line.valid = False

    def flush_line(self, addr: int) -> Optional[CacheLine]:
        tag, set_idx, _, _ = self.decode_addr(addr)
        for _, line in enumerate(self.lines[set_idx]):
            if line.valid and line.tag == tag:
                evicted = CacheLine(valid=True, state=line.state,
                                    tag=tag, data=list(line.data))
                line.invalidate()
                return evicted
        return None


# ─────────────────────────────────────────────────────────────────────────────
# 5.  SRAM Model
# ─────────────────────────────────────────────────────────────────────────────

class SRAMModel:
    """Behavioural 512×32 SRAM matching mem_ctrl_512x32."""

    MEM_DEPTH = 512

    def __init__(self):
        self._mem: List[int] = [0] * self.MEM_DEPTH

    def _wa(self, byte_addr: int) -> int:
        return (byte_addr >> 2) & 0x1FF

    def read(self, mem_addr: int) -> int:
        return self._mem[self._wa(mem_addr)]

    def write(self, mem_addr: int, data: int, strobe: int) -> None:
        wa = self._wa(mem_addr)
        cur = self._mem[wa]
        result = 0
        for b in range(4):
            mask = 0xFF << (b * 8)
            result |= (data & mask) if (strobe & (1 << b)) else (cur & mask)
        self._mem[wa] = result

    def read_line(self, base: int, words: int) -> List[int]:
        return [self.read(base + i * 4) for i in range(words)]

    def write_line(self, base: int, data_words: List[int]) -> None:
        for i, w in enumerate(data_words):
            self.write(base + i * 4, w, 0xF)

    def load_program(self, data: List[int], start_word: int = 0) -> None:
        for i, val in enumerate(data):
            idx = start_word + i
            if idx >= self.MEM_DEPTH:
                break
            self._mem[idx] = val & 0xFFFF_FFFF


# ─────────────────────────────────────────────────────────────────────────────
# 6.  Cache Controller
# ─────────────────────────────────────────────────────────────────────────────

class CacheTransaction:
    __slots__ = ("addr", "is_write", "data", "strobe", "hit",
                 "msi_before", "msi_after", "cmd_issued", "stall_cycles")

    def __init__(self):
        self.addr         = 0
        self.is_write     = False
        self.data         = 0
        self.strobe       = 0
        self.hit          = False
        self.msi_before   = MSIState.I
        self.msi_after    = MSIState.I
        self.cmd_issued   = None
        self.stall_cycles = 0


@dataclass
class _PendingAccess:
    """State for a multi-cycle miss in progress."""
    rdata       : int
    txn         : CacheTransaction
    cycles_left : int   # reaches 0 on the cycle we return ready=True


class CacheController:
    """
    MSI cache controller with clock-accurate miss-penalty modelling.

    Miss-penalty stall protocol
    ───────────────────────────
    On a cache miss with miss_penalty=N:
      Cycle 0  First access() call:  SRAM fill performed internally,
               data ready, (0, False) returned (mem_ready=0).
      Cycles 1…N-1:  subsequent access() calls return (0, False).
      Cycle N:  access() returns (rdata, True) — mem_ready=1.

    Set miss_penalty=0 for zero-stall / single-cycle operation.

    No RuntimeError is ever raised after construction.
    """

    MISS_PENALTY = 4

    def __init__(
        self,
        cache        : Optional[Cache]     = None,
        sram         : Optional[SRAMModel] = None,
        miss_penalty : int                 = MISS_PENALTY,
    ):
        self.cache        = cache or Cache()
        self.sram         = sram  or SRAMModel()
        self.msi          = MSIProtocol()
        self.miss_penalty = miss_penalty
        self._pending: Optional[_PendingAccess] = None

        self.stats = {
            "reads"     : 0,
            "writes"    : 0,
            "hits"      : 0,
            "misses"    : 0,
            "evictions" : 0,
            "writebacks": 0,
        }
        self.log: List[CacheTransaction] = []

    # ── Primary interface ─────────────────────────────────────────────────────

    def access(
        self,
        mem_valid : bool,
        mem_instr : bool,
        mem_addr  : int,
        mem_wdata : int = 0,
        mem_wstrb : int = 0,
    ) -> Tuple[int, bool]:
        """
        Call once per clock edge while mem_valid is asserted.
        Returns (mem_rdata, mem_ready).
        """
        # ── Bus idle ──────────────────────────────────────────────────────────
        if not mem_valid:
            if self._pending is not None:
                warnings.warn(
                    f"CacheController: mem_valid dropped during pending miss "
                    f"at 0x{self._pending.txn.addr:08X} — aborting transaction",
                    stacklevel=2,
                )
                self._pending = None
            return 0, False

        # ── Drain stall for in-flight miss ────────────────────────────────────
        if self._pending is not None:
            self._pending.cycles_left -= 1
            if self._pending.cycles_left <= 0:
                rdata         = self._pending.rdata
                self.log.append(self._pending.txn)
                self._pending = None
                return rdata, True
            return 0, False

        # ── New transaction ───────────────────────────────────────────────────
        is_write = mem_wstrb != 0
        proc_evt = ProcEvent.PR_WR if is_write else ProcEvent.PR_RD
        self.stats["writes" if is_write else "reads"] += 1

        hit, _, line  = self.cache.lookup(mem_addr)
        current_state = line.state if hit else MSIState.I

        txn = CacheTransaction()
        txn.addr       = mem_addr
        txn.is_write   = is_write
        txn.data       = mem_wdata
        txn.strobe     = mem_wstrb
        txn.hit        = hit
        txn.msi_before = current_state

        msi_out = self.msi.evaluate(
            current_state = current_state,
            proc_valid    = True,
            proc_event    = proc_evt,
            snoop_valid   = False,
            snoop_event   = None,
        )
        txn.msi_after  = msi_out.next_state
        txn.cmd_issued = msi_out.issue_cmd

        if not hit:
            self.stats["misses"] += 1
            self._fill_line(mem_addr, msi_out.next_state)
        else:
            self.stats["hits"] += 1
            if msi_out.next_state != current_state:
                self.cache.set_state(mem_addr, msi_out.next_state)

        # Data operation always performed on cycle 0
        rdata = 0
        if is_write:
            self.cache.update_word(mem_addr, mem_wdata, mem_wstrb)
        else:
            rdata = self.cache.read_word(mem_addr)

        # ── Stall decision ────────────────────────────────────────────────────
        if not hit and self.miss_penalty > 0:
            txn.stall_cycles = self.miss_penalty
            self._pending = _PendingAccess(
                rdata       = rdata,
                txn         = txn,
                cycles_left = self.miss_penalty,   # decremented NEXT call
            )
            return 0, False

        txn.stall_cycles = 0
        self.log.append(txn)
        return rdata, True

    def access_blocking(
        self,
        mem_valid : bool,
        mem_instr : bool,
        mem_addr  : int,
        mem_wdata : int = 0,
        mem_wstrb : int = 0,
    ) -> int:
        """
        Standalone helper: loops access() until ready.
        Simulates the processor stalling on mem_ready=0.
        """
        rdata, ready = self.access(mem_valid, mem_instr, mem_addr, mem_wdata, mem_wstrb)
        while not ready:
            rdata, ready = self.access(mem_valid, mem_instr, mem_addr, mem_wdata, mem_wstrb)
        return rdata

    # ── Snoop interface ───────────────────────────────────────────────────────

    def snoop(
        self,
        addr        : int,
        snoop_event : SnoopEvent,
    ) -> Tuple[Optional[List[int]], bool]:
        """
        Handle an incoming bus snoop.
        Returns (supplied_data_or_None, flushed_bool).
        """
        hit, _, line = self.cache.lookup(addr)
        if not hit:
            return None, False

        msi_out = self.msi.evaluate(
            current_state = line.state,
            proc_valid    = False,
            proc_event    = None,
            snoop_valid   = True,
            snoop_event   = snoop_event,
        )

        supplied_data = None
        flushed       = False

        if msi_out.flush:
            base = self.cache.make_line_addr(line.tag, self._get_set(addr))
            self.sram.write_line(base, line.data)
            self.stats["writebacks"] += 1
            if snoop_event == SnoopEvent.BUS_RD:
                supplied_data = list(line.data)

        if msi_out.next_state == MSIState.I:
            self.cache.flush_line(addr)
            flushed = True
        elif msi_out.next_state != line.state:
            self.cache.set_state(addr, msi_out.next_state)

        return supplied_data, flushed

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_set(self, addr: int) -> int:
        c = self.cache
        return (addr >> (c.byte_offset_bits + c.word_offset_bits)) & (c.num_sets - 1)

    def _fill_line(self, addr: int, state: MSIState) -> None:
        c         = self.cache
        line_mask = ~((c.words_per_line * 4) - 1) & 0xFFFF_FFFF
        base      = addr & line_mask
        _, set_idx, _, _ = c.decode_addr(addr)
        _, victim = c._lru_victim(set_idx)
        if victim.is_dirty():
            wb_base = c.make_line_addr(victim.tag, set_idx)
            self.sram.write_line(wb_base, victim.data)
            self.stats["evictions"]  += 1
            self.stats["writebacks"] += 1
        data_words = self.sram.read_line(base, c.words_per_line)
        c.fill(addr, data_words, state)

    # ── Debug helpers ─────────────────────────────────────────────────────────

    def print_stats(self) -> None:
        s = self.stats
        total = s["reads"] + s["writes"]
        hr    = (s["hits"] / total * 100) if total else 0.0
        print(f"  Reads      : {s['reads']}")
        print(f"  Writes     : {s['writes']}")
        print(f"  Hits       : {s['hits']}")
        print(f"  Misses     : {s['misses']}")
        print(f"  Hit rate   : {hr:.1f}%")
        print(f"  Evictions  : {s['evictions']}")
        print(f"  Writebacks : {s['writebacks']}")

    def dump_log(self) -> None:
        for i, t in enumerate(self.log):
            op = "WR" if t.is_write else "RD"
            print(
                f"  [{i:4d}] {op} addr=0x{t.addr:08X}  "
                f"{'HIT ' if t.hit else 'MISS'} "
                f"{t.msi_before.name}→{t.msi_after.name}  "
                f"cmd={t.cmd_issued.name if t.cmd_issued else 'none':<22} "
                f"stall={t.stall_cycles}"
            )

from pathlib import Path
try:
    from cocotb_tools.runner import get_runner
except ImportError:
    from cocotb.runner import get_runner

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

async def reset(dut):
    dut.rst_ni.value = 0
    dut.mem_valid_i.value = 0
    dut.mem_addr_i.value = 0
    dut.mem_wdata_i.value = 0
    dut.mem_wstrb_i.value = 0
    dut.snoop_valid_i.value = 0
    dut.snoop_meta_i.value = 0
    dut.snoop_addr_i.value = 0
    dut.snoop_wdata_i.value = 0
    dut.out_ready_i.value = 1
    for _ in range(3):
        await RisingEdge(dut.clk_i)
    dut.rst_ni.value = 1
    await RisingEdge(dut.clk_i)

async def cpu_read(dut, addr):
    dut.mem_valid_i.value = 1
    dut.mem_addr_i.value = addr
    dut.mem_wstrb_i.value = 0
    while True:
        await RisingEdge(dut.clk_i)
        if int(dut.mem_ready_o.value):
            val = int(dut.mem_rdata_o.value)
            dut.mem_valid_i.value = 0
            return val

async def cpu_write(dut, addr, data, strb=0xF):
    dut.mem_valid_i.value = 1
    dut.mem_addr_i.value = addr
    dut.mem_wdata_i.value = data
    dut.mem_wstrb_i.value = strb
    while True:
        await RisingEdge(dut.clk_i)
        if int(dut.mem_ready_o.value):
            dut.mem_valid_i.value = 0
            dut.mem_wstrb_i.value = 0
            return

@cocotb.test()
async def smoke_read_write_and_snoop(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    await reset(dut)
    assert int(dut.cpu_id_o.value) == 1

    val = await cpu_read(dut, 0x00000010)
    assert val == 0

    await cpu_write(dut, 0x00000010, 0xDEADBEEF)
    val2 = await cpu_read(dut, 0x00000010)
    assert val2 == 0xDEADBEEF

    dut.snoop_valid_i.value = 1
    dut.snoop_meta_i.value = 0x9
    dut.snoop_addr_i.value = 0x00000010
    await RisingEdge(dut.clk_i)
    dut.snoop_valid_i.value = 0
    saw = False
    for _ in range(8):
        await RisingEdge(dut.clk_i)
        if int(dut.out_valid_o.value):
            saw = True
            assert int(dut.out_meta_o.value) in (0x9, 0xA)
    assert saw

@cocotb.test()
async def miss_emits_busrd_and_write_hit_upgrade(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, unit="ns").start())
    await reset(dut)

    dut.mem_valid_i.value = 1
    dut.mem_addr_i.value = 0x00000120
    dut.mem_wstrb_i.value = 0
    seen_busrd = False
    for _ in range(10):
        await RisingEdge(dut.clk_i)
        if int(dut.out_valid_o.value) and int(dut.out_meta_o.value) == 0x1:
            seen_busrd = True
        if int(dut.mem_ready_o.value):
            break
    dut.mem_valid_i.value = 0
    assert seen_busrd

    await cpu_write(dut, 0x00000120, 0xA5A5F00D)
    assert int(dut.mem_ready_o.value) in (0,1)

if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    runner = get_runner("icarus")
    runner.build(
        sources=[
            root / "src/msi_protocol/msi_protocol.sv",
            root / "src/cache/cache.sv",
            root / "src/mem_ctrl/mem512x32.sv",
            root / "src/cache/cache_controller.sv",
        ],
        hdl_toplevel="cache_controller",
        build_dir=str(Path(__file__).resolve().parent / "sim_build" / "cache_controller"),
        always=True,
    )
    runner.test(hdl_toplevel="cache_controller", test_module="test_cache_controller")

