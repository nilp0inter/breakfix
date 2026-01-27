"""
BreakFix Agents Package

This package contains all 7 specialist agents of the BreakFix team:
- Architect: Plans and defines atomic requirements
- Pioneer: Writes failing tests (Red phase)
- Gatekeeper: Validates tests against specifications
- Builder: Writes minimal code to pass tests (Green phase)
- Pruner: Removes unused code using coverage analysis
- Sniper: Performs mutation testing to expose weak tests
- Curator: Refactors code and tests for elegance
"""

# Agents are now instantiated dynamically via get_<agent_name> functions
# and are no longer re-exported here as static instances.