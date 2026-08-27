"""HardwareSource backed by a live TIA Portal through Openness.

The only module in the package that talks to the CLR, and the only one excluded
from coverage: it cannot execute on CI. Keep it mechanical. Any decision worth a
test belongs above the source boundary, in ``walk.py``.

Read-only by construction: this module never writes an attribute and never
persists the project, and neither call may be added.

That is a promise this module keeps, not one the API enforces. Openness'
``ProjectOpenMode`` has exactly two values, ``Primary`` and ``Secondary`` --
there is no read-only mode. Nothing in Openness itself would stop the
underlying project object from being written to or persisted; the guarantee
here rests entirely on this module's own discipline.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from plc_hw.model import AddressRange, AttributeInfo, NodeRef, SubnetInfo
from plc_hw.openness.bootstrap import OpennessError, load_clr, resolve

__all__ = ["OpennessError", "OpennessSource", "open_source"]

#: Features read per device item, by Openness service type name. Every name here
#: is a type in the ``Siemens.Engineering.HW.Features`` namespace.
_FEATURES = (
    "NetworkInterface",
    "NetworkPort",
    "MrpDomainOwner",
    "MrpInstancesOwner",
    "OpcUaUserManagement",
    "PlcAccessLevelProvider",
    "DefaultWebPagesFeature",
    "CertificateManagementConfiguration",
    "GsdDeviceItem",
)

#: Key marking that no ``SafetyAdministration`` service could be reached at all --
#: as opposed to a project that was reached and genuinely carries no signatures.
#: A real ``SafetySignatureType`` member (``CollectiveOfflineSignature`` and the
#: like) never takes this shape, so an absent signature set can never be mistaken
#: for an empty one.
UNREACHABLE_SAFETY = "__safety_unreachable__"


class OpennessSource:
    """Read a TIA project through Openness."""

    def __init__(self, portal: Any, project: Any) -> None:
        self._portal = portal
        self._project = project
        self._objects: dict[str, Any] = {}

    # -- protocol ---------------------------------------------------------

    def project_name(self) -> str:
        return str(self._project.Name)

    def subnets(self) -> list[SubnetInfo]:
        out: list[SubnetInfo] = []
        for subnet in self._project.Subnets:
            number = None
            for io_system in subnet.IoSystems:
                number = int(io_system.Number)
                break
            out.append(SubnetInfo(name=str(subnet.Name), type=str(subnet.TypeIdentifier), number=number))
        return out

    def devices(self) -> list[NodeRef]:
        return [self._register(device, str(device.Name)) for device in self._all_devices()]

    def device_items(self, parent: NodeRef) -> list[NodeRef]:
        obj = self._objects[parent.key]
        items = getattr(obj, "DeviceItems", None)
        if items is None:
            return []
        return [self._register(item, f"{parent.key}/{item.Name}") for item in items]

    def attribute_infos(self, item: NodeRef) -> list[AttributeInfo]:
        obj = self._objects[item.key]
        try:
            infos = obj.GetAttributeInfos()
        except Exception:  # noqa: BLE001 - no attribute infos is not fatal
            return []
        # EngineeringAttributeInfo has no ReadOnly property; access is reported
        # through the AccessMode flags enum (None, Read, Write, ReadWrite). An
        # attribute is read-only when it reports exactly Read.
        return [
            AttributeInfo(name=str(info.Name), read_only=str(info.AccessMode) == "Read") for info in infos
        ]

    def attributes(self, item: NodeRef, names: Sequence[str]) -> dict[str, object]:
        obj = self._objects[item.key]
        out: dict[str, object] = {}
        for name in names:
            try:
                out[name] = obj.GetAttribute(name)
            except Exception:  # noqa: BLE001 - the walker records the gap and its reason
                continue
        return out

    def attribute_error(self, item: NodeRef, name: str) -> str:
        obj = self._objects[item.key]
        try:
            obj.GetAttribute(name)
        except Exception as exc:  # noqa: BLE001
            return f"{type(exc).__name__}: {exc}"
        return "read succeeded on retry"

    def addresses(self, item: NodeRef) -> list[AddressRange]:
        obj = self._objects[item.key]
        ranges = getattr(obj, "Addresses", None)
        if ranges is None:
            return []
        return [
            AddressRange(
                start=int(address.StartAddress),
                length=int(address.Length),
                io_type=str(address.IoType),
            )
            for address in ranges
        ]

    def features(self, item: NodeRef) -> dict[str, dict[str, object]]:
        import Siemens.Engineering.HW.Features as hw_features  # type: ignore[import-not-found]

        obj = self._objects[item.key]
        out: dict[str, dict[str, object]] = {}
        for name in _FEATURES:
            service = self._service(obj, hw_features, name)
            if service is None:
                continue
            captured = self._capture(service)
            if captured:
                out[name] = captured
        return out

    def safety_signatures(self) -> dict[str, str]:
        try:
            import Siemens.Engineering.HW.Features as hw_features  # type: ignore[import-not-found]
            import Siemens.Engineering.Safety as safety  # type: ignore[import-not-found]
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
            return {UNREACHABLE_SAFETY: f"Safety API not loadable: {type(exc).__name__}: {exc}"}

        out: dict[str, str] = {}
        errors: list[str] = []
        for device in self._all_devices():
            for obj in self._iter_hardware_objects(device):
                container = self._service(obj, hw_features, "SoftwareContainer")
                software = getattr(container, "Software", None) if container is not None else None
                if software is None:
                    # Ordinary: most device items carry no software at all.
                    continue
                try:
                    administration = software.GetService[safety.SafetyAdministration]()
                except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
                    errors.append(f"{getattr(obj, 'Name', '?')}: {type(exc).__name__}: {exc}")
                    continue
                if administration is None:
                    # Ordinary: this PLC software has no safety program.
                    continue
                for signature in administration.ProgramSignatures:
                    out[str(signature.Type)] = str(signature.Value)
        if errors:
            # A real failure reaching the service, distinct from "not present
            # here" -- recorded so an all-empty result cannot be mistaken for
            # a project confirmed to have no safety program.
            out[UNREACHABLE_SAFETY] = "; ".join(errors)
        return out

    # -- helpers ----------------------------------------------------------

    def _all_devices(self) -> list[Any]:
        """Devices at project level and inside every device group."""
        found = list(self._project.Devices)
        stack = list(self._project.DeviceGroups)
        while stack:
            group = stack.pop()
            # DeviceUserGroup documents a Groups composition (nested groups);
            # a Devices composition is not documented on it, so this is read
            # defensively rather than assumed.
            found.extend(getattr(group, "Devices", None) or [])
            stack.extend(getattr(group, "Groups", None) or [])
        return found

    def _iter_hardware_objects(self, obj: Any) -> Iterator[Any]:
        """Yield ``obj`` and every device item nested beneath it, depth-first.

        The service that exposes a CPU's PLC software (``SoftwareContainer``)
        can sit on the device itself or on any device item plugged into it,
        at any depth, and nothing in the object graph says where without
        asking. ``Device`` and ``DeviceItem`` both expose ``DeviceItems``
        from the same ``HardwareObject`` base, so this recursion applies to
        either without needing to know which one it was given.
        """
        yield obj
        for child in getattr(obj, "DeviceItems", None) or []:
            yield from self._iter_hardware_objects(child)

    def _register(self, obj: Any, key: str) -> NodeRef:
        """Remember a CLR object under the path the walker will use as its key."""
        self._objects[key] = obj
        return NodeRef(key=key, name=str(obj.Name))

    @staticmethod
    def _service(obj: Any, namespace: Any, name: str) -> Any:
        """Fetch an Openness service by name from ``namespace``, or ``None``.

        Parameters
        ----------
        obj : Any
            The CLR object to query.
        namespace : Any
            The imported Python.NET namespace module holding the service type,
            for example ``Siemens.Engineering.HW.Features``.
        name : str
            The Openness type name of the service to request.

        Returns
        -------
        Any
            The service instance, or ``None`` when this object does not
            support it -- an ordinary, silent outcome for most name/object
            combinations (most device items are not network interfaces, most
            devices are not GSD devices, and so on).
        """
        try:
            return obj.GetService[getattr(namespace, name)]()
        except Exception:  # noqa: BLE001 - "unsupported here" is not a failure
            return None

    @staticmethod
    def _capture(service: Any) -> dict[str, object]:
        """Read every attribute a feature advertises."""
        out: dict[str, object] = {}
        try:
            infos = service.GetAttributeInfos()
        except Exception:  # noqa: BLE001
            return out
        for info in infos:
            try:
                out[str(info.Name)] = service.GetAttribute(str(info.Name))
            except Exception:  # noqa: BLE001
                continue
        return out


def open_source(attach: bool = False, project: Path | None = None) -> OpennessSource:
    """Connect to TIA Portal and return a read-only source.

    Parameters
    ----------
    attach : bool
        Attach to a running TIA session. Default when exactly one is running.
    project : Path | None
        Project to open without a user interface.

    Returns
    -------
    OpennessSource
        A read-only source.

    Raises
    ------
    OpennessError
        If Openness is unreachable, no session can be attached, or several are
        running with no project given.
    """
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    load_clr(resolve(os.environ, program_files))

    import Siemens.Engineering as tia  # type: ignore[import-not-found]
    from System.IO import FileInfo  # type: ignore[import-not-found]

    try:
        processes = list(tia.TiaPortal.GetProcesses())
    except Exception as exc:  # noqa: BLE001 - the CLR exception type is not importable here
        raise OpennessError(
            "TIA Openness refused the connection. The usual cause is that this Windows account "
            "is not a member of the 'Siemens TIA Openness' group. Add it, sign out and back in. "
            f"Original error: {type(exc).__name__}: {exc}"
        ) from exc
    if attach or (project is None and len(processes) == 1):
        if not processes:
            raise OpennessError(
                "no running TIA Portal session to attach to; open the project or pass --project"
            )
        if len(processes) > 1:
            raise OpennessError(
                f"{len(processes)} TIA Portal sessions are running; pass --project to pick one"
            )
        try:
            portal = processes[0].Attach()
            opened = portal.Projects[0]
        except Exception as exc:  # noqa: BLE001 - the CLR exception type is not importable here
            raise OpennessError(
                f"could not attach to the running TIA Portal session: {type(exc).__name__}: {exc}"
            ) from exc
        return OpennessSource(portal, opened)

    if project is None:
        raise OpennessError(
            "no TIA session running and no --project given; " "set hw.project in plc.yaml or pass --project"
        )

    try:
        portal = tia.TiaPortal(tia.TiaPortalMode.WithoutUserInterface)
        # Opened without a user interface: nothing in this package ever calls
        # Save, and there is no read-only ProjectOpenMode to ask for instead.
        opened = portal.Projects.Open(FileInfo(str(project)))
    except Exception as exc:  # noqa: BLE001 - the CLR exception type is not importable here
        raise OpennessError(f"could not open {project}: {type(exc).__name__}: {exc}") from exc
    return OpennessSource(portal, opened)
