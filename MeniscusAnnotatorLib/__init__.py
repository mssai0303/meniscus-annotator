"""Meniscus annotation persistence and technical validation, independent of Qt/Slicer.

Only this module defines output acceptance. Preparation checkers are not copied or
called. Public arrays are KJI; NIfTI files remain native IJK, with explicit mapping.
"""
from .core import (Dataset, Case, WorkStore, CaseSession, ValidationError,
                   export_approved, sha256, check_nifti, APP_VERSION)
