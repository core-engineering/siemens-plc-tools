"""The published CLI surface must not carry accidental aliases.

`import` is a Python keyword, so the group's function is `import_`. A bare
`@iol_group.group()` derives the command name from the function and registers it
as `import-`; the code then called `add_command(..., name="import")` as well, so
the same group appeared twice in `plc iol --help` under two names. Nothing
documented `import-` — it was an artefact of the keyword workaround.

A duplicate is not just cosmetic: it doubles the surface a user has to read, and
either name could drift into a script and then have to be supported forever.
"""

from __future__ import annotations

import click
from click.testing import CliRunner

from plc_iol.cli import iol_group


def _command_names(group: click.Group) -> list[str]:
    """List a group's registered command names.

    Parameters
    ----------
    group : click.Group
        The group to inspect.

    Returns
    -------
    list[str]
        Registered names, in registration order.
    """
    return list(group.commands)


class TestNoDuplicateCommands:
    def test_no_two_names_share_one_command_object(self) -> None:
        """Two names for one command means one of them is an accident."""
        seen: dict[int, str] = {}
        duplicates: list[str] = []
        for name, command in iol_group.commands.items():
            key = id(command)
            if key in seen:
                duplicates.append(f"{seen[key]!r} and {name!r} are the same command")
            else:
                seen[key] = name
        assert not duplicates, "; ".join(duplicates)

    def test_import_is_registered_once_under_its_real_name(self) -> None:
        names = _command_names(iol_group)
        assert "import" in names
        assert "import-" not in names

    def test_the_trailing_hyphen_alias_is_gone_from_help(self) -> None:
        """What the user actually sees, not just what the object graph says."""
        result = CliRunner().invoke(iol_group, ["--help"])
        assert "import-" not in result.output
        assert "import" in result.output

    def test_import_still_works(self) -> None:
        """Removing the alias must not remove the command."""
        result = CliRunner().invoke(iol_group, ["import", "--help"])
        assert result.exit_code == 0, result.output
        assert "tags" in result.output
