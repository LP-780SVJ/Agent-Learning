"""Dynamic plugin loader."""

import importlib


def load_plugin(module_name: str):
    """Load a plugin module dynamically."""
    return importlib.import_module(module_name)


def load_default_fraud_plugin():
    return load_plugin("src.plugins.fraud_rules")

