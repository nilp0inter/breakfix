# The Ratchet Cycle

## 1. Core Concept
**The Ratchet Cycle** is a strictly additive development loop. Unlike standard
TDD, it prohibits refactoring during the cycle. The codebase must move forward
in discrete, atomic steps where necessity is proven before code is written.

## 2. Roles & Information Barriers
To ensure decoupling, agents operate under strict information constraints:
*   **The Tester (Black-Box):** Sees only Requirements and Public Function
    Signatures. **Cannot** see implementation.
*   **The Developer (Blind):** Sees only Source Code and Test *Failure
    Messages*. **Cannot** see test source code.
*   **The Verifier (Semantic Check):** Ensures the test matches the prompt's
    intent.
*   **The System (Automated Check):** Enforces compilation, failure states, and
    coverage strictness.

## 3. The Cycle

### Phase 1: The "Red" Phase (Constraint)
*   **Step A: The Tester**
    *   **Action:** Writes exactly one test case asserting new behavior against
        the public interface.
*   **Step B: The Verifier (Semantic Lock)**
    *   **Check:** Rejects the test if it does not semantically match the
        Requirement Intent.
*   **Step C: The System (Inventory Lock)**
    *   **Action:** Validates the state.
    *   **Pass Condition:**
        1.  Total test count increases by exactly 1.
        2.  Test compiles successfully.
        3.  Test **FAILS** against current implementation.

### Phase 2: The "Green" Phase (Solution)
*   **Step A: The Developer**
    *   **Action:** writes implementation code to satisfy the failure.
    *   **Context:** Relies solely on `AssertionError` output to infer logic.
*   **Step B: The System (Coverage Lock)**
    *   **Action:** Validates the diff.
    *   **Pass Condition:**
        1.  **Strict Coverage:** 100% of the *added* lines are executed by the
            specific test case. (Dead code rejection).
        2.  **Regression:** All previous tests pass.
