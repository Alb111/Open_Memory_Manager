"""
Test Suite for MSI Cache Coherence Protocol

This test suite verifies the correctness of the MSI protocol implementation
by testing various scenarios and edge cases.

Test Categories:
1. Basic State Transitions - Single cache operations
2. Cache-to-Cache Transfers - Data sharing and ownership transfer
3. Write Upgrade - SHARED to MODIFIED transitions
4. Evictions - Clean and dirty evictions
5. Protocol Invariants - MSI rules are never violated
6. Stress Tests - Complex multi-operation scenarios

Author: Rishi & Nick
Date: 2/8/25
"""

from msi import (
    MSIState,
    ProcessorEvent,
    SnoopEvent,
    CoherenceCmd,
    axi_request,
    on_processor_event,
    on_snoop_event,
)
from cache import CacheController
from directory import DirectoryController


# ============================================================================
# Test Utilities
# ============================================================================

class TestSystem:
    """Complete test system with 2 caches and directory."""
    
    def __init__(self):
        """Initialize test system."""
        self.directory = DirectoryController(num_cores=2)
        self.cache0 = CacheController(0, self.directory.axi_handler)
        self.cache1 = CacheController(1, self.directory.axi_handler)
        
        # Register caches with directory
        self.directory.register_cache(0, self.cache0.axi_handler)
        self.directory.register_cache(1, self.cache1.axi_handler)
    
    def cpu_read(self, cache_id: int, addr: int) -> int:
        """Simulate CPU read."""
        cache = self.cache0 if cache_id == 0 else self.cache1
        req = axi_request(
            mem_valid=True,
            mem_instr=False,
            mem_addr=addr,
            mem_wstrb=0,  # Read
        )
        resp = cache.axi_handler(req)
        assert resp.mem_ready, f"Cache {cache_id} read not ready"
        return resp.mem_rdata
    
    def cpu_write(self, cache_id: int, addr: int, data: int) -> None:
        """Simulate CPU write."""
        cache = self.cache0 if cache_id == 0 else self.cache1
        req = axi_request(
            mem_valid=True,
            mem_instr=False,
            mem_addr=addr,
            mem_wdata=data,
            mem_wstrb=0xF,  # Write all bytes
        )
        resp = cache.axi_handler(req)
        assert resp.mem_ready, f"Cache {cache_id} write not ready"
    
    def get_cache_state(self, cache_id: int, addr: int) -> MSIState:
        """Get cache line state."""
        cache = self.cache0 if cache_id == 0 else self.cache1
        line = cache._line(addr)
        return line.state
    
    def get_directory_state(self, addr: int):
        """Get directory state."""
        entry = self.directory._entry(addr)
        return entry.state, entry.sharers
    
    def get_memory(self, addr: int) -> int:
        """Get memory value."""
        return self.directory.memory.get(addr, 0)
    
    def verify_invariants(self, addr: int) -> bool:
        """
        Verify MSI protocol invariants.
        
        Invariants:
        1. At most one cache can be MODIFIED
        2. If one cache is MODIFIED, all others must be INVALID
        3. Multiple caches can be SHARED
        """
        state0 = self.get_cache_state(0, addr)
        state1 = self.get_cache_state(1, addr)
        
        # Check no two caches are MODIFIED
        if state0 == MSIState.MODIFIED and state1 == MSIState.MODIFIED:
            print(f"INVARIANT VIOLATION: Both caches MODIFIED for {addr:#x}")
            return False
        
        # Check MODIFIED implies others are INVALID
        if state0 == MSIState.MODIFIED and state1 != MSIState.INVALID:
            print(f"INVARIANT VIOLATION: Cache0 MODIFIED but Cache1 is {state1.name}")
            return False
        
        if state1 == MSIState.MODIFIED and state0 != MSIState.INVALID:
            print(f"INVARIANT VIOLATION: Cache1 MODIFIED but Cache0 is {state0.name}")
            return False
        
        return True


def print_test_header(test_name: str):
    """Print formatted test header."""
    print(f"\n{'='*70}")
    print(f"TEST: {test_name}")
    print(f"{'='*70}")


def print_state(system: TestSystem, addr: int, label: str = ""):
    """Print current state of system."""
    if label:
        print(f"\n{label}:")
    dir_state, sharers = system.get_directory_state(addr)
    mem = system.get_memory(addr)
    system.cache0.dump_cache()
    system.cache1.dump_cache()
    print(f"  Directory: state={dir_state.name}, sharers={sharers:#04b}")
    print(f"  Memory: {mem:#010x}")


# ============================================================================
# Test 1: Basic State Transitions
# ============================================================================

