"""ComfyLock - the reproducibility lockfile for ComfyUI workflows.

"pip freeze for ComfyUI": pin custom-node commits, model hashes, and key
workflow parameters into one small, portable, verifiable lockfile.
"""

__version__ = "0.3.0"

from .model import SCHEMA_VERSION, FileNode, Hash, Lockfile, Model  # noqa: E402

__all__ = [
    "Lockfile",
    "Model",
    "Hash",
    "FileNode",
    "__version__",
    "SCHEMA_VERSION",
]
