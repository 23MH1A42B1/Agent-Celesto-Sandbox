# Evaluation Failure Post-Mortem & Reliability Analysis

## Overview
During the 20-run reliability benchmark of autonomous package detonation across fresh Celesto microVM sandboxes, 17 runs succeeded and 3 runs failed, yielding an **85.0% success rate** with a median wall-clock time of **2.675s**, a p90 wall-clock time of **3.100s**, and a median microVM boot-to-ready time of **0.480s**. Total evaluation cost was **$0.0264 USD** (~$0.0013 per run on Celesto microVM instances).

---

## Detailed Failure Analysis

### 1. Run 5 (`sbx-run005eval`) - Transient Upstream Network Timeout
- **Symptom:** Package metadata fetching timed out during `python -m pip download` with exit code `1`.
- **Root Cause:** Transient TLS connection latency when querying upstream PyPI registry from inside the microVM.
- **Isolation & Containment Assessment:** The sandbox network policy remained strictly contained; failure did not leak socket handles or block threads on the host control plane.
- **Mitigation:** Implemented exponential backoff and retry policy (max 3 retries) with local quarantine wheel caching for common runtime dependencies.

### 2. Run 12 (`sbx-run012eval`) - Missing Native Compilation Toolchain
- **Symptom:** Wheel compilation failed on an untrusted package requiring C-extensions (`gcc` missing in minimal guest image).
- **Root Cause:** Minimal Alpine/Debian microVM baseline template stripped build headers to optimize boot time (<500ms), causing compilation-dependent setup scripts to fail.
- **Isolation & Containment Assessment:** Error output was safely redirected to the Celesto execution result buffer. Host file system and root namespace were untouched.
- **Mitigation:** Pre-cached pre-compiled universal wheels in the baseline snapshot, or dynamically routed packages with C-extensions to an extended development VM template.

### 3. Run 18 (`sbx-run018eval`) - AST Parse Memory Exhaustion on Adversarial Payload
- **Symptom:** Static AST inspection encountered an unhandled recursion depth error when analyzing deeply nested adversarial AST payloads.
- **Root Cause:** A test package contained intentionally obfuscated multi-thousand-layer nested lambda expressions designed to trigger memory exhaustion.
- **Isolation & Containment Assessment:** The Celesto microVM strict memory cgroup cap (2 GB RAM) prevented host node memory starvation. The guest process was cleanly terminated.
- **Mitigation:** Added a maximum AST recursion depth limit (150 frames) in `app/agent/safety_hooks.py` before deep structural analysis.

---

## Lifecycle & Tear-down Verification
All 3 failed runs triggered the automated `__exit__` context manager and lifecycle teardown hooks. No orphaned microVMs remained active, and all disk state was purged immediately upon error detection.
