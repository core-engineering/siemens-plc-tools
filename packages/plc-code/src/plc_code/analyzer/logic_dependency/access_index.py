"""Every read and write of a variable path in a block, from the shared ASTs.

The cross-block tracers (``field_tracer``, ``forward_tracer``, ``state_detector``,
``tag_assignment``, ``chain_builder``) all ask the same question of a block --
*where is this path read, where is it written, by what, inside which call* -- and
each used to answer it by running its own regexes over the block's re-spaced
``Region.content`` text. This module answers it once, from the statement AST for
SCL (:func:`plc_code.parser.statement_parser.parse_statements`) and the ladder AST
for LAD (:func:`plc_code.parser.ladder_builder.build_ladder_program`), as a flat
list of :class:`Access` records the tracers filter.

Paths are spelled as written (:func:`plc_code.parser.scl_text.expression_text`),
indices included, so a consumer can resolve ``[#ARM1]`` against a tag's indices
the way it always did; matching with ``[*]`` wildcards stays the consumer's job.
"""

from __future__ import annotations

import weakref
from collections.abc import Iterator
from dataclasses import dataclass, field

from plc_code.parser import expressions as ast
from plc_code.parser.ladder_ast import Box, CallBox, Coil, CompareContact, Contact, Rung
from plc_code.parser.ladder_builder import build_network_rungs, parse_ladder_element
from plc_code.parser.lexer import Token
from plc_code.parser.models import Block, Network
from plc_code.parser.scl_text import expression_text
from plc_code.parser.statement_parser import parse_statements, verify_no_silent_loss
from plc_code.parser.statements import Assignment, Call, Case, For, If, Statement, While

READ = "read"
WRITE = "write"


@dataclass(frozen=True)
class CallContext:
    """The call a parameter binding belongs to.

    Attributes
    ----------
    callee : str
        The called name as written: ``"Block"``, ``#instance``, ``TON``.
    instance : str | None
        For an FB instance call (``#tmr(...)``), the instance variable's name
        without ``#``; ``None`` for a FUNCTION or builtin call.
    parameter : str
        The parameter this access binds.
    direction : str
        ``":="`` for an input, ``"=>"`` for an output.
    inputs : dict[str, str]
        Every ``:=`` parameter of the call, to its value's spelling.
    outputs : dict[str, str]
        Every ``=>`` parameter of the call, to its target's spelling.
    text : str
        The whole call as written.
    """

    callee: str
    instance: str | None
    parameter: str
    direction: str
    inputs: dict[str, str]
    outputs: dict[str, str]
    text: str


@dataclass(frozen=True)
class Access:
    """One read or write of a path by one statement (or ladder element).

    Attributes
    ----------
    path : str
        The accessed path as written: ``"DB".a.b[#i]``, ``#local.x``, ``%I0.0``,
        ``"TAG"``.
    kind : str
        :data:`READ` or :data:`WRITE`.
    block_name : str
        The block the access is in.
    line : int
        Source line of the statement (``0`` for a ladder element, which carries
        no line).
    statement : str
        The statement as written, for a reader.
    expression : str
        For a write, what is written: the value's spelling, or the call's. For a
        read, the statement.
    dependencies : list[str]
        For a write, every path the value reads (global paths as written, a bare
        quoted symbol without its quotes, a local by its root ``#name``); for a
        read, the statement's write targets.
    call : CallContext | None
        Set when the access is a parameter binding of a call.
    element : str
        What produced it: ``assignment``, ``call``, ``condition``, ``selector``
        (a CASE's own variable), ``label`` (a CASE arm's value), ``bounds``,
        ``contact``, ``coil``, ``box``, ``callbox``.
    """

    path: str
    kind: str
    block_name: str
    line: int
    statement: str
    expression: str
    dependencies: list[str] = field(default_factory=list)
    call: CallContext | None = None
    element: str = "assignment"

    @property
    def is_write(self) -> bool:
        return self.kind == WRITE

    @property
    def is_global(self) -> bool:
        """A global DB path, tag, or absolute address (anything not ``#local``)."""
        return not self.path.startswith("#")


@dataclass
class BlockAccessIndex:
    """All accesses of one block, plus what could not be read."""

    block_name: str
    accesses: list[Access] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)

    def reads(self) -> Iterator[Access]:
        return (access for access in self.accesses if access.kind == READ)

    def writes(self) -> Iterator[Access]:
        return (access for access in self.accesses if access.kind == WRITE)


