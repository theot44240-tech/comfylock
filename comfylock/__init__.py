"""ComfyLock - the reproducibility lockfile for ComfyUI workflows.

"pip freeze for ComfyUI": pin custom-node commits, model hashes, and key
workflow parameters into one small, portable, verifiable lockfile.
"""

__version__ = "0.2.0"
SCHEMA_VERSION = 1

from .model import FileNode, Hash, Lockfile, Model  # noqa: E402

__all__ = ["Lockfile", "Model", "Hash", "FileNode", "__version__", "SCHEMA_VERSION"]
