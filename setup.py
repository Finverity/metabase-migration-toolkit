"""Setup script for backward compatibility.

All configuration is in pyproject.toml.
"""

from setuptools import setup

setup(
    py_modules=["export_metabase", "import_metabase", "sync_metabase"],
)
