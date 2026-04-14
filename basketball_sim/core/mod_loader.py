"""Mod loader -- auto-discovers and loads mods from the mods/ folder.

On startup, discovers all folders in mods/, loads JSON into registries,
imports Python files and registers them in pipelines.

Structure:
    mods/
      my_mod/
        mod.json              # metadata (name, version, author)
        data/
          moves/*.json        # new dribble moves
          badges/*.json       # new badges
          narration/*.json    # new templates
        modifiers/
          *.py                # new modifier functions
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class ModMetadata:
    """Metadata for a loaded mod."""
    mod_id: str
    name: str = ""
    version: str = "1.0.0"
    author: str = ""
    description: str = ""
    path: Path = field(default_factory=lambda: Path("."))


@dataclass
class LoadedMod:
    """A fully loaded mod with all its data and functions."""
    metadata: ModMetadata
    moves: dict[str, Any] = field(default_factory=dict)
    badges: dict[str, Any] = field(default_factory=dict)
    narration_templates: list[dict] = field(default_factory=list)
    modifier_functions: list[tuple[str, Callable]] = field(default_factory=list)


class ModLoader:
    """Discovers and loads mods from a directory.

    Usage:
        loader = ModLoader(Path("mods"))
        mods = loader.discover_and_load()
        for mod in mods:
            # merge mod.moves into move registry
            # register mod.modifier_functions into pipeline
            ...
    """

    def __init__(self, mods_dir: Path | None = None) -> None:
        self._mods_dir = mods_dir or Path("mods")
        self._loaded: list[LoadedMod] = []
        self._conflict_policy = "last_wins"  # "last_wins", "error", "namespace"

    @property
    def mods_dir(self) -> Path:
        return self._mods_dir

    @property
    def loaded_mods(self) -> list[LoadedMod]:
        return list(self._loaded)

    def discover_and_load(self) -> list[LoadedMod]:
        """Discover all mods in the mods directory and load them.

        Returns list of LoadedMod instances.
        """
        self._loaded.clear()

        if not self._mods_dir.exists():
            logger.info("Mods directory does not exist: %s", self._mods_dir)
            return []

        for mod_dir in sorted(self._mods_dir.iterdir()):
            if not mod_dir.is_dir():
                continue
            if mod_dir.name.startswith(".") or mod_dir.name.startswith("_"):
                continue

            try:
                mod = self._load_mod(mod_dir)
                self._loaded.append(mod)
                logger.info(
                    "Loaded mod: %s v%s (%d moves, %d badges, %d modifiers)",
                    mod.metadata.name or mod.metadata.mod_id,
                    mod.metadata.version,
                    len(mod.moves),
                    len(mod.badges),
                    len(mod.modifier_functions),
                )
            except Exception:
                logger.exception("Failed to load mod from %s", mod_dir)

        return self._loaded

    def _load_mod(self, mod_dir: Path) -> LoadedMod:
        """Load a single mod from its directory."""
        metadata = self._load_metadata(mod_dir)
        mod = LoadedMod(metadata=metadata)

        # Load JSON data
        data_dir = mod_dir / "data"
        if data_dir.exists():
            mod.moves = self._load_json_registry(data_dir / "moves")
            mod.badges = self._load_json_registry(data_dir / "badges")
            mod.narration_templates = self._load_json_list(data_dir / "narration")

        # Load Python modifier functions
        modifiers_dir = mod_dir / "modifiers"
        if modifiers_dir.exists():
            mod.modifier_functions = self._load_python_modifiers(
                modifiers_dir, metadata.mod_id
            )

        return mod

    def _load_metadata(self, mod_dir: Path) -> ModMetadata:
        """Load mod.json metadata."""
        meta_path = mod_dir / "mod.json"
        mod_id = mod_dir.name

        if meta_path.exists():
            with open(meta_path, "r") as f:
                data = json.load(f)
            return ModMetadata(
                mod_id=data.get("id", mod_id),
                name=data.get("name", mod_id),
                version=data.get("version", "1.0.0"),
                author=data.get("author", ""),
                description=data.get("description", ""),
                path=mod_dir,
            )

        return ModMetadata(mod_id=mod_id, name=mod_id, path=mod_dir)

    def _load_json_registry(self, directory: Path) -> dict[str, Any]:
        """Load all JSON files in a directory into a dict keyed by 'id'."""
        registry: dict[str, Any] = {}
        if not directory.exists():
            return registry

        for path in sorted(directory.glob("*.json")):
            try:
                with open(path, "r") as f:
                    raw = json.load(f)
                entries = raw if isinstance(raw, list) else [raw]
                for entry in entries:
                    entry_id = entry.get("id", "")
                    if entry_id:
                        if entry_id in registry and self._conflict_policy == "error":
                            raise ValueError(
                                f"Duplicate ID '{entry_id}' in {path}"
                            )
                        registry[entry_id] = entry
            except Exception:
                logger.exception("Failed to load JSON from %s", path)

        return registry

    def _load_json_list(self, directory: Path) -> list[dict]:
        """Load all JSON files in a directory into a flat list."""
        items: list[dict] = []
        if not directory.exists():
            return items

        for path in sorted(directory.glob("*.json")):
            try:
                with open(path, "r") as f:
                    raw = json.load(f)
                if isinstance(raw, list):
                    items.extend(raw)
                elif isinstance(raw, dict):
                    # Could be a single template or a container with a list
                    templates = raw.get("templates", [raw])
                    items.extend(templates)
            except Exception:
                logger.exception("Failed to load JSON from %s", path)

        return items

    def _load_python_modifiers(
        self, directory: Path, mod_id: str
    ) -> list[tuple[str, Callable]]:
        """Load Python modifier functions from .py files.

        Each .py file should define a function with the same name as the file
        (without .py extension) that takes an ActionContext and returns a Modifier.
        """
        modifiers: list[tuple[str, Callable]] = []

        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("_"):
                continue

            try:
                module_name = f"mod_{mod_id}_{path.stem}"
                spec = importlib.util.spec_from_file_location(module_name, path)
                if spec is None or spec.loader is None:
                    continue

                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)

                # Look for a function matching the filename
                fn_name = path.stem
                fn = getattr(module, fn_name, None)
                if callable(fn):
                    modifiers.append((f"{mod_id}/{fn_name}", fn))
                    logger.info(
                        "Loaded modifier '%s' from %s", fn_name, path
                    )
                else:
                    # Look for any function ending in "_modifier"
                    for attr_name in dir(module):
                        if attr_name.endswith("_modifier"):
                            attr = getattr(module, attr_name)
                            if callable(attr):
                                modifiers.append(
                                    (f"{mod_id}/{attr_name}", attr)
                                )
                                logger.info(
                                    "Loaded modifier '%s' from %s",
                                    attr_name,
                                    path,
                                )
            except Exception:
                logger.exception("Failed to load modifier from %s", path)

        return modifiers

    def merge_into_registry(
        self,
        base_moves: dict[str, Any],
        base_badges: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Merge all loaded mod data into existing registries.

        Returns (merged_moves, merged_badges).
        """
        moves = dict(base_moves)
        badges = dict(base_badges)

        for mod in self._loaded:
            for move_id, move_data in mod.moves.items():
                if self._conflict_policy == "namespace":
                    move_id = f"{mod.metadata.mod_id}:{move_id}"
                moves[move_id] = move_data

            for badge_id, badge_data in mod.badges.items():
                if self._conflict_policy == "namespace":
                    badge_id = f"{mod.metadata.mod_id}:{badge_id}"
                badges[badge_id] = badge_data

        return moves, badges