def test_basic_read_miss():
    """Test: Cache read miss (I → S)."""
    print_test_header("Basic Read Miss (I → S)")
    
    system = TestSystem()
    addr = 0x1000
    
    # Initialize memory
    system.directory.memory[addr] = 0xDEADBEEF
    print_state(system, addr, "Initial")
    
    # Cache 0 reads
    print("\nCache 0 reads address...")
    data = system.cpu_read(0, addr)
    print_state(system, addr, "After read")
    
    # Verify
    assert data == 0xDEADBEEF, f"Data mismatch: {data:#x}"
    assert system.get_cache_state(0, addr) == MSIState.SHARED
    assert system.verify_invariants(addr)
    print("✓ PASSED")


def test_basic_write_miss():
    """Test: Cache write miss (I → M)."""
    print_test_header("Basic Write Miss (I → M)")
    
    system = TestSystem()
    addr = 0x2000
    
    print_state(system, addr, "Initial")
    
    # Cache 0 writes
    print("\nCache 0 writes value...")
    system.cpu_write(0, addr, 0xCAFEBABE)
    print_state(system, addr, "After write")
    
    # Verify
    assert system.get_cache_state(0, addr) == MSIState.MODIFIED
    assert system.verify_invariants(addr)
    print("✓ PASSED")


def test_read_hit():
    """Test: Read hit in SHARED state."""
    print_test_header("Read Hit (S → S)")
    
    system = TestSystem()
    addr = 0x3000
    
    # Setup: Cache 0 reads first
    system.directory.memory[addr] = 0x12345678
    system.cpu_read(0, addr)
    print_state(system, addr, "After first read")
    
    # Read again (should hit)
    print("\nCache 0 reads again...")
    data = system.cpu_read(0, addr)
    print_state(system, addr, "After second read")
    
    # Verify
    assert data == 0x12345678
    assert system.get_cache_state(0, addr) == MSIState.SHARED
    assert system.verify_invariants(addr)
    print("✓ PASSED")


def test_write_hit():
    """Test: Write hit in MODIFIED state."""
    print_test_header("Write Hit (M → M)")
    
    system = TestSystem()
    addr = 0x4000
    
    # Setup: Cache 0 writes first
    system.cpu_write(0, addr, 0xAAAAAAAA)
    print_state(system, addr, "After first write")
    
    # Write again (should hit)
    print("\nCache 0 writes again...")
    system.cpu_write(0, addr, 0xBBBBBBBB)
    print_state(system, addr, "After second write")
    
    # Verify
    assert system.get_cache_state(0, addr) == MSIState.MODIFIED
    line = system.cache0._line(addr)
    assert line.data == 0xBBBBBBBB
    assert system.verify_invariants(addr)
    print("✓ PASSED")


# ============================================================================
# Test 2: Cache-to-Cache Transfers
# ============================================================================

def test_sharing():
    """Test: Two caches sharing data."""
    print_test_header("Cache Sharing (Both in SHARED)")
    
    system = TestSystem()
    addr = 0x5000
    system.directory.memory[addr] = 0x11111111
    
    # Cache 0 reads
    print("\nCache 0 reads...")
    data0 = system.cpu_read(0, addr)
    print_state(system, addr, "After Cache 0 read")
    
    # Cache 1 reads (should share)
    print("\nCache 1 reads...")
    data1 = system.cpu_read(1, addr)
    print_state(system, addr, "After Cache 1 read")
    
    # Verify
    assert data0 == data1 == 0x11111111
    assert system.get_cache_state(0, addr) == MSIState.SHARED
    assert system.get_cache_state(1, addr) == MSIState.SHARED
    dir_state, sharers = system.get_directory_state(addr)
    assert sharers == 0b11  # Both caches
    assert system.verify_invariants(addr)
    print("✓ PASSED")


def test_modified_to_shared():
    """Test: MODIFIED cache shares data (M → S on snoop)."""
    print_test_header("Modified to Shared (M → S via flush)")
    
    system = TestSystem()
    addr = 0x6000
    
    # Cache 0 writes (goes to MODIFIED)
    print("\nCache 0 writes...")
    system.cpu_write(0, addr, 0x22222222)
    print_state(system, addr, "After Cache 0 write")
    
    # Cache 1 reads (should get data from Cache 0)
    print("\nCache 1 reads (triggers flush from Cache 0)...")
    data = system.cpu_read(1, addr)
    print_state(system, addr, "After Cache 1 read")
    
    # Verify
    assert data == 0x22222222
    assert system.get_cache_state(0, addr) == MSIState.SHARED  # Downgraded
    assert system.get_cache_state(1, addr) == MSIState.SHARED
    assert system.get_memory(addr) == 0x22222222  # Memory updated
    assert system.verify_invariants(addr)
    print("✓ PASSED")