def build_access_index(block: Block) -> BlockAccessIndex:
    """Index every access in ``block`` from its SCL statements and ladder rungs."""
    index = BlockAccessIndex(block_name=block.name)
    builder = _Builder(block, index)
    # Gate on the networks' own content, not the block's preferred-language pragma:
    # an FBD-flagged block still carries its rungs as ladder elements.
    if any(network.ladder_elements or network.rungs_raw for network in block.networks):
        builder.ladder(block)
    for network in block.networks:
        if network.tokens:
            builder.tokens(network.tokens)
        for region in network.regions:
            if region.tokens:
                builder.tokens(region.tokens)
    return index


_CACHE: dict[int, tuple[weakref.ref[Block], BlockAccessIndex]] = {}


def access_index(block: Block) -> BlockAccessIndex:
    """:func:`build_access_index`, cached per block object for a tracing session.

    The entry is keyed by the object's id but only honoured while a weak
    reference still points at that same object: a block that was dropped and
    re-parsed at a reused address gets a fresh index, never the old file's.
    """
    key = id(block)
    entry = _CACHE.get(key)
    if entry is not None and entry[0]() is block:
        return entry[1]
    index = build_access_index(block)

    def evict(_ref: weakref.ref[Block], key: int = key) -> None:
        _CACHE.pop(key, None)

    _CACHE[key] = (weakref.ref(block, evict), index)
    return index


def clear_access_index_cache() -> None:
    """Drop every cached index (a service reloading its source tree calls this)."""
    _CACHE.clear()


# -- building ----------------------------------------------------------------------


