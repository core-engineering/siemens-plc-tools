"""The boundary between pure Python and whatever supplies hardware data.

Three implementations exist: ``OpennessSource`` (Windows + TIA, the only module
that touches the CLR), ``ReplaySource`` (a recorded fixture) and the test fake.
Nothing above this boundary knows which one it holds.

The protocol is deliberately fine-grained, mirroring the Openness object graph,
so that traversal, error handling and ordering live in pure Python above it and
stay testable without TIA.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from plc_hw.model import AddressRange, AttributeInfo, NodeRef, SubnetInfo


@runtime_checkable
class HardwareSource(Protocol):
    """Read-only access to a hardware configuration.

    Every method is a read. The protocol has no write member, and none may be
    added: read-only is structural in this package, not a convention.
    """

    def project_name(self) -> str:
        """Return the project name."""
        ...

    def subnets(self) -> list[SubnetInfo]:
        """Return the project's subnets and IO systems."""
        ...

    def devices(self) -> list[NodeRef]:
        """Return the project's devices."""
        ...

    def device_items(self, parent: NodeRef) -> list[NodeRef]:
        """Return the direct children of a device or device item."""
        ...

    def attribute_infos(self, item: NodeRef) -> list[AttributeInfo]:
        """Return the attributes a device item advertises."""
        ...

    def attributes(self, item: NodeRef, names: Sequence[str]) -> dict[str, object]:
        """Read the named attributes.

        Returns only what could be read. The caller compares the request to the
        response and records every gap; this method must never invent a value.
        """
        ...

    def attribute_error(self, item: NodeRef, name: str) -> str:
        """Return why ``name`` could not be read on ``item``."""
        ...

    def addresses(self, item: NodeRef) -> list[AddressRange]:
        """Return the item's input/output address ranges."""
        ...

    def features(self, item: NodeRef) -> dict[str, dict[str, object]]:
        """Return the item's captured features, keyed by feature name."""
        ...

    def safety_signatures(self) -> dict[str, str]:
        """Return the project's safety signatures, keyed by signature type."""
        ...
