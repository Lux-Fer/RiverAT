"""Runner：把插件包送到目标机、执行、回收证据。"""

from app.runner.bundle import pack_bundle
from app.runner.executor import StepOutcome, StepStatus, run_step
from app.runner.manifest import MANIFEST_NAME, PluginManifest, load_manifest

__all__ = [
    "MANIFEST_NAME",
    "PluginManifest",
    "StepOutcome",
    "StepStatus",
    "load_manifest",
    "pack_bundle",
    "run_step",
]
