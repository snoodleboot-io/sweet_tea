"""
Case package for SWE-47: a type-narrowed singleton over a lazily filled tree.

Each component module imports a marker module at its top level, so a test can tell
which components were imported by looking at ``sys.modules`` rather than by trusting
the registry's account of itself.
"""
