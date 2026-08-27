"""Single-Agent orchestration package.

Public types live in ``runtime`` and ``runtime_models``. Keeping package import
side-effect free prevents the provider protocol parser from importing the
Runtime while the core loop itself is still initializing.
"""
