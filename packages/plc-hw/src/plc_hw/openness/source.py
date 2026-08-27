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
    """Read a TIA project through Openness.

    Parameters
    ----------
    portal : Any
        The connected ``TiaPortal`` instance, as returned by :func:`open_source`.
    project : Any
        The open project object (``Project`` or ``ProjectBase``) to read from.
    """

    def __init__(self, portal: Any, project: Any) -> None:
        self._portal = portal
        self._project = project
        self._objects: dict[str, Any] = {}

    # -- protocol ---------------------------------------------------------

    def project_name(self) -> str:
        """Return the project's name, from ``Project.Name``.

        Raises
        ------
        OpennessError
            If the CLR call failed -- for example, the TIA session dropped
            mid-read.
        """
        try:
            return str(self._project.Name)
        except Exception as exc:  # noqa: BLE001 - translated at the boundary
            raise OpennessError(f"could not read the project's name: {type(exc).__name__}: {exc}") from exc

    def subnets(self) -> list[SubnetInfo]:
        """Return the project's subnets and their IO system numbers.

        Reads ``Project.Subnets``, and for each subnet its ``IoSystems``
        composition, taking the first IO system's number, if any.

        Raises
        ------
        OpennessError
            If the CLR call failed -- for example, the TIA session dropped
            mid-read.
        """
        try:
            out: list[SubnetInfo] = []
            for subnet in self._project.Subnets:
                number = None
                for io_system in subnet.IoSystems:
                    number = int(io_system.Number)
                    break
                out.append(SubnetInfo(name=str(subnet.Name), type=str(subnet.TypeIdentifier), number=number))
            return out
        except Exception as exc:  # noqa: BLE001 - translated at the boundary
            raise OpennessError(f"could not read the project's subnets: {type(exc).__name__}: {exc}") from exc

    def devices(self) -> list[NodeRef]:
        """Return the project's devices, at every nesting level.

        See :meth:`_all_devices` for how nested device (user) groups are walked.

        Raises
        ------
        OpennessError
            If :meth:`_all_devices` failed, or if reading a device's name
            while registering it failed.
        """
        try:
            return [self._register(device, str(device.Name)) for device in self._all_devices()]
        except OpennessError:
            raise
        except Exception as exc:  # noqa: BLE001 - translated at the boundary
            raise OpennessError(f"could not read the project's devices: {type(exc).__name__}: {exc}") from exc

    def device_items(self, parent: NodeRef) -> list[NodeRef]:
        """Return ``parent``'s direct children, from its ``DeviceItems`` composition.

        Raises
        ------
        KeyError
            If ``parent`` was never registered by this source -- an internal
            bookkeeping error, not a TIA failure, so it is left to raise as
            itself rather than being mistaken for one.
        OpennessError
            If ``parent`` was registered but the CLR call to read its children
            failed.
        """
        obj = self._objects[parent.key]
        try:
            items = getattr(obj, "DeviceItems", None)
            if items is None:
                return []
            return [self._register(item, f"{parent.key}/{item.Name}") for item in items]
        except Exception as exc:  # noqa: BLE001 - translated at the boundary
            raise OpennessError(
                f"could not read device items of {parent.key!r}: {type(exc).__name__}: {exc}"
            ) from exc

    def attribute_infos(self, item: NodeRef) -> list[AttributeInfo]:
        """Return the attributes ``item`` advertises, from ``GetAttributeInfos()``.

        ``EngineeringAttributeInfo`` has no ``ReadOnly`` property; access is
        reported through the ``EngineeringAttributeAccessMode`` flags enum
        (``None``, ``Read``, ``Write``, ``ReadWrite``) instead. All four members
        have exact names, so .NET's ``Enum.ToString()`` -- and pythonnet's
        ``str()`` of it -- reliably returns one of those four names, never a
        decomposed combination; an attribute is reported read-only exactly
        when it is ``Read``. ``None`` (no access at all) is not distinguished
        from ``Write``/``ReadWrite`` by this model and also maps to
        ``read_only=False`` -- a ``None``-access attribute would misleadingly
        read as writable. No attribute observed so far has reported ``None``.

        Raises
        ------
        KeyError
            If ``item`` was never registered by this source.
        """
        obj = self._objects[item.key]
        try:
            infos = obj.GetAttributeInfos()
            return [
                AttributeInfo(name=str(info.Name), read_only=str(info.AccessMode) == "Read") for info in infos
            ]
        except Exception:  # noqa: BLE001 - no attribute infos is not fatal
            return []

    def attributes(self, item: NodeRef, names: Sequence[str]) -> dict[str, object]:
        """Read the named attributes, keeping only the ones that could be read.

        Raises
        ------
        KeyError
            If ``item`` was never registered by this source.
        """
        obj = self._objects[item.key]
        out: dict[str, object] = {}
        for name in names:
            try:
                out[name] = obj.GetAttribute(name)
            except Exception:  # noqa: BLE001 - the walker records the gap and its reason
                continue
        return out

    def attribute_error(self, item: NodeRef, name: str) -> str:
        """Return why ``name`` could not be read on ``item``, by reading it again.

        Raises
        ------
        KeyError
            If ``item`` was never registered by this source.
        """
        obj = self._objects[item.key]
        try:
            obj.GetAttribute(name)
        except Exception as exc:  # noqa: BLE001
            return f"{type(exc).__name__}: {exc}"
        return "read succeeded on retry"

    def addresses(self, item: NodeRef) -> list[AddressRange]:
        """Return ``item``'s input/output address ranges, from ``Addresses``.

        Raises
        ------
        KeyError
            If ``item`` was never registered by this source.
        OpennessError
            If ``item`` was registered but the CLR call to read its addresses
            failed.
        """
        obj = self._objects[item.key]
        try:
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
        except Exception as exc:  # noqa: BLE001 - translated at the boundary
            raise OpennessError(
                f"could not read addresses of {item.key!r}: {type(exc).__name__}: {exc}"
            ) from exc

    def features(self, item: NodeRef) -> dict[str, dict[str, object]]:
        """Return ``item``'s captured features, keyed by feature name.

        Tries each name in :data:`_FEATURES` as an Openness service
        (``item.GetService[T]()``); most names are unsupported for most items,
        which is ordinary and silent, not an error. Guarded the same way as
        :meth:`safety_signatures`'s parallel import: if the
        ``HW.Features`` namespace itself cannot be imported, there is nothing
        to look up, so an empty result is returned rather than raised.

        Raises
        ------
        KeyError
            If ``item`` was never registered by this source.
        """
        obj = self._objects[item.key]
        try:
            import Siemens.Engineering.HW.Features as hw_features
        except Exception:  # noqa: BLE001 - consistent with safety_signatures's guard
            return {}
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
        """Return the project's safety signatures, keyed by signature type.

        For every device and every device item nested beneath it (see
        :meth:`_iter_hardware_objects`), tries
        ``GetService[SoftwareContainer]()`` then
        ``.Software.GetService[SafetyAdministration]()`` -- the chain from a
        hardware object to its PLC software's safety program. Most objects
        offer neither service, which is ordinary and silent.

        Two different failure shapes, kept distinct:

        - A failure that stops the *whole* scan before it can start -- the
          ``HW.Features``/``Safety`` namespaces failing to import, or
          :meth:`_all_devices` raising :class:`OpennessError` -- is not
          caught here. The former is reported inline (below); the latter
          propagates as :class:`OpennessError`, the same as every other
          method that reads the CLR directly.
        - A failure on *one* object partway through the scan -- reading its
          ``DeviceItems`` while descending (:meth:`_iter_hardware_objects`),
          reading its ``SoftwareContainer.Software``, reaching
          ``SafetyAdministration``, or reading one signature's ``Type``/
          ``Value`` -- does not stop the scan. It is recorded under
          :data:`UNREACHABLE_SAFETY`, naming the object, and the walk moves
          on to the next object. A partial result (some signatures found,
          some objects that could not be read) is therefore distinguishable
          both from "no safety program anywhere" (``{}``) and from "nothing
          could be read at all" (only :data:`UNREACHABLE_SAFETY` present).
        """
        try:
            import Siemens.Engineering.HW.Features as hw_features
            import Siemens.Engineering.Safety as safety
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
            return {UNREACHABLE_SAFETY: f"Safety API not loadable: {type(exc).__name__}: {exc}"}

        out: dict[str, str] = {}
        errors: list[str] = []
        for device in self._all_devices():
            for obj in self._iter_hardware_objects(device, errors):
                try:
                    container = self._service(obj, hw_features, "SoftwareContainer")
                    software = getattr(container, "Software", None) if container is not None else None
                except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
                    errors.append(
                        f"{self._safe_name(obj)}: could not read software container: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    continue
                if software is None:
                    # Ordinary: most device items carry no software at all.
                    continue
                try:
                    administration = software.GetService[safety.SafetyAdministration]()
                except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
                    errors.append(f"{self._safe_name(obj)}: {type(exc).__name__}: {exc}")
                    continue
                if administration is None:
                    # Ordinary: this PLC software has no safety program.
                    continue
                try:
                    for signature in administration.ProgramSignatures:
                        out[str(signature.Type)] = str(signature.Value)
                except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
                    errors.append(
                        f"{self._safe_name(obj)}: could not read safety signatures: "
                        f"{type(exc).__name__}: {exc}"
                    )
        if errors:
            # A real failure reaching the service, distinct from "not present
            # here" -- recorded so an all-empty result cannot be mistaken for
            # a project confirmed to have no safety program.
            out[UNREACHABLE_SAFETY] = "; ".join(errors)
        return out

    # -- helpers ----------------------------------------------------------

    def _all_devices(self) -> list[Any]:
        """Devices at project level and inside every device group.

        Raises
        ------
        OpennessError
            If the CLR call to enumerate devices or groups failed.
        """
        try:
            found = list(self._project.Devices)
            stack = list(self._project.DeviceGroups)
            while stack:
                group = stack.pop()
                # DeviceUserGroup documents a Groups composition (nested
                # groups); a Devices composition is not documented on it, so
                # this is read defensively rather than assumed.
                found.extend(getattr(group, "Devices", None) or [])
                stack.extend(getattr(group, "Groups", None) or [])
            return found
        except Exception as exc:  # noqa: BLE001 - translated at the boundary
            raise OpennessError(f"could not enumerate devices: {type(exc).__name__}: {exc}") from exc

    def _iter_hardware_objects(self, obj: Any, errors: list[str]) -> Iterator[Any]:
        """Yield ``obj`` and every device item nested beneath it, depth-first.

        The service that exposes a CPU's PLC software (``SoftwareContainer``)
        can sit on the device itself or on any device item plugged into it,
        at any depth, and nothing in the object graph says where without
        asking. ``Device`` and ``DeviceItem`` both expose ``DeviceItems``
        from the same ``HardwareObject`` base, so this recursion applies to
        either without needing to know which one it was given.

        Parameters
        ----------
        obj : Any
            The object to yield, then descend from.
        errors : list[str]
            Mutated in place: a CLR failure reading ``obj``'s ``DeviceItems``
            stops the walk from descending past ``obj`` -- its siblings and
            everything already yielded are unaffected -- and is appended
            here naming ``obj``, the same way :meth:`safety_signatures`
            records every other per-object failure in this scan.
        """
        yield obj
        try:
            children = getattr(obj, "DeviceItems", None) or []
        except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
            errors.append(f"{self._safe_name(obj)}: could not read device items: {type(exc).__name__}: {exc}")
            return
        for child in children:
            yield from self._iter_hardware_objects(child, errors)

    @staticmethod
    def _safe_name(obj: Any) -> str:
        """Best-effort ``obj.Name`` for an error message; never raises.

        Used only to label a diagnostic string, so a CLR failure reading the
        name itself must not replace the failure it was trying to describe.
        """
        try:
            return str(obj.Name)
        except Exception:  # noqa: BLE001 - purely for a diagnostic message
            return "?"

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

    import Siemens.Engineering as tia
    from System.IO import FileInfo

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
