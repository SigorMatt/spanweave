"""The capture harness. **Outside the package, and human-run only.**

Everything here may use the network, a model API, and framework dependencies
-- and it is the only place in this repository that may (``ENVIRONMENT.md``,
network zones). Nothing in ``spanweave/`` imports any of it, which is what
keeps the library's "never touches the network" claim structural rather than
aspirational.

An autonomous agent must not run this and must not produce a file in
``fixtures/captured/`` (``AGENT.md`` halt point). A fabricated "captured"
trace would destroy the only thing that directory is for.
"""