class _Builder:
    def __init__(self, block: Block, index: BlockAccessIndex) -> None:
        self.block = block
        self.index = index
        self.instance_types = {var.name: var.data_type for var in block.static_vars}
        self._network = 0

    # SCL

    def tokens(self, tokens: list[Token]) -> None:
        result = parse_statements(tokens)
        for error in result.errors:
            self.index.parse_errors.append(error.message)
        for error in result.expression_errors:
            self.index.parse_errors.append(error.message)
        self.index.parse_errors.extend(verify_no_silent_loss(tokens, result))
        self.statements(result.statements)

    def statements(self, statements: list[Statement]) -> None:
        for statement in statements:
            if isinstance(statement, Assignment):
                self.assignment(statement)
            elif isinstance(statement, Call):
                self.call(statement)
            elif isinstance(statement, If):
                for branch in statement.branches:
                    line = branch.condition[0].line if branch.condition else statement.line
                    self.reads_of(branch.condition_expr, line, "condition", [])
                    self.statements(branch.body)
                self.statements(statement.else_body)
            elif isinstance(statement, Case):
                # Only the selector's own path is the state variable; an index
                # inside it (`CASE #arms[#i].mode OF`) is an ordinary read.
                selector = statement.selector_expr
                if isinstance(selector, ast.VariableRef | ast.Member | ast.Index):
                    self.reads_of(selector, statement.line, "selector", [], outermost_only=True)
                    for index_expr in _index_expressions(selector):
                        self.reads_of(index_expr, statement.line, "selector_index", [])
                else:
                    self.reads_of(selector, statement.line, "selector_expression", [])
                for arm in statement.branches:
                    for value in arm.values_expr:
                        self.reads_of(value, statement.line, "label", [])
                    self.statements(arm.body)
                self.statements(statement.default)
            elif isinstance(statement, For):
                variable = "".join(token.value for token in statement.variable)
                bounds = [b for b in (statement.start_expr, statement.end_expr, statement.step_expr) if b]
                text = f"FOR {variable} := {' TO '.join(expression_text(b) for b in bounds[:2])} DO"
                self.index.accesses.append(
                    Access(
                        path=variable,
                        kind=WRITE,
                        block_name=self.block.name,
                        line=statement.line,
                        statement=text,
                        expression=text,
                        dependencies=[n for b in bounds for n in _dependency_names(b)],
                        element="bounds",
                    )
                )
                for bound in bounds:
                    self.reads_of(bound, statement.line, "bounds", [variable], text)
                self.statements(statement.body)
            elif isinstance(statement, While):
                self.reads_of(statement.condition_expr, statement.line, "condition", [])
                self.statements(statement.body)

    def assignment(self, statement: Assignment) -> None:
        if statement.target_expr is None or statement.value_expr is None:
            self.index.parse_errors.append(f"line {statement.line}: assignment has no parsed expression tree")
            return
        target = expression_text(statement.target_expr)
        value = expression_text(statement.value_expr)
        text = f"{target} := {value};"
        self.index.accesses.append(
            Access(
                path=target,
                kind=WRITE,
                block_name=self.block.name,
                line=statement.line,
                statement=text,
                expression=value,
                dependencies=_dependency_names(statement.value_expr),
                element="assignment",
            )
        )
        # The target's own indices are read to know where to write.
        for index_expr in _index_expressions(statement.target_expr):
            self.reads_of(index_expr, statement.line, "assignment", [target], text)
        self.reads_of(statement.value_expr, statement.line, "assignment", [target], text)
        self.nested_outputs(statement.value_expr, statement.line, text)

    def call(self, statement: Call) -> None:
        if statement.callee_expr is None:
            callee_text = " ".join(token.value for token in statement.callee)
            self.index.parse_errors.append(
                f"line {statement.line}: call of {callee_text!r} has no parsed callee"
            )
            return
        callee = expression_text(statement.callee_expr)
        instance = _instance_name(statement.callee_expr)
        inputs: dict[str, str] = {}
        outputs: dict[str, str] = {}
        parts: list[str] = []
        for argument in statement.arguments:
            if argument.value_expr is None:
                self.index.parse_errors.append(
                    f"line {statement.line}: argument {argument.name!r} has no parsed expression tree"
                )
                continue
            spelled = expression_text(argument.value_expr)
            (outputs if argument.is_output else inputs)[argument.name] = spelled
            parts.append(f"{argument.name} {'=>' if argument.is_output else ':='} {spelled}")
        text = f"{callee}({', '.join(parts)});"
        input_paths: list[str] = []
        for argument in statement.arguments:
            if not argument.is_output and argument.value_expr is not None:
                input_paths.extend(n for n in _dependency_names(argument.value_expr) if n not in input_paths)

        def context(parameter: str, direction: str) -> CallContext:
            return CallContext(callee, instance, parameter, direction, dict(inputs), dict(outputs), text)

        for argument in statement.arguments:
            if argument.value_expr is None:
                continue
            if argument.is_output:
                target = expression_text(argument.value_expr)
                self.index.accesses.append(
                    Access(
                        path=target,
                        kind=WRITE,
                        block_name=self.block.name,
                        line=statement.line,
                        statement=text,
                        expression=text,
                        dependencies=list(input_paths),
                        call=context(argument.name, "=>"),
                        element="call",
                    )
                )
                for index_expr in _index_expressions(argument.value_expr):
                    self.reads_of(index_expr, statement.line, "call", [target], text)
            else:
                self.reads_of(
                    argument.value_expr,
                    statement.line,
                    "call",
                    list(outputs.values()),
                    text,
                    call=context(argument.name, ":="),
                )
        root = _root(statement.callee_expr)
        if instance is not None or (isinstance(root, ast.VariableRef) and not root.is_absolute):
            # Calling an instance (`#tmr`, or a global instance DB `"TON_DB"`)
            # reads and updates its own state. A FUNCTION called by its quoted
            # name gets the same record; nothing reads a FUNCTION's name as a path.
            self.index.accesses.append(
                Access(
                    path=callee,
                    kind=WRITE,
                    block_name=self.block.name,
                    line=statement.line,
                    statement=text,
                    expression=text,
                    dependencies=list(input_paths),
                    element="call",
                )
            )

    def reads_of(
        self,
        expression: ast.Expression | None,
        line: int,
        element: str,
        targets: list[str],
        text: str | None = None,
        call: CallContext | None = None,
        outermost_only: bool = False,
    ) -> None:
        """One READ access per reference in ``expression`` (calls' inputs included).

        A call's ``=>`` output inside the expression is not a read; see
        :meth:`nested_outputs`.
        """
        if expression is None:
            return
        statement = text if text is not None else f"{expression_text(expression)}"
        references = [expression] if outermost_only else list(_references(expression))
        for reference in references:
            self.index.accesses.append(
                Access(
                    path=expression_text(reference),
                    kind=READ,
                    block_name=self.block.name,
                    line=line,
                    statement=statement,
                    expression=statement,
                    dependencies=list(targets),
                    call=call,
                    element=element,
                )
            )

    def nested_outputs(self, expression: ast.Expression | None, line: int, text: str) -> None:
        """A WRITE for every ``=>`` output of a call nested in ``expression``."""
        if expression is None:
            return
        for call_node, argument in _nested_outputs(expression):
            inputs = {a.name: expression_text(a.value) for a in call_node.arguments if not a.is_output}
            outputs = {a.name: expression_text(a.value) for a in call_node.arguments if a.is_output}
            callee = f'"{call_node.name}"' if call_node.is_quoted else call_node.name
            context = CallContext(
                callee, None, argument.name, "=>", inputs, outputs, expression_text(call_node)
            )
            target = expression_text(argument.value)
            dependencies: list[str] = []
            for a in call_node.arguments:
                if not a.is_output:
                    dependencies.extend(n for n in _dependency_names(a.value) if n not in dependencies)
            self.index.accesses.append(
                Access(
                    path=target,
                    kind=WRITE,
                    block_name=self.block.name,
                    line=line,
                    statement=text,
                    expression=context.text,
                    dependencies=dependencies,
                    call=context,
                    element="call",
                )
            )
            for index_expr in _index_expressions(argument.value):
                self.reads_of(index_expr, line, "call", [target], text)

    # Ladder

    def ladder(self, block: Block) -> None:
        """Every network's rungs; a network the rung builder refuses is indexed
        element by element instead, with the refusal recorded."""
        for ordinal, network in enumerate(block.networks, 1):
            # A rung carries no source line; the network's ordinal (1-based)
            # stands in, so accesses of two networks never collapse into one.
            self._network = ordinal
            try:
                rungs = build_network_rungs(network)
            except ValueError as error:
                self.index.parse_errors.append(
                    f"network {ordinal}: rungs not built ({error}); elements indexed one by one"
                )
                self.ladder_elements(network)
                continue
            for rung in rungs:
                if isinstance(rung, Rung):
                    self.rung(rung)

    def ladder_elements(self, network: Network) -> None:
        """Fallback for one network: every element on its own; a coil depends on
        the contacts seen before it in the network."""
        contacts: list[str] = []
        for element in network.ladder_elements:
            if element.startswith("wire#") or element.startswith("Label("):
                continue  # rung plumbing, not an instruction
            try:
                node = parse_ladder_element(element)
            except ValueError as error:
                self.index.parse_errors.append(str(error))
                continue
            if isinstance(node, Contact):
                contacts.append(node.operand)
                self._ladder_access(node.operand, READ, "contact", element, [])
            elif isinstance(node, CompareContact):
                for operand in (node.in1, node.in2):
                    contacts.append(operand)
                    self._ladder_access(operand, READ, "contact", element, [])
            elif isinstance(node, Coil):
                self._ladder_access(node.operand, WRITE, "coil", element, list(contacts))
            elif isinstance(node, Box):
                text = _box_text(node)
                for operand in node.inputs.values():
                    self._ladder_access(operand, READ, "box", text, list(node.outputs.values()))
                for operand in node.outputs.values():
                    self._ladder_access(operand, WRITE, "box", text, [*contacts, *node.inputs.values()])
            elif isinstance(node, CallBox):
                self.callbox(node, contacts)

    def rung(self, rung: Rung) -> None:
        contacts: list[str] = []
        for term in rung.rail:
            for contact in term:
                if isinstance(contact, Contact):
                    contacts.append(contact.operand)
                    self._ladder_access(contact.operand, READ, "contact", f"Contact({contact.operand})", [])
                elif isinstance(contact, CompareContact):
                    for operand in (contact.in1, contact.in2):
                        contacts.append(operand)
                        self._ladder_access(
                            operand, READ, "contact", f"Compare{contact.op}({contact.in1}, {contact.in2})", []
                        )
        for action in rung.actions:
            if isinstance(action, Coil):
                self._ladder_access(action.operand, WRITE, "coil", f"Coil({action.operand})", list(contacts))
            elif isinstance(action, Box):
                text = _box_text(action)
                inputs = list(action.inputs.values())
                for operand in inputs:
                    self._ladder_access(operand, READ, "box", text, list(action.outputs.values()))
                for operand in action.outputs.values():
                    self._ladder_access(operand, WRITE, "box", text, [*contacts, *inputs])
            elif isinstance(action, CallBox):
                self.callbox(action, contacts)

    def callbox(self, action: CallBox, contacts: list[str]) -> None:
        inputs = {name: operand for name, direction, operand in action.params if direction == ":="}
        outputs = {name: operand for name, direction, operand in action.params if direction == "=>"}
        text = f"{action.name}({', '.join(f'{n} {d} {o}' for n, d, o in action.params)})"
        instance = action.name.lstrip("#") if action.name.startswith("#") else None
        for name, direction, operand in action.params:
            context = CallContext(action.name, instance, name, direction, dict(inputs), dict(outputs), text)
            if direction == "=>":
                self._ladder_access(operand, WRITE, "callbox", text, [*contacts, *inputs.values()], context)
            else:
                self._ladder_access(operand, READ, "callbox", text, list(outputs.values()), context)

    def _ladder_access(
        self,
        operand: str,
        kind: str,
        element: str,
        text: str,
        dependencies: list[str],
        call: CallContext | None = None,
    ) -> None:
        if _is_ladder_literal(operand):
            return
        self.index.accesses.append(
            Access(
                path=operand,
                kind=kind,
                block_name=self.block.name,
                line=self._network,
                statement=text,
                expression=_ladder_expression(kind, element, text, dependencies),
                dependencies=[d for d in dependencies if not _is_ladder_literal(d)],
                call=call,
                element=element,
            )
        )


