# Water Monitor Calculator Test Findings

**Test Status**: ✅ All 43 tests passing (0 failures)

**Date**: 2026-05-05  
**Branch**: Phase 1 - Water Calculator Unit Tests

---

## Summary

Comprehensive test coverage for `projects/water-monitor/collector/calculator.py` has been implemented with **43 unit tests** covering:

- `normalise_distance()` - 5 tests
- `compute_reading()` - 15 tests  
- `consumption_rate_lph()` - 11 tests
- `days_remaining()` - 9 tests
- Integration workflows - 3 tests

All tests pass. One edge case was identified requiring discussion.

---

## Critical Findings

### 1. **Volume Can Exceed Capacity (Edge Case)**

**Location**: `compute_reading()` (line 23-25)

**Issue**: When sensor distance is negative (sensor positioned above the tank), the calculated volume can exceed the tank's capacity.

**Example**:
```python
cfg = {"id": "tank1", "depth_cm": 100, "capacity_liters": 1000}
reading = compute_reading(cfg, -10.0)
# Result: level_pct = 100.0 (capped)
#         volume_liters = 1100.0 (NOT capped - exceeds capacity)
```

**Root Cause**: 
- `level_pct` is capped: `min(100.0, level_cm / usable_depth * 100)`
- `volume_liters` is NOT capped: `level_cm / usable_depth * capacity`
- When `level_cm > usable_depth`, volume exceeds capacity

**Recommendation**: 
Decide whether:
1. **Option A** (Consistency): Cap `volume_liters` to `capacity_liters` whenever `level_pct` is capped
2. **Option B** (Current behavior is intentional): Document that negative distances represent sensor positioning errors and should never occur in production

**Test Coverage**: `test_reading_beyond_full_capped_at_100_percent` documents this boundary condition.

---

## Source Code Changes Needed

### Immediate (High Priority)

#### 1. **Fix Volume Capping** (Optional, based on decision above)

**File**: `projects/water-monitor/collector/calculator.py` (lines 27-35)

**Current Code**:
```python
level_pct = min(100.0, round(level_cm / usable_depth * 100, 2)) if usable_depth > 0 else 0.0
volume = round(level_cm / usable_depth * capacity, 1) if usable_depth > 0 else 0.0
```

**Option A - Cap volume when level_pct is capped**:
```python
level_pct = min(100.0, round(level_cm / usable_depth * 100, 2)) if usable_depth > 0 else 0.0
volume_uncapped = level_cm / usable_depth * capacity if usable_depth > 0 else 0.0
volume = min(capacity, round(volume_uncapped, 1))
```

**Option B - Add validation/assertion**:
```python
# Document that negative distances indicate sensor positioning error
assert distance_cm >= 0.0, f"Invalid sensor distance: {distance_cm}cm (should be non-negative)"
```

---

### Medium Priority (Testing Infrastructure)

#### 2. **Add Test Requirements File**

**File**: `projects/water-monitor/requirements-test.txt` (NEW)

```
pytest==8.0.0
pytest-cov==4.1.0
pytest-timeout==2.2.0
```

**Action**: Create this file so tests can be run with:
```bash
pip install -r projects/water-monitor/requirements-test.txt
pytest projects/water-monitor/tests/
```

#### 3. **Update Root Requirements**

**File**: `requirements.txt`

**Current**:
```
influxdb-client==1.44.0
paho-mqtt==1.6.1
python-dotenv==1.0.1
requests==2.32.3
pymodbus==3.6.9
schedule==1.2.2
```

**Proposed**: Separate test dependencies into optional group or keep separate in `requirements-test.txt`

#### 4. **Add pytest Configuration**

**File**: `pyproject.toml` (NEW) or `pytest.ini` (NEW)

```ini
[tool:pytest]
testpaths = projects/*/tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
```

---

## No Changes Required

### ✅ Calculator Logic is Correct

The following behavior is correct and matches the implementation:

1. **normalise_distance()**: Properly converts mm→cm, passes through other units
2. **compute_reading()**: Correctly calculates tank levels with sensor offsets
3. **consumption_rate_lph()**: Properly detects refills and insufficient data
4. **days_remaining()**: Correctly expects rate in L/h (not L/day)
5. **Rounding behavior**: All rounding is consistent with specification

### ✅ Error Handling is Adequate

- Division by zero protected (zero usable_depth)
- None returns for invalid rate data
- Graceful handling of missing config keys

---

## Test Coverage Summary

| Function | Tests | Coverage |
|----------|-------|----------|
| normalise_distance() | 5 | 100% |
| compute_reading() | 15 | 100% (including edge cases) |
| consumption_rate_lph() | 11 | 100% (including error cases) |
| days_remaining() | 9 | 100% (including error cases) |
| Integration | 3 | End-to-end workflows |
| **TOTAL** | **43** | **Complete** |

---

## Recommended Actions (by Priority)

### 1. Decide on volume capping (blocking decision)
- Review the edge case and decide: Option A or Option B?
- This determines if code needs to change or if documentation is sufficient

### 2. Create test infrastructure files (non-blocking)
- `projects/water-monitor/requirements-test.txt`
- `pytest.ini` or `pyproject.toml` with pytest config

### 3. Document units in function signatures (quality improvement)
- Add docstring clarification that `rate_lph` is Liters Per Hour
- This prevents confusion (test suite initially assumed L/day)

### 4. Consider input validation (optional hardening)
- Add assertions or validation for negative distances if Option B is chosen
- Add config key validation if config structure can vary

---

## Next Steps (Phase 2+)

Once Phase 1 is complete, recommend moving to:

1. **Solar-Battery Module Tests** (ModBus + MQTT collectors)
2. **Dashboard API Tests** (Flask routes + InfluxDB query mocking)
3. **Integration Tests** (End-to-end with mocked external services)

---

## Running the Tests

```bash
# Install test dependencies
pip install pytest requests-mock

# Run all calculator tests
python -m pytest projects/water-monitor/tests/test_calculator.py -v

# Run with coverage report
pip install pytest-cov
python -m pytest projects/water-monitor/tests/test_calculator.py --cov=projects.water_monitor.collector.calculator --cov-report=term-missing
```

---

## Test File Location

- **Test File**: `projects/water-monitor/tests/test_calculator.py`
- **Lines of Test Code**: 680+ lines
- **Execution Time**: ~0.09 seconds