def test_ownership_transfer():
    """Test: Ownership transfer (M → I, other cache gets M)."""
    print_test_header("Ownership Transfer (M → I → M)")
    
    system = TestSystem()
    addr = 0x7000
    
    # Cache 0 writes
    print("\nCache 0 writes...")
    system.cpu_write(0, addr, 0x33333333)
    print_state(system, addr, "After Cache 0 write")
    
    # Cache 1 writes (should invalidate Cache 0)
    print("\nCache 1 writes (triggers ownership transfer)...")
    system.cpu_write(1, addr, 0x44444444)
    print_state(system, addr, "After Cache 1 write")
    
    # Verify
    assert system.get_cache_state(0, addr) == MSIState.INVALID
    assert system.get_cache_state(1, addr) == MSIState.MODIFIED
    assert system.get_memory(addr) == 0x33333333  # Old data flushed
    assert system.verify_invariants(addr)
    print("✓ PASSED")


# ============================================================================
# Test 3: Write Upgrade (BUS_UPGR)
# ============================================================================

def test_write_upgrade():
    """Test: Write upgrade from SHARED to MODIFIED."""
    print_test_header("Write Upgrade (S → M via BUS_UPGR)")
    
    system = TestSystem()
    addr = 0x8000
    system.directory.memory[addr] = 0x55555555
    
    # Both caches read (both SHARED)
    print("\nBoth caches read...")
    system.cpu_read(0, addr)
    system.cpu_read(1, addr)
    print_state(system, addr, "After both read")
    
    # Cache 0 writes (should upgrade, invalidate Cache 1)
    print("\nCache 0 writes (BUS_UPGR)...")
    system.cpu_write(0, addr, 0x66666666)
    print_state(system, addr, "After Cache 0 write")
    
    # Verify
    assert system.get_cache_state(0, addr) == MSIState.MODIFIED
    assert system.get_cache_state(1, addr) == MSIState.INVALID
    assert system.verify_invariants(addr)
    print("✓ PASSED")


# ============================================================================
# Test 4: Evictions
# ============================================================================

def test_evict_clean():
    """Test: Evict SHARED line."""
    print_test_header("Clean Eviction (SHARED)")
    
    system = TestSystem()
    addr = 0x9000
    system.directory.memory[addr] = 0x77777777
    
    # Cache 0 reads
    system.cpu_read(0, addr)
    print_state(system, addr, "After read")
    
    # Evict
    print("\nCache 0 evicts...")
    system.cache0.evict(addr)
    print_state(system, addr, "After eviction")
    
    # Verify
    assert system.get_cache_state(0, addr) == MSIState.INVALID
    dir_state, sharers = system.get_directory_state(addr)
    assert sharers == 0  # No sharers left
    assert system.verify_invariants(addr)
    print("✓ PASSED")


def test_evict_dirty():
    """Test: Evict MODIFIED line (writeback)."""
    print_test_header("Dirty Eviction (MODIFIED)")
    
    system = TestSystem()
    addr = 0xA000
    
    # Cache 0 writes
    system.cpu_write(0, addr, 0x88888888)
    print_state(system, addr, "After write")
    
    # Evict (should writeback)
    print("\nCache 0 evicts (writeback)...")
    system.cache0.evict(addr)
    print_state(system, addr, "After eviction")
    
    # Verify
    assert system.get_cache_state(0, addr) == MSIState.INVALID
    assert system.get_memory(addr) == 0x88888888  # Written back
    assert system.verify_invariants(addr)
    print("✓ PASSED")


# ============================================================================
# Test 5: State Machine Unit Tests
# ============================================================================