# -- helpers -------------------------------------------------------------------------


def _references(expression: ast.Expression) -> Iterator[ast.VariableRef | ast.Member | ast.Index]:
    """Every reference path in ``expression``, outermost first, index expressions too."""
    if isinstance(expression, ast.VariableRef | ast.Member | ast.Index):
        yield expression
        for index_expr in _index_expressions(expression):
            yield from _references(index_expr)
        return
    if isinstance(expression, ast.Grouping):
        yield from _references(expression.inner)
    elif isinstance(expression, ast.UnaryOp):
        yield from _references(expression.operand)
    elif isinstance(expression, ast.BinaryOp):
        yield from _references(expression.left)
        yield from _references(expression.right)
    elif isinstance(expression, ast.FunctionCall):
        for argument in expression.arguments:
            if argument.is_output:
                # A `=>` target is written, not read; its own indices are read.
                for index_expr in _index_expressions(argument.value):
                    yield from _references(index_expr)
                continue
            yield from _references(argument.value)


def _nested_outputs(expression: ast.Expression) -> Iterator[tuple[ast.FunctionCall, ast.CallArgument]]:
    """Every ``=>`` argument of every call nested anywhere in ``expression``."""
    if isinstance(expression, ast.FunctionCall):
        for argument in expression.arguments:
            if argument.is_output:
                yield expression, argument
            else:
                yield from _nested_outputs(argument.value)
    elif isinstance(expression, ast.Grouping):
        yield from _nested_outputs(expression.inner)
    elif isinstance(expression, ast.UnaryOp):
        yield from _nested_outputs(expression.operand)
    elif isinstance(expression, ast.BinaryOp):
        yield from _nested_outputs(expression.left)
        yield from _nested_outputs(expression.right)
    elif isinstance(expression, ast.Index):
        for index_expr in expression.indices:
            yield from _nested_outputs(index_expr)


