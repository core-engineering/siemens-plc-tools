"""Find the TIA Openness assemblies and load them into the CLR.

Path resolution is pure logic and fully tested. Only :func:`load_clr` touches
pythonnet.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

#: Environment variable that overrides discovery entirely.
ENV_OVERRIDE = "PLC_HW_OPENNESS_PATH"

#: V21 split the single assembly into three. The first two are mandatory for
#: the split layout to be recognised; the third (Safety) is optional, since
#: not every installation licenses the Safety option.
_SPLIT = ("Siemens.Engineering.Base.dll", "Siemens.Engineering.Step7.dll", "Siemens.Engineering.Safety.dll")
_SPLIT_MANDATORY = _SPLIT[:2]

#: V20 and earlier ship one assembly.
_SINGLE = "Siemens.Engineering.dll"


class OpennessError(Exception):
    """Openness could not be located, loaded, or reached."""


@dataclass(frozen=True)
class AssemblySet:
    """The assemblies to load, and which layout they came from.

    Attributes
    ----------
    directory : Path
        Directory the assemblies live in.
    assemblies : tuple[Path, ...]
        Full paths, in load order.
    layout : str
        ``split`` for V21 and later, ``single`` for V20 and earlier.
    """

    directory: Path
    assemblies: tuple[Path, ...]
    layout: str


def discover_assemblies(api_dir: Path) -> AssemblySet:
    """Identify the assembly layout inside ``api_dir``.

    Parameters
    ----------
    api_dir : Path
        Directory holding the public API assemblies.

    Returns
    -------
    AssemblySet
        What to load.

    Raises
    ------
    OpennessError
        If the directory is missing, is not a directory, holds a partial
        split install, or holds neither known layout.
    """
    if not api_dir.exists():
        raise OpennessError(f"{api_dir} does not exist")
    if not api_dir.is_dir():
        raise OpennessError(f"{api_dir} exists but is not a directory")

    mandatory_found = [name for name in _SPLIT_MANDATORY if (api_dir / name).is_file()]
    if len(mandatory_found) == len(_SPLIT_MANDATORY):
        found = tuple(api_dir / name for name in _SPLIT if (api_dir / name).is_file())
        return AssemblySet(directory=api_dir, assemblies=found, layout="split")

    single = api_dir / _SINGLE
    if single.is_file():
        return AssemblySet(directory=api_dir, assemblies=(single,), layout="single")

    if mandatory_found:
        missing = [name for name in _SPLIT_MANDATORY if name not in mandatory_found]
        raise OpennessError(
            f"partial Openness install in {api_dir}: found {', '.join(mandatory_found)} but missing "
            f"{', '.join(missing)}. Reinstall TIA Portal's Openness API, or set {ENV_OVERRIDE} to a "
            "complete installation."
        )

    raise OpennessError(
        f"no Openness assemblies in {api_dir}: expected either "
        f"{_SPLIT[0]} (TIA V21 and later) or {_SINGLE} (V20 and earlier). "
        f"Set {ENV_OVERRIDE} to the directory holding them."
    )


def candidate_api_dirs(env: Mapping[str, str], program_files: Path) -> list[Path]:
    """List directories that may hold the assemblies, best first.

    Parameters
    ----------
    env : Mapping[str, str]
        Environment. ``PLC_HW_OPENNESS_PATH`` wins outright.
    program_files : Path
        Root to scan, normally ``C:\\Program Files``.

    Returns
    -------
    list[Path]
        Candidates, newest Portal version first. Empty when nothing is installed.
    """
    override = env.get(ENV_OVERRIDE)
    if override:
        return [Path(override)]

    automation = program_files / "Siemens" / "Automation"
    if not automation.is_dir():
        return []

    candidates: list[tuple[str, Path]] = []
    for portal in automation.glob("Portal V*"):
        for version_dir in (portal / "PublicAPI").glob("V*"):
            target = version_dir / "net48"
            candidates.append((version_dir.name, target if target.is_dir() else version_dir))
    return [path for _, path in sorted(candidates, key=lambda pair: pair[0], reverse=True)]


def resolve(env: Mapping[str, str], program_files: Path) -> AssemblySet:
    """Find the first candidate directory that actually holds assemblies.

    Parameters
    ----------
    env : Mapping[str, str]
        Environment, passed through to :func:`candidate_api_dirs`.
    program_files : Path
        Root to scan, passed through to :func:`candidate_api_dirs`.

    Returns
    -------
    AssemblySet
        The first candidate, in the order :func:`candidate_api_dirs` returns
        them, that :func:`discover_assemblies` accepts. Earlier candidates
        that exist but hold neither known layout are skipped, not fatal.

    Raises
    ------
    OpennessError
        When there are no candidates at all -- the message names the
        environment variable as the way out -- or when every candidate was
        tried and rejected -- the message lists what was wrong with each one.
    """
    candidates = candidate_api_dirs(env, program_files)
    if not candidates:
        raise OpennessError(
            f"no TIA Portal installation found under {program_files}. "
            f"Set {ENV_OVERRIDE} to the directory holding the Openness assemblies."
        )
    problems: list[str] = []
    for candidate in candidates:
        try:
            return discover_assemblies(candidate)
        except OpennessError as exc:
            problems.append(str(exc))
    raise OpennessError("; ".join(problems))


def load_clr(assemblies: AssemblySet) -> None:
    """Load the assemblies into the CLR.

    Parameters
    ----------
    assemblies : AssemblySet
        What to load, as returned by :func:`resolve` or :func:`discover_assemblies`.

    Raises
    ------
    OpennessError
        If the platform is not Windows, or if pythonnet is not installed.
    """
    if sys.platform != "win32":
        raise OpennessError("TIA Openness runs on Windows only; use --source replay:<path> elsewhere")
    try:
        import clr
    except ImportError as exc:  # pragma: no cover - depends on the host
        raise OpennessError(
            "pythonnet is not installed; from packages/plc-hw, run: uv pip install -e '.[openness]'"
        ) from exc
    directory = str(assemblies.directory)
    if directory not in sys.path:
        sys.path.append(directory)
    for assembly in assemblies.assemblies:
        clr.AddReference(str(assembly))
