"""Binding positional call arguments to a callee's declared parameters.

SCL lets a FUNCTION be called positionally -- ``"Scaling"(#raw, 2.0)`` -- where the
position decides which declared parameter receives the value. The transpiler works
one block at a time and cannot see the callee's declaration from inside the call.
The runtime can: it already resolves a block by name to read its kind, and the same
resolution reads its declared inputs in order. That resolver is handed in as a
callable, so this module depends on neither.

Where a binding cannot be established, this module raises rather than guessing.
The old text translator dropped every unnamed argument silently -- the block was
called with no inputs, computed on its defaults, and nothing reported it. Five
production projects held 97 such calls in 3 blocks.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

#: Resolves a block's quoted name (without the quotes) to the parameter names its
#: positional arguments bind to, in order -- or ``None`` when the block cannot be
#: found or parsed. ``PLCRuntime.block_signature`` offers ``VAR_INPUT``, plus
#: ``VAR_IN_OUT`` only for a block without outputs; anything whose positional order
#: is unverified is left out, so a call reaching past it is refused, not guessed.
SignatureResolver = Callable[[str], list[str] | None]


class PositionalBindingError(ValueError):
    """A positional argument could not be bound to a declared parameter.

    Raised for the four cases where the binding would be a guess: no resolver was
    supplied, the resolver does not know the block, the call passes more positional
    arguments than the block declares inputs, or a positional argument would bind a
    parameter that a named argument in the same call already binds.
    """


def positional_parameter_names(
    block_name: str,
    *,
    positional_count: int,
    already_named: Iterable[str],
    resolver: SignatureResolver | None,
) -> list[str]:
    """The parameter names that ``positional_count`` leading positional arguments bind.

    Parameters
    ----------
    block_name : str
        The callee's name, without quotes.
    positional_count : int
        How many unnamed arguments the call passes.
    already_named : Iterable[str]
        Parameter names bound by named arguments in the same call. A positional
        argument may not bind one of these.
    resolver : SignatureResolver | None
        Resolves ``block_name`` to its declared input names in order; ``None`` when
        no project context is available.

    Returns
    -------
    list[str]
        One parameter name per positional argument, in argument order. Empty when
        ``positional_count`` is zero -- in which case ``resolver`` is never called,
        so a call with only named arguments needs no project context.

    Raises
    ------
    PositionalBindingError
        When the binding cannot be established. The message names the block and the
        reason, so the transpile error it becomes is actionable.
    """
    if positional_count == 0:
        return []
    if resolver is None:
        raise PositionalBindingError(
            f"{block_name!r} is called with {positional_count} positional argument(s) but no "
            "signature resolver is available to bind them; call it with named arguments"
        )
    signature = resolver(block_name)
    if signature is None:
        raise PositionalBindingError(
            f"{block_name!r} is called with {positional_count} positional argument(s) but its "
            "declaration cannot be resolved from the project; call it with named arguments"
        )
    if positional_count > len(signature):
        raise PositionalBindingError(
            f"{block_name!r} is called with {positional_count} positional argument(s) but declares "
            f"only {len(signature)} positionally bindable parameter(s): "
            f"{', '.join(signature) or '(none)'}; pass the rest by name"
        )
    bound = signature[:positional_count]
    # SCL identifiers are case-insensitive; the generated Python is not, so a clash
    # that differs only by case would otherwise pass here and then bind twice.
    named_folded = {name.casefold() for name in already_named}
    clash = sorted(name for name in bound if name.casefold() in named_folded)
    if clash:
        raise PositionalBindingError(
            f"{block_name!r}: positional argument(s) would bind {', '.join(clash)}, which the same "
            "call also binds by name"
        )
    return bound
