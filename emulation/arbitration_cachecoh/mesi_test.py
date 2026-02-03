import os
import random
import unittest

from mesi_protocol import Bus, Cache, State


class StrictMemoryPool:
    """
    Testbench memory.

    This is stricter than a typical simulation memory because it throws on out of bounds.
    It also counts reads and writes for optional sanity checks.
    """

    def __init__(self, size: int = 64, base_addr: int = 0x1000):
        if size <= 0:
            raise ValueError("bad size")
        self.BASE_ADDR = base_addr
        self.SIZE = size
        self.mem = {}
        self.reads = 0
        self.writes = 0

    def _valid(self, addr: int) -> bool:
        return self.BASE_ADDR <= addr < self.BASE_ADDR + self.SIZE

    def write(self, addr: int, data: bytes):
        for i, b in enumerate(data):
            a = addr + i
            if not self._valid(a):
                raise ValueError(f"oob write at {hex(a)}")
            self.mem[a] = b
        self.writes += 1

    def read(self, addr: int, size: int) -> bytes:
        out = []
        for i in range(size):
            a = addr + i
            if not self._valid(a):
                raise ValueError(f"oob read at {hex(a)}")
            out.append(self.mem.get(a, 0))
        self.reads += 1
        return bytes(out)


def init_memory_pattern(mem: StrictMemoryPool) -> None:
    """
    Fill memory with a deterministic pattern so reads are predictable.

    We want predictable nontrivial values so bugs are easier to spot than all zeros.
    """
    base = mem.BASE_ADDR
    data = bytes([(i * 37 + 11) & 0xFF for i in range(mem.SIZE)])
    mem.write(base, data)


def mem_read_byte(mem: StrictMemoryPool, addr: int) -> int:
    """
    Convenience helper for truth checking values directly from memory.
    """
    return mem.read(addr, 1)[0]