def test_state_machine():
    """Test: State machine transition functions."""
    print_test_header("State Machine Unit Tests")
    
    # Test processor events
    print("\nTesting on_processor_event()...")
    
    # I + PR_RD → S
    tr = on_processor_event(MSIState.INVALID, ProcessorEvent.PR_RD)
    assert tr.next_state == MSIState.SHARED
    assert tr.issue_cmd == CoherenceCmd.BUS_RD
    print("  ✓ I + PR_RD → S (BUS_RD)")
    
    # I + PR_WR → M
    tr = on_processor_event(MSIState.INVALID, ProcessorEvent.PR_WR)
    assert tr.next_state == MSIState.MODIFIED
    assert tr.issue_cmd == CoherenceCmd.BUS_RDX
    print("  ✓ I + PR_WR → M (BUS_RDX)")
    
    # S + PR_WR → M
    tr = on_processor_event(MSIState.SHARED, ProcessorEvent.PR_WR)
    assert tr.next_state == MSIState.MODIFIED
    assert tr.issue_cmd == CoherenceCmd.BUS_UPGR
    print("  ✓ S + PR_WR → M (BUS_UPGR)")
    
    # Test snoop events
    print("\nTesting on_snoop_event()...")
    
    # M + BUS_RD → S (flush)
    tr = on_snoop_event(MSIState.MODIFIED, SnoopEvent.BUS_RD)
    assert tr.next_state == MSIState.SHARED
    assert tr.flush == True
    print("  ✓ M + BUS_RD → S (flush)")
    
    # M + BUS_RDX → I (flush)
    tr = on_snoop_event(MSIState.MODIFIED, SnoopEvent.BUS_RDX)
    assert tr.next_state == MSIState.INVALID
    assert tr.flush == True
    print("  ✓ M + BUS_RDX → I (flush)")
    
    # S + BUS_RDX → I
    tr = on_snoop_event(MSIState.SHARED, SnoopEvent.BUS_RDX)
    assert tr.next_state == MSIState.INVALID
    assert tr.flush == False
    print("  ✓ S + BUS_RDX → I (no flush)")
    
    print("\n✓ ALL STATE MACHINE TESTS PASSED")


# ============================================================================
# Test 6: Complex Scenarios
# ============================================================================

def test_ping_pong():
    """Test: Ping-pong writes between caches."""
    print_test_header("Ping-Pong Writes")
    
    system = TestSystem()
    addr = 0xB000
    
    for i in range(5):
        cache_id = i % 2
        value = 0x1000 + i
        
        print(f"\nIteration {i}: Cache {cache_id} writes {value:#x}")
        system.cpu_write(cache_id, addr, value)
        
        # Verify exclusive ownership
        assert system.get_cache_state(cache_id, addr) == MSIState.MODIFIED
        assert system.get_cache_state(1 - cache_id, addr) == MSIState.INVALID
        assert system.verify_invariants(addr)
    
    print("\n✓ PASSED")


def test_read_write_read():
    """Test: Complex read-write-read pattern."""
    print_test_header("Read-Write-Read Pattern")
    
    system = TestSystem()
    addr = 0xC000
    system.directory.memory[addr] = 0xAAAAAAAA
    
    # Both caches read
    print("\n1. Both caches read...")
    d0 = system.cpu_read(0, addr)
    d1 = system.cpu_read(1, addr)
    assert d0 == d1 == 0xAAAAAAAA
    print_state(system, addr, "After reads")
    
    # Cache 0 writes
    print("\n2. Cache 0 writes...")
    system.cpu_write(0, addr, 0xBBBBBBBB)
    print_state(system, addr, "After write")
    
    # Cache 1 reads (should get new value)
    print("\n3. Cache 1 reads...")
    d1 = system.cpu_read(1, addr)
    assert d1 == 0xBBBBBBBB
    print_state(system, addr, "After final read")
    
    # Verify both SHARED
    assert system.get_cache_state(0, addr) == MSIState.SHARED
    assert system.get_cache_state(1, addr) == MSIState.SHARED
    assert system.verify_invariants(addr)
    print("✓ PASSED")


def test_test():
    print_test_header("Nick's Test")

    system = TestSystem()
    addr = 0xD000
    system.directory.memory[addr] = 0xDEADDEAD

    print("\n Caches reading")

    g0 = system.cpu_read(0, addr)
    assert g0 == 0xDEADDEAD
    print_state(system, addr, "WTF")

    system.cpu_write(1, addr, 0xABCDEF01)
    print_state(system, addr, "WTF2")

# ============================================================================
# Main Test Runner
# ============================================================================

def run_all_tests():
    """Run all tests."""
    print("\n" + "="*70)
    print("MSI CACHE COHERENCE PROTOCOL - TEST SUITE")
    print("="*70)
    
    tests = [
        # Basic transitions
        test_basic_read_miss,
        test_basic_write_miss,
        test_read_hit,
        test_write_hit,
        
        # Cache-to-cache
        test_sharing,
        test_modified_to_shared,
        test_ownership_transfer,
        
        # Write upgrade
        test_write_upgrade,
        
        # Evictions
        test_evict_clean,
        test_evict_dirty,
        
        # State machine
        test_state_machine,
        
        # Complex scenarios
        test_ping_pong,
        test_read_write_read,
        test_test,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"\n✗ FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"\n✗ ERROR: {e}")
            failed += 1
    
    # Summary
    print("\n" + "="*70)
    print(f"TEST SUMMARY: {passed} passed, {failed} failed")
    print("="*70)
    
    if failed == 0:
        print("\n🎉 ALL TESTS PASSED! System is functionally correct.")
    else:
        print(f"\n⚠️  {failed} test(s) failed. Please review.")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