def _index_expressions(reference: ast.Expression) -> Iterator[ast.Expression]:
    """Every index expression along a reference path, innermost base first."""
    chain: list[ast.Expression] = []
    node = reference
    while isinstance(node, ast.Member | ast.Index):
        chain.append(node)
        node = node.base
    for link in reversed(chain):
        if isinstance(link, ast.Index):
            yield from link.indices


def _root(reference: ast.Expression) -> ast.Expression:
    node = reference
    while isinstance(node, ast.Member | ast.Index):
        node = node.base
    return node


def _dependency_names(expression: ast.Expression) -> list[str]:
    """The spelling the tracers match on: a global path whole, a bare quoted symbol
    bare, a local by its root ``#name``."""
    names: list[str] = []
    for reference in _references(expression):
        root = _root(reference)
        if not isinstance(root, ast.VariableRef):
            continue
        if root.is_local:
            name = f"#{root.name}"
        elif isinstance(reference, ast.VariableRef) and not root.is_absolute:
            name = root.name  # `"TAG"` -> TAG, what the tag matchers expect
        else:
            name = expression_text(reference)
        if name not in names:
            names.append(name)
    return names


def _is_ladder_literal(operand: str) -> bool:
    """``TRUE``, ``-9000``, ``T#5s``, ``16#FF``: a constant operand, not a path."""
    text = operand.strip()
    if not text or text.upper() in ("TRUE", "FALSE"):
        return True
    head = text[1:] if text[0] in "+-" else text
    return bool(head) and (head[0].isdigit() or (len(head) > 1 and head[1] == "#" and head[0].isalpha()))


def _instance_name(callee: ast.Expression) -> str | None:
    root = _root(callee)
    if isinstance(root, ast.VariableRef) and root.is_local:
        return root.name
    return None


def _ladder_expression(kind: str, element: str, text: str, dependencies: list[str]) -> str:
    """What a ladder write writes: a box's input for a Move, the element text otherwise."""
    if kind == WRITE and element == "box" and dependencies:
        return dependencies[-1]
    return text


def _box_text(box: Box) -> str:
    parts = [f"{name} := {value}" for name, value in box.inputs.items()]
    parts += [f"{name} => {value}" for name, value in box.outputs.items()]
    return f"{box.op}({', '.join(parts)})"


__all__ = [
    "READ",
    "WRITE",
    "Access",
    "BlockAccessIndex",
    "CallContext",
    "access_index",
    "build_access_index",
    "clear_access_index_cache",
]