def line_base(mem_base: int, addr: int, line_size: int) -> int:
    """
    Compute the aligned line base for a given address.

    This is used in tests that must guarantee they touch distinct cache lines.
    """
    return mem_base + ((addr - mem_base) // line_size) * line_size


def assert_cache_integrity(cache: Cache) -> None:
    """
    Internal cache structure consistency check.

    This does not test coherence, it tests the cache bookkeeping:
    lru must reference exactly the set of installed line bases.
    """
    lru_set = set(cache.lru)
    line_set = set(cache.lines.keys())
    if lru_set != line_set:
        raise AssertionError("lru and lines keys differ")

    for base in cache.lru:
        if base not in cache.lines:
            raise AssertionError("lru contains base not present in lines")


def assert_system_invariants(c0: Cache, c1: Cache) -> None:
    """
    Coherence legality checks that must hold after every operation.

    These are MESI invariants:
    1. If one cache has M, the other must be I for that line
    2. If one cache has E, the other must be I for that line
    """
    bases = set(list(c0.lines.keys()) + list(c1.lines.keys()))
    for base in bases:
        s0 = c0.lines[base].state if base in c0.lines else State.I
        s1 = c1.lines[base].state if base in c1.lines else State.I

        if s0 is State.M and s1 is not State.I:
            raise AssertionError("illegal: M must be exclusive")

        if s1 is State.M and s0 is not State.I:
            raise AssertionError("illegal: M must be exclusive")

        if s0 is State.E and s1 is not State.I:
            raise AssertionError("illegal: E must be unique")

        if s1 is State.E and s0 is not State.I:
            raise AssertionError("illegal: E must be unique")

    assert_cache_integrity(c0)
    assert_cache_integrity(c1)


class ReporterMixin:
    """
    Small helper used to print per iteration status.

    We keep this separate from the tests so the test bodies remain readable.
    """

    def report_case(self, group: str, idx: int, total: int, label: str, fn):
        prefix = f"[{group}] iter {idx} of {total}  {label}"
        print(prefix, end="  ")
        try:
            fn()
        except AssertionError as e:
            print("RESULT FAIL")
            print(f"  REASON {e}")
            raise
        except Exception as e:
            print("RESULT ERROR")
            print(f"  REASON {type(e).__name__}: {e}")
            raise
        else:
            print("RESULT OK")


class TestMESIThoroughReported(unittest.TestCase, ReporterMixin):
    """
    Functional MESI test suite.

    Testing approach
    1. Each subcase creates a fresh system when it needs cold cache preconditions.
       This prevents earlier subcases from contaminating later subcases.
    2. Many tests use cross products of:
       multiple line sizes
       multiple addresses and offsets
       multiple values
    3. We validate both:
       returned data correctness
       legal MESI state combinations
       expected bus events when appropriate
    """

    def make_system(self, line_size: int, cap_lines: int, mem_size: int):
        """
        Create a new isolated system for a subcase.

        mem_size must be a multiple of line_size so line boundaries are well behaved.
        """
        if mem_size % line_size != 0:
            raise ValueError("mem_size must be a multiple of line_size")

        mem = StrictMemoryPool(size=mem_size, base_addr=0x1000)
        init_memory_pattern(mem)

        bus = Bus(mem, line_size=line_size, verbose=False)
        c0 = Cache(
            "C0",
            bus,
            base_addr=mem.BASE_ADDR,
            line_size=line_size,
            capacity_lines=cap_lines,
            verbose=False,
        )
        c1 = Cache(
            "C1",
            bus,
            base_addr=mem.BASE_ADDR,
            line_size=line_size,
            capacity_lines=cap_lines,
            verbose=False,
        )
        return mem, bus, c0, c1

    def address_vectors(self, mem_base: int, line_size: int, mem_size: int):
        """
        Generate a set of representative addresses.

        We include:
        first line base and offsets
        a couple middle line bases
        the last line base
        several offsets inside each line

        This catches corner cases where alignment and offsets are wrong.
        """
        last_addr = mem_base + mem_size - 1
        last_line_base = last_addr - (last_addr % line_size)

        bases = [mem_base, mem_base + line_size, mem_base + 2 * line_size, last_line_base]
        offsets = [0, 1, line_size // 2, line_size - 1]

        out = []
        for b in bases:
            for off in offsets:
                a = b + off
                if mem_base <= a <= last_addr:
                    out.append(a)
        return out

    def value_vectors(self):
        """
        Values chosen to include boundaries and typical byte patterns.
        """
        return [0x00, 0x01, 0x7F, 0x80, 0xFE, 0xFF]

    def configs(self):
        """
        Test multiple line sizes to catch alignment and base math bugs.
        """
        return [(4, 4, 64), (8, 4, 64), (16, 4, 64)]

    def test_read_miss_I_to_E_many_vectors(self):
        """
        Test: a cold read miss on an address where no other cache has the line
        Expected: requester installs E, other remains I
        """
        group = "read miss I to E"
        for line_size, cap_lines, mem_size in self.configs():
            addrs = self.address_vectors(0x1000, line_size, mem_size)
            total = len(addrs)
            idx = 0

            for addr in addrs:
                idx += 1

                def run():
                    mem, bus, c0, c1 = self.make_system(line_size, cap_lines, mem_size)

                    exp = mem_read_byte(mem, addr)
                    got = c0.read_byte(addr)
                    self.assertEqual(got, exp)

                    self.assertEqual(c0.peek_state(addr), State.E)
                    self.assertEqual(c1.peek_state(addr), State.I)

                    # BusRd should occur on the miss and not again on the second read
                    stats = bus.get_stats()
                    self.assertEqual(stats["busrd"], 1)
                    self.assertEqual(stats["writebacks"], 0)

                    got2 = c0.read_byte(addr)
                    self.assertEqual(got2, exp)
                    self.assertEqual(bus.get_stats()["busrd"], 1)

                    assert_system_invariants(c0, c1)

                label = f"line_size={line_size} addr={hex(addr)} expect E in reader"
                self.report_case(group, idx, total, label, run)

    def test_second_reader_E_to_S_many_vectors(self):
        """
        Test: two cores read the same cold line
        Expected: first gets E, then second read forces both to S
        """
        group = "second reader E to S"
        for line_size, cap_lines, mem_size in self.configs():
            addrs = self.address_vectors(0x1000, line_size, mem_size)
            total = len(addrs)
            idx = 0

            for addr in addrs:
                idx += 1

                def run():
                    mem, bus, c0, c1 = self.make_system(line_size, cap_lines, mem_size)

                    exp = mem_read_byte(mem, addr)

                    self.assertEqual(c0.read_byte(addr), exp)
                    self.assertEqual(c0.peek_state(addr), State.E)

                    self.assertEqual(c1.read_byte(addr), exp)

                    self.assertEqual(c0.peek_state(addr), State.S)
                    self.assertEqual(c1.peek_state(addr), State.S)

                    stats = bus.get_stats()
                    self.assertEqual(stats["busrd"], 2)

                    assert_system_invariants(c0, c1)

                label = f"line_size={line_size} addr={hex(addr)} E then shared read gives S S"
                self.report_case(group, idx, total, label, run)

    def test_write_hit_E_to_M_many_vectors(self):
        """
        Test: writer has E and performs a write
        Expected: silent transition E to M and data updates
        """
        group = "write hit E to M"
        values = self.value_vectors()
        for line_size, cap_lines, mem_size in self.configs():
            addrs = self.address_vectors(0x1000, line_size, mem_size)
            total = len(addrs) * len(values)
            idx = 0

            for addr in addrs:
                for value in values:
                    idx += 1

                    def run():
                        mem, bus, c0, c1 = self.make_system(line_size, cap_lines, mem_size)

                        c0.read_byte(addr)
                        self.assertEqual(c0.peek_state(addr), State.E)

                        # No bus upgrade needed for E to M
                        before = bus.get_stats()
                        c0.write_byte(addr, value)

                        self.assertEqual(c0.peek_state(addr), State.M)
                        self.assertEqual(c1.peek_state(addr), State.I)
                        self.assertEqual(c0.read_byte(addr), value)

                        after = bus.get_stats()
                        self.assertEqual(after["busupgr"], before["busupgr"])
                        self.assertEqual(after["busrdx"], before["busrdx"])

                        assert_system_invariants(c0, c1)

                    label = f"line_size={line_size} addr={hex(addr)} value={value} E then write gives M"
                    self.report_case(group, idx, total, label, run)

    def test_write_hit_S_to_M_upgrade_many_vectors(self):
        """
        Test: both caches share S, then one writes
        Expected: writer issues BusUpgr, becomes M, other becomes I
        A subsequent read by the other should see the written value and move both to S.
        """
        group = "write hit S to M via upgrade"
        values = self.value_vectors()
        for line_size, cap_lines, mem_size in self.configs():
            addrs = self.address_vectors(0x1000, line_size, mem_size)
            total = len(addrs) * len(values)
            idx = 0

            for addr in addrs:
                for value in values:
                    idx += 1

                    def run():
                        mem, bus, c0, c1 = self.make_system(line_size, cap_lines, mem_size)

                        exp = mem_read_byte(mem, addr)

                        self.assertEqual(c0.read_byte(addr), exp)
                        self.assertEqual(c1.read_byte(addr), exp)
                        self.assertEqual(c0.peek_state(addr), State.S)
                        self.assertEqual(c1.peek_state(addr), State.S)

                        before_upgr = bus.get_stats()["busupgr"]
                        before_inv = bus.get_stats()["invalidations"]

                        c0.write_byte(addr, value)

                        self.assertEqual(c0.peek_state(addr), State.M)
                        self.assertEqual(c1.peek_state(addr), State.I)

                        self.assertEqual(bus.get_stats()["busupgr"], before_upgr + 1)
                        self.assertGreaterEqual(bus.get_stats()["invalidations"], before_inv + 1)

                        got_other = c1.read_byte(addr)
                        self.assertEqual(got_other, value)

                        self.assertEqual(c0.peek_state(addr), State.S)
                        self.assertEqual(c1.peek_state(addr), State.S)

                        assert_system_invariants(c0, c1)

                    label = f"line_size={line_size} addr={hex(addr)} value={value} S S then writer upgrades to M"
                    self.report_case(group, idx, total, label, run)

    def test_write_miss_I_to_M_many_vectors_all_other_states(self):
        """
        Test: write miss scenarios where the other cache may hold the line in various states.

        Cases
        other I
        other E
        other S but writer does not currently have the line due to eviction
        other M

        The last case is especially important because it requires a writeback on the bus.
        """
        group = "write miss I to M with other states"
        configs = [(8, 4, 64), (16, 4, 64)]
        values = self.value_vectors()

        for line_size, cap_lines, mem_size in configs:
            addrs = self.address_vectors(0x1000, line_size, mem_size)
            total = len(addrs) * len(values) * 4
            idx = 0

            for addr in addrs:
                for value in values:
                    idx += 1

                    def run_other_I():
                        mem, bus, c0, c1 = self.make_system(line_size, cap_lines, mem_size)

                        c1.write_byte(addr, value)
                        self.assertEqual(c1.peek_state(addr), State.M)
                        self.assertEqual(c0.peek_state(addr), State.I)
                        self.assertEqual(c0.read_byte(addr), value)

                        assert_system_invariants(c0, c1)

                    label = f"case other I line_size={line_size} addr={hex(addr)} value={value}"
                    self.report_case(group, idx, total, label, run_other_I)

                    idx += 1

                    def run_other_E():
                        mem, bus, c0, c1 = self.make_system(line_size, cap_lines, mem_size)

                        c0.read_byte(addr)
                        self.assertEqual(c0.peek_state(addr), State.E)

                        c1.write_byte(addr, value)

                        self.assertEqual(c1.peek_state(addr), State.M)
                        self.assertEqual(c0.peek_state(addr), State.I)
                        self.assertEqual(c0.read_byte(addr), value)

                        assert_system_invariants(c0, c1)

                    label = f"case other E line_size={line_size} addr={hex(addr)} value={value}"
                    self.report_case(group, idx, total, label, run_other_E)

                    idx += 1

                    def run_other_S_writer_missing():
                        """
                        This case forces the writer to lose its S copy via eviction.

                        The key detail is that the eviction address must be on a different line
                        than the target address, otherwise it will not evict the target line.
                        """
                        mem, bus, c0, c1 = self.make_system(line_size, cap_lines=1, mem_size=mem_size)

                        c0.read_byte(addr)
                        c1.read_byte(addr)
                        self.assertEqual(c0.peek_state(addr), State.S)
                        self.assertEqual(c1.peek_state(addr), State.S)

                        tgt_base = line_base(mem.BASE_ADDR, addr, line_size)

                        # Choose a guaranteed different line base
                        candidate = tgt_base + line_size
                        last_addr = mem.BASE_ADDR + mem.SIZE - 1
                        if candidate > last_addr:
                            candidate = tgt_base - line_size

                        other_line = candidate
                        other_base = line_base(mem.BASE_ADDR, other_line, line_size)
                        self.assertNotEqual(other_base, tgt_base)

                        # With capacity 1, touching a different line forces eviction
                        c1.read_byte(other_line)
                        self.assertEqual(c1.peek_state(addr), State.I)

                        c1.write_byte(addr, value)

                        self.assertEqual(c1.peek_state(addr), State.M)
                        self.assertEqual(c0.peek_state(addr), State.I)
                        self.assertEqual(c0.read_byte(addr), value)

                        assert_system_invariants(c0, c1)

                    label = f"case other S writer missing line_size={line_size} addr={hex(addr)} value={value}"
                    self.report_case(group, idx, total, label, run_other_S_writer_missing)

                    idx += 1

                    def run_other_M():
                        mem, bus, c0, c1 = self.make_system(line_size, cap_lines, mem_size)

                        old = mem_read_byte(mem, addr)
                        c0.write_byte(addr, old ^ 0xAA)
                        self.assertEqual(c0.peek_state(addr), State.M)

                        before_wb = bus.get_stats()["writebacks"]
                        c1.write_byte(addr, value)
                        self.assertEqual(bus.get_stats()["writebacks"], before_wb + 1)

                        self.assertEqual(c1.peek_state(addr), State.M)
                        self.assertEqual(c0.peek_state(addr), State.I)

                        self.assertEqual(mem_read_byte(mem, addr), old ^ 0xAA)
                        self.assertEqual(c0.read_byte(addr), value)

                        assert_system_invariants(c0, c1)

                    label = f"case other M line_size={line_size} addr={hex(addr)} value={value}"
                    self.report_case(group, idx, total, label, run_other_M)

    def test_eviction_writeback_corner_cases(self):
        """
        Test: eviction must write back if the evicted line is M.

        We force evictions by setting cache capacity to 1 line and then touching two line bases.
        """
        group = "eviction writeback corner cases"
        configs = [(8, 1, 64), (16, 1, 64)]
        values = self.value_vectors()

        for line_size, cap_lines, mem_size in configs:
            a1 = 0x1000 + 1
            a2 = 0x1000 + 2 * line_size + 1

            total = len(values) * len(values)
            idx = 0

            for v1 in values:
                for v2 in values:
                    idx += 1

                    def run():
                        mem, bus, c0, c1 = self.make_system(line_size, cap_lines, mem_size)

                        c0.write_byte(a1, v1)
                        self.assertEqual(c0.peek_state(a1), State.M)

                        c0.write_byte(a2, v2)

                        # After eviction, memory should contain the v1 writeback
                        self.assertEqual(mem_read_byte(mem, a1), v1)
                        self.assertEqual(c0.peek_state(a2), State.M)
                        self.assertEqual(c0.peek_state(a1), State.I)

                        c0_stats = c0.get_stats()
                        self.assertEqual(c0_stats["evictions"], 1)
                        self.assertEqual(c0_stats["eviction_writebacks"], 1)

                        assert_system_invariants(c0, c1)

                    label = f"line_size={line_size} v1={v1} v2={v2} evict M must write back"
                    self.report_case(group, idx, total, label, run)

    def test_boundary_addresses_many_values(self):
        """
        Test: first and last byte addresses in memory.

        These are common edge cases for address math and line alignment.
        """
        group = "boundary addresses"
        configs = [(8, 4, 64), (16, 4, 64)]
        values = self.value_vectors()

        for line_size, cap_lines, mem_size in configs:
            addrs = [0x1000, 0x1000 + mem_size - 1]
            total = len(addrs) * len(values)
            idx = 0

            for addr in addrs:
                for value in values:
                    idx += 1

                    def run():
                        mem, bus, c0, c1 = self.make_system(line_size, cap_lines, mem_size)

                        c0.write_byte(addr, value)
                        self.assertEqual(c0.read_byte(addr), value)

                        got = c1.read_byte(addr)
                        self.assertEqual(got, value)

                        assert_system_invariants(c0, c1)

                    label = f"line_size={line_size} addr={hex(addr)} value={value} boundary read write"
                    self.report_case(group, idx, total, label, run)

    def test_random_stress_trace_deterministic(self):
        """
        Stress test with a deterministic random seed.

        Purpose
        Catch rare interleavings and sequences not covered by structured tests.
        The test maintains its own truth dictionary of last writes per address.

        Optional printing behavior
        MESI_TRACE_STRESS=1 prints every step as a reported iteration.
        Otherwise it prints progress every N steps controlled by MESI_STRESS_PRINT_EVERY.
        """
        group = "random deterministic stress"
        line_size = 8
        mem_size = 256
        mem, bus, c0, c1 = self.make_system(line_size=line_size, cap_lines=8, mem_size=mem_size)

        rng = random.Random(20260202)
        truth = {mem.BASE_ADDR + i: mem_read_byte(mem, mem.BASE_ADDR + i) for i in range(mem.SIZE)}

        steps = 800
        trace_each_step = os.environ.get("MESI_TRACE_STRESS", "0") == "1"
        print_every = int(os.environ.get("MESI_STRESS_PRINT_EVERY", "25"))

        for step in range(1, steps + 1):

            def run_step():
                cache = c0 if rng.randint(0, 1) == 0 else c1
                addr = mem.BASE_ADDR + rng.randint(0, mem.SIZE - 1)

                # 45 percent reads, 55 percent writes
                if rng.random() < 0.45:
                    got = cache.read_byte(addr)
                    exp = truth[addr]
                    self.assertEqual(got, exp)
                else:
                    value = rng.randint(0, 255)
                    cache.write_byte(addr, value)
                    truth[addr] = value & 0xFF

                assert_system_invariants(c0, c1)

            if trace_each_step:
                label = f"step={step} of {steps}"
                self.report_case(group, step, steps, label, run_step)
            else:
                run_step()
                if step % print_every == 0:
                    print(f"[{group}] progress step {step} of {steps}  RESULT OK")


if __name__ == "__main__":
    unittest.main(verbosity=2)

