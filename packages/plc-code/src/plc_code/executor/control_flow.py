"""Control flow statement translation for SCL to Python.

This module provides parsing and translation of SCL control flow statements
including IF, CASE, WHILE, and FOR constructs.
"""

import re
from dataclasses import dataclass, field

from plc_code.executor.codegen import ExpressionTranslator, StatementTranslator


@dataclass
class ControlFlowTranslator:
    """Translates SCL control flow statements to Python.

    This class handles parsing and translation of:
    - IF/ELSIF/ELSE/END_IF
    - CASE/OF/END_CASE
    - WHILE/DO/END_WHILE
    - FOR/TO/DO/END_FOR
    """

    expr_translator: ExpressionTranslator = field(default_factory=ExpressionTranslator)
    stmt_translator: StatementTranslator = field(default_factory=StatementTranslator)
    _indent: int = 0

    def translate_block(self, scl_code: str) -> list[str]:
        """Translate a block of SCL code to Python statements.

        Parameters
        ----------
        scl_code : str
            SCL code block to translate.

        Returns
        -------
        list[str]
            List of Python statements with proper indentation.
        """
        lines = self._preprocess(scl_code)
        return self._translate_statements(lines)

    def _preprocess(self, code: str) -> list[str]:
        """Preprocess SCL code into normalized lines.

        Parameters
        ----------
        code : str
            Raw SCL code.

        Returns
        -------
        list[str]
            Preprocessed lines.
        """
        raw_lines: list[str] = []

        for line in code.split("\n"):
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith("//"):
                continue

            # Skip pragma lines
            if line.startswith("{") or line.startswith("}"):
                continue

            # Skip REGION markers (including END_REGION with optional trailing name)
            if line.upper().startswith("REGION") or line.upper().startswith("END_REGION"):
                continue

            # Strip a trailing inline ``//`` comment.  TIA Portal glues an inline
            # comment onto the code line (``IF #f THEN // note``), so a whole-line
            # skip is not enough: an inline comment left as the first body token
            # after ``THEN``/``ELSE`` would otherwise be captured as a body
            # statement and leak into the generated Python as invalid syntax.
            line = self._strip_inline_comment(line)
            if not line:
                continue

            # Normalize spacing around keywords that may have been stripped
            line = self._normalize_spacing(line)

            raw_lines.append(line)

        # Join continuation lines: TIA Portal preserves the author's line breaks
        # inside a REGION, so a single SCL statement may span several physical
        # lines.  Two shapes occur:
        #   1. the line ends with a dangling operator (``:=``, ``+``, ``(`` ...):
        #          #matrixResult[#i, #k] :=
        #              #matrixResult[#i, #k] * #matrixResult[#k, #k] ;
        #   2. the next line *starts* with a binary operator (operator-led
        #      continuation), which is never valid at the start of a statement:
        #          #s := #a
        #              + #b * 2.0
        #              + #c * 3.0 ;
        # We greedily absorb following lines until the statement is complete
        # (i.e. terminated by ``;`` or no longer looking like a continuation).
        lines: list[str] = []
        i = 0
        while i < len(raw_lines):
            current = raw_lines[i]
            while i + 1 < len(raw_lines):
                cur_stripped = current.rstrip()
                if cur_stripped.endswith(";"):
                    break
                nxt = raw_lines[i + 1].strip()
                if not self._is_continuation(cur_stripped, nxt):
                    break
                current = cur_stripped + " " + nxt
                i += 1
            lines.append(current)
            i += 1

        # Split an inline nested control-flow header off the line that carries the
        # enclosing keyword.  TIA Portal (and hand-written SCL) may place a nested
        # ``IF``/``CASE``/``WHILE``/``FOR`` on the SAME physical line as the outer
        # ``THEN``/``ELSE``/``DO`` (e.g. ``IF #a THEN IF #b THEN ... ;``).  The
        # inline-body capture in :meth:`_translate_if_block` would otherwise grab
        # the nested header WITHOUT its matching ``END_IF`` (which sits on a later
        # line), silently dropping the whole nested statement and leaking a stray
        # ``END_IF``.  Giving every nested header its own line routes it through the
        # correct multi-line nested path instead.
        expanded: list[str] = []
        for line in lines:
            split = self._INLINE_COMPOUND_SPLIT.sub(r"\1\n\2", line)
            expanded.extend(part.strip() for part in split.split("\n") if part.strip())

        return expanded

    def _strip_inline_comment(self, line: str) -> str:
        """Remove a trailing ``//`` line comment, respecting string literals.

        A ``//`` inside a single- or double-quoted literal is left untouched; the
        first ``//`` outside any quote truncates the line.

        Parameters
        ----------
        line : str
            A single, already-stripped source line.

        Returns
        -------
        str
            The line with any trailing inline comment removed (right-stripped).
        """
        in_squote = False
        in_dquote = False
        for idx in range(len(line) - 1):
            ch = line[idx]
            if ch == "'" and not in_dquote:
                in_squote = not in_squote
            elif ch == '"' and not in_squote:
                in_dquote = not in_dquote
            elif ch == "/" and line[idx + 1] == "/" and not in_squote and not in_dquote:
                return line[:idx].rstrip()
        return line

    # A nested control-flow keyword directly following THEN/ELSE/DO on the same
    # physical line starts a new statement and must be broken onto its own line.
    _INLINE_COMPOUND_SPLIT = re.compile(
        r"\b(THEN|ELSE|DO)\b\s+(IF|CASE|WHILE|FOR)\b",
        re.IGNORECASE,
    )

    # Operators that, at the end of a line, require a right-hand side on the next.
    _CONT_END = re.compile(r"(:=|[-+*/(,<>=])$")
    _CONT_END_KW = re.compile(r"\b(AND|OR|MOD|DIV|NOT|TO|BY)$", re.IGNORECASE)
    # Operators that, at the start of a line, mark it as a continuation of the
    # previous one (a statement can never legitimately *begin* with these).
    _CONT_START = re.compile(r"^[-+*/).,<>=]")
    _CONT_START_KW = re.compile(r"^(AND|OR|MOD|DIV)\b", re.IGNORECASE)

    def _is_continuation(self, current: str, nxt: str) -> bool:
        """Return True if ``nxt`` continues the (unterminated) statement ``current``.

        Parameters
        ----------
        current : str
            The accumulated statement so far (already right-stripped, not ending
            in ``;``).
        nxt : str
            The next physical line, left/right-stripped.
        """
        if not nxt:
            return False
        if current.endswith(":=") or self._CONT_END.search(current) or self._CONT_END_KW.search(current):
            return True
        if self._CONT_START.match(nxt) or self._CONT_START_KW.match(nxt):
            return True
        return False

    def _normalize_spacing(self, line: str) -> str:
        """Normalize spacing around SCL keywords.

        The parser may strip spaces between tokens, so we need to restore them.
        This handles cases like:
        - IF#var -> IF #var
        - #varANDNOT(#var) -> #var AND NOT (#var)
        - CASE#varOF -> CASE #var OF

        Parameters
        ----------
        line : str
            Line that may have missing spaces.

        Returns
        -------
        str
            Line with proper spacing around keywords.
        """
        result = line

        # Use case-insensitive matching throughout
        # We need to ensure keyword operators are properly spaced without matching
        # keywords embedded within variable names (e.g., "hornAcknowledge" contains "OR")

        # Strategy: Use word boundaries but then also handle concatenated keywords
        # by explicitly looking for known keyword-to-keyword transitions

        # First, handle keyword-to-keyword transitions where there's no space
        # These are unambiguous: ANDNOT, ORNOT, etc.
        result = re.sub(r"AND(NOT)", r"AND \1", result, flags=re.IGNORECASE)
        result = re.sub(r"OR(NOT)", r"OR \1", result, flags=re.IGNORECASE)
        result = re.sub(r"AND(IF)", r"AND \1", result, flags=re.IGNORECASE)
        result = re.sub(r"OR(IF)", r"OR \1", result, flags=re.IGNORECASE)

        # Handle keyword followed by # (instance variable)
        result = re.sub(r"\bAND#", "AND #", result, flags=re.IGNORECASE)
        result = re.sub(r"\bOR#", "OR #", result, flags=re.IGNORECASE)
        result = re.sub(r"\bNOT#", "NOT #", result, flags=re.IGNORECASE)

        # Handle keyword followed by (
        result = re.sub(r"\bAND\(", "AND (", result, flags=re.IGNORECASE)
        result = re.sub(r"\bOR\(", "OR (", result, flags=re.IGNORECASE)
        result = re.sub(r"\bNOT\(", "NOT (", result, flags=re.IGNORECASE)

        # Handle ) followed by keyword
        result = re.sub(r"\)AND\b", ") AND", result, flags=re.IGNORECASE)
        result = re.sub(r"\)OR\b", ") OR", result, flags=re.IGNORECASE)
        result = re.sub(r"\)NOT\b", ") NOT", result, flags=re.IGNORECASE)

        # Now handle identifiers that end with AND/OR followed by keyword
        # Pattern: 2+ wordchars followed by AND/OR - this naturally excludes BAND/FOR/XOR/NOR
        # which only have 1 char before AND/OR.
        # Only split when OR/AND is directly concatenated (no preceding space) and followed
        # by #, ( or NOT (not just whitespace, to avoid splitting words like "error" or "forward").
        result = re.sub(r"(\w{2,})(AND)(NOT\b|[#(])", r"\1 \2 \3", result, flags=re.IGNORECASE)
        result = re.sub(r"(\w{2,})(OR)(NOT\b|[#(])", r"\1 \2 \3", result, flags=re.IGNORECASE)

        # Handle word char followed by AND/OR before another word char (like #var)
        # This handles: varAND#var -> var AND #var
        # Require 2+ chars before AND/OR to preserve BAND/FOR/XOR/NOR
        result = re.sub(r"(\w{2,})(AND)\s*#", r"\1 \2 #", result, flags=re.IGNORECASE)
        result = re.sub(r"(\w{2,})(OR)\s*#", r"\1 \2 #", result, flags=re.IGNORECASE)

        # Handle word char followed by AND/OR at end (before THEN, etc.)
        # Require 2+ chars before AND/OR to preserve keywords.
        # IMPORTANT: Only split when AND/OR is NOT a substring of a real identifier.
        # We detect "real" concatenation by requiring that there is NO space between
        # the identifier part and AND/OR (i.e. they appear directly glued together),
        # and that OR/AND is not preceded by a word-char that would make it part of a
        # word like "mulError" (er-OR), "forward" (forw-AND), etc.
        # Strategy: require the AND/OR to be immediately followed by the keyword
        # WITH NO SPACE (direct concatenation), so "varORTHEN" not "mulError THEN".
        result = re.sub(r"(\w{2,})(AND)(THEN|DO|OF)\b", r"\1 \2 \3", result, flags=re.IGNORECASE)
        result = re.sub(r"(\w{2,})(OR)(THEN|DO|OF)\b", r"\1 \2 \3", result, flags=re.IGNORECASE)

        # IF - ensure space after
        result = re.sub(r"\bIF(?=[^\s])", "IF ", result, flags=re.IGNORECASE)

        # ELSIF - ensure space after
        result = re.sub(r"\bELSIF(?=[^\s])", "ELSIF ", result, flags=re.IGNORECASE)

        # WHILE - ensure space after
        result = re.sub(r"\bWHILE(?=[^\s])", "WHILE ", result, flags=re.IGNORECASE)

        # CASE - ensure space after
        result = re.sub(r"\bCASE(?=[^\s])", "CASE ", result, flags=re.IGNORECASE)

        # FOR - ensure space after (must come after OR handling).
        # Negative lookbehind (?<!") prevents matching "For..." inside quoted block
        # names like "ForwardKinematicMdh": the " immediately before F is non-word
        # (creating \b) but the block name must not be rewritten.
        result = re.sub(r'(?<!")\bFOR(?=[^\s])', "FOR ", result, flags=re.IGNORECASE)

        # THEN - ensure space before
        result = re.sub(r"(?<=[^\s])THEN\b", " THEN", result, flags=re.IGNORECASE)

        # DO/OF/TO/BY - ensure space before (FOR-loop / CASE glued keywords).
        # Only insert a space when the keyword is glued to a NON-LETTER (digit, ')',
        # ']', '.') i.e. the end of a real range/selector expression. A letter before
        # the keyword means it is the tail of an identifier (e.g. "triggerGoto" ->
        # "...Go" + "to", "autoBy", "infoOf") and must be left intact.
        result = re.sub(r"(?<=[^\sA-Za-z])DO\b", " DO", result, flags=re.IGNORECASE)
        result = re.sub(r"(?<=[^\sA-Za-z])OF\b", " OF", result, flags=re.IGNORECASE)
        result = re.sub(r"(?<=[^\sA-Za-z])TO\b", " TO", result, flags=re.IGNORECASE)
        result = re.sub(r"(?<=[^\sA-Za-z])BY\b", " BY", result, flags=re.IGNORECASE)

        # Clean up any double spaces that may have been introduced
        result = re.sub(r"  +", " ", result)

        return result

    def _translate_statements(self, lines: list[str]) -> list[str]:
        """Translate a list of statement lines.

        Parameters
        ----------
        lines : list[str]
            Preprocessed lines.

        Returns
        -------
        list[str]
            Translated Python statements.
        """
        result: list[str] = []
        i = 0

        while i < len(lines):
            line = lines[i]
            upper = line.upper()

            # Handle IF statement
            if upper.startswith("IF ") or upper == "IF":
                block_lines, i = self._extract_if_block(lines, i)
                result.extend(self._translate_if_block(block_lines))

            # Handle CASE statement
            elif upper.startswith("CASE "):
                block_lines, i = self._extract_case_block(lines, i)
                result.extend(self._translate_case_block(block_lines))

            # Handle WHILE statement
            elif upper.startswith("WHILE ") or upper.startswith("WHILE("):
                block_lines, i = self._extract_while_block(lines, i)
                result.extend(self._translate_while_block(block_lines))

            # Handle FOR statement
            elif upper.startswith("FOR "):
                block_lines, i = self._extract_for_block(lines, i)
                result.extend(self._translate_for_block(block_lines))

            # Handle simple statements
            else:
                translated = self._translate_simple_statement(line)
                if translated:
                    result.extend(translated)
                i += 1

        return result

    def _extract_if_block(self, lines: list[str], start: int) -> tuple[list[str], int]:
        """Extract IF block including ELSIF/ELSE branches.

        Parameters
        ----------
        lines : list[str]
            All lines.
        start : int
            Starting index of IF.

        Returns
        -------
        tuple[list[str], int]
            Block lines and next index.
        """
        block: list[str] = []
        depth = 0
        i = start

        while i < len(lines):
            line = lines[i]
            upper = line.upper()
            block.append(line)

            # Count IF depth
            if upper.startswith("IF ") or upper == "IF":
                depth += 1
            elif upper.rstrip("; ") == "END_IF":
                depth -= 1
                if depth == 0:
                    return block, i + 1

            i += 1

        return block, i

    def _extract_case_block(self, lines: list[str], start: int) -> tuple[list[str], int]:
        """Extract CASE block.

        Parameters
        ----------
        lines : list[str]
            All lines.
        start : int
            Starting index of CASE.

        Returns
        -------
        tuple[list[str], int]
            Block lines and next index.
        """
        block: list[str] = []
        depth = 0
        i = start

        while i < len(lines):
            line = lines[i]
            upper = line.upper()
            block.append(line)

            if upper.startswith("CASE "):
                depth += 1
            elif upper.rstrip("; ") == "END_CASE":
                depth -= 1
                if depth == 0:
                    return block, i + 1

            i += 1

        return block, i

    def _extract_while_block(self, lines: list[str], start: int) -> tuple[list[str], int]:
        """Extract WHILE block.

        Parameters
        ----------
        lines : list[str]
            All lines.
        start : int
            Starting index of WHILE.

        Returns
        -------
        tuple[list[str], int]
            Block lines and next index.
        """
        block: list[str] = []
        depth = 0
        i = start

        while i < len(lines):
            line = lines[i]
            upper = line.upper()
            block.append(line)

            if upper.startswith("WHILE ") or upper.startswith("WHILE("):
                depth += 1
            elif upper.rstrip("; ") == "END_WHILE":
                depth -= 1
                if depth == 0:
                    return block, i + 1

            i += 1

        return block, i

    def _extract_for_block(self, lines: list[str], start: int) -> tuple[list[str], int]:
        """Extract FOR block.

        Parameters
        ----------
        lines : list[str]
            All lines.
        start : int
            Starting index of FOR.

        Returns
        -------
        tuple[list[str], int]
            Block lines and next index.
        """
        block: list[str] = []
        depth = 0
        i = start

        while i < len(lines):
            line = lines[i]
            upper = line.upper()
            block.append(line)

            # Count all FOR...DO occurrences on this line (handles multiple FORs per line)
            for_count = len(re.findall(r"\bFOR\s+\S", upper))
            end_for_count = len(re.findall(r"\bEND_FOR\b", upper))
            depth += for_count - end_for_count
            if depth <= 0:
                return block, i + 1

            i += 1

        return block, i

    def _translate_if_block(self, block: list[str]) -> list[str]:
        """Translate IF/ELSIF/ELSE block to Python.

        Parameters
        ----------
        block : list[str]
            IF block lines.

        Returns
        -------
        list[str]
            Python if/elif/else statements.
        """
        result: list[str] = []
        body_lines: list[str] = []
        current_condition = ""
        current_keyword = ""
        depth = 0
        accumulating_condition = ""  # For multi-line conditions

        for line in block:
            upper = line.upper()

            # Check if we're accumulating a multi-line condition
            if accumulating_condition:
                # Continue accumulating until we find THEN
                if "THEN" in upper:
                    # Find THEN and extract everything before it
                    then_idx = upper.find("THEN")
                    condition_part = line[:then_idx].strip()
                    accumulating_condition += " " + condition_part
                    current_condition = accumulating_condition.strip()
                    accumulating_condition = ""
                    depth = 1
                    continue
                else:
                    # Keep accumulating
                    accumulating_condition += " " + line.strip()
                    continue

            # IF condition THEN [body] (single line, body may follow THEN)
            if_match = re.match(r"IF\s+(.+?)\s+THEN\b(.*)", line, re.IGNORECASE)
            if if_match and depth == 0:
                current_condition = if_match.group(1)
                current_keyword = "if"
                depth = 1
                # Capture any inline body statement after THEN on the same line
                inline_body = if_match.group(2).strip().rstrip(";").strip()
                if inline_body:
                    body_lines.append(inline_body)
                continue

            # IF without THEN on same line (multi-line condition)
            if_start_match = re.match(r"IF\s+(.+)", line, re.IGNORECASE)
            if if_start_match and depth == 0 and "THEN" not in upper:
                current_keyword = "if"
                accumulating_condition = if_start_match.group(1).strip()
                continue

            # Nested IF increases depth
            if (upper.startswith("IF ") or upper == "IF") and depth > 0:
                depth += 1
                body_lines.append(line)
                continue

            # ELSIF condition THEN [body] (single line, body may follow THEN)
            elsif_match = re.match(r"ELSIF\s+(.+?)\s+THEN\b(.*)", line, re.IGNORECASE)
            if elsif_match and depth == 1:
                # Output previous branch
                if current_keyword:
                    py_cond = self.expr_translator.translate(current_condition)
                    result.append(f"{current_keyword} {py_cond}:")
                    body = self._translate_statements(body_lines)
                    if body:
                        result.extend(["    " + ln for ln in body])
                    else:
                        result.append("    pass")

                current_condition = elsif_match.group(1)
                current_keyword = "elif"
                body_lines = []
                # Capture any inline body statement after THEN on the same line
                inline_body = elsif_match.group(2).strip().rstrip(";").strip()
                if inline_body:
                    body_lines.append(inline_body)
                continue

            # ELSIF without THEN (multi-line condition)
            elsif_start_match = re.match(r"ELSIF\s+(.+)", line, re.IGNORECASE)
            if elsif_start_match and depth == 1 and "THEN" not in upper:
                # Output previous branch
                if current_keyword:
                    py_cond = self.expr_translator.translate(current_condition)
                    result.append(f"{current_keyword} {py_cond}:")
                    body = self._translate_statements(body_lines)
                    if body:
                        result.extend(["    " + ln for ln in body])
                    else:
                        result.append("    pass")

                current_keyword = "elif"
                accumulating_condition = elsif_start_match.group(1).strip()
                body_lines = []
                continue

            # ELSE [body]  — matches bare "ELSE" or "ELSE <inline-body>"
            else_match = re.match(r"ELSE\b(.*)", line, re.IGNORECASE)
            if else_match and depth == 1:
                # Output previous branch
                if current_keyword:
                    py_cond = self.expr_translator.translate(current_condition)
                    result.append(f"{current_keyword} {py_cond}:")
                    body = self._translate_statements(body_lines)
                    if body:
                        result.extend(["    " + ln for ln in body])
                    else:
                        result.append("    pass")

                current_keyword = "else"
                current_condition = ""
                body_lines = []
                # Capture any inline body statement after ELSE on the same line
                inline_body = else_match.group(1).strip().rstrip(";").strip()
                if inline_body:
                    body_lines.append(inline_body)
                continue

            # END_IF
            if upper.rstrip("; ") == "END_IF":
                depth -= 1
                if depth == 0:
                    # Output final branch
                    if current_keyword == "else":
                        result.append("else:")
                    elif current_keyword:
                        py_cond = self.expr_translator.translate(current_condition)
                        result.append(f"{current_keyword} {py_cond}:")

                    body = self._translate_statements(body_lines)
                    if body:
                        result.extend(["    " + ln for ln in body])
                    else:
                        result.append("    pass")
                    break
                else:
                    body_lines.append(line)
                    continue

            # Accumulate body lines
            body_lines.append(line)

        return result

    def _translate_case_block(self, block: list[str]) -> list[str]:
        """Translate CASE/OF block to Python if/elif chain.

        Parameters
        ----------
        block : list[str]
            CASE block lines.

        Returns
        -------
        list[str]
            Python if/elif statements.
        """
        result: list[str] = []
        case_var = ""
        current_values: list[str] = []
        body_lines: list[str] = []
        is_first = True
        depth = 0

        for line in block:
            upper = line.upper()

            # CASE #var OF
            case_match = re.match(r"CASE\s+(.+?)\s+OF", line, re.IGNORECASE)
            if case_match and depth == 0:
                case_var = self.expr_translator.translate(case_match.group(1))
                depth = 1
                continue

            # Nested CASE increases depth
            if upper.startswith("CASE ") and depth > 0:
                depth += 1
                body_lines.append(line)
                continue

            # Case label: #VALUE: or "STRING_VALUE": or numeric values
            # (at start of line, not followed by =)
            # Must not match assignments like #activeState:=#ALARM;
            # Patterns:
            #   #NO_ALARM:
            #   "USER_FREEWHEEL":
            #   1, 2, 3:
            #   ELSE: (for default case)
            label_match = re.match(r'^\s*(#\w+|"\w+"|[\d,\s]+|ELSE)\s*:\s*$', line, re.IGNORECASE)
            if label_match and depth == 1 and not upper.rstrip("; ") == "END_CASE":
                # Output previous case if any
                if current_values and body_lines:
                    self._emit_case_branch(result, case_var, current_values, body_lines, is_first)
                    is_first = False

                # Parse new case values
                values_str = label_match.group(1)
                current_values = [self.expr_translator.translate(v.strip()) for v in values_str.split(",")]
                body_lines = []
                continue

            # END_CASE
            if upper.rstrip("; ") == "END_CASE":
                depth -= 1
                if depth == 0:
                    # Output final case
                    if current_values and body_lines:
                        self._emit_case_branch(result, case_var, current_values, body_lines, is_first)
                    break
                else:
                    body_lines.append(line)
                    continue

            # Accumulate body lines
            body_lines.append(line)

        return result

    def _emit_case_branch(
        self,
        result: list[str],
        case_var: str,
        values: list[str],
        body_lines: list[str],
        is_first: bool,
    ) -> None:
        """Emit a CASE branch as Python if/elif.

        Parameters
        ----------
        result : list[str]
            Result list to append to.
        case_var : str
            Variable being switched on.
        values : list[str]
            Values for this branch.
        body_lines : list[str]
            Body lines for this branch.
        is_first : bool
            Whether this is the first branch.
        """
        keyword = "if" if is_first else "elif"

        if len(values) == 1:
            condition = f"{case_var} == {values[0]}"
        else:
            condition = f"{case_var} in ({', '.join(values)})"

        result.append(f"{keyword} {condition}:")
        body = self._translate_statements(body_lines)
        if body:
            result.extend(["    " + ln for ln in body])
        else:
            result.append("    pass")

    def _translate_while_block(self, block: list[str]) -> list[str]:
        """Translate WHILE block to Python while.

        Parameters
        ----------
        block : list[str]
            WHILE block lines.

        Returns
        -------
        list[str]
            Python while statement.
        """
        result: list[str] = []
        condition = ""
        body_lines: list[str] = []
        depth = 0

        for line in block:
            upper = line.upper()

            # WHILE (condition) DO
            while_match = re.match(r"WHILE\s*\((.+?)\)\s*DO", line, re.IGNORECASE)
            if while_match and depth == 0:
                condition = while_match.group(1)
                depth = 1
                continue

            # Alternative: WHILE condition DO
            while_match2 = re.match(r"WHILE\s+(.+?)\s+DO", line, re.IGNORECASE)
            if while_match2 and depth == 0:
                condition = while_match2.group(1)
                depth = 1
                continue

            # Nested WHILE
            if (upper.startswith("WHILE ") or upper.startswith("WHILE(")) and depth > 0:
                depth += 1
                body_lines.append(line)
                continue

            # END_WHILE
            if upper.rstrip("; ") == "END_WHILE":
                depth -= 1
                if depth == 0:
                    py_cond = self.expr_translator.translate(condition)
                    result.append(f"while {py_cond}:")
                    body = self._translate_statements(body_lines)
                    if body:
                        result.extend(["    " + ln for ln in body])
                    else:
                        result.append("    pass")
                    break
                else:
                    body_lines.append(line)
                    continue

            body_lines.append(line)

        return result

    def _translate_for_block(self, block: list[str]) -> list[str]:
        """Translate FOR block to Python for.

        Parameters
        ----------
        block : list[str]
            FOR block lines.

        Returns
        -------
        list[str]
            Python for statement.
        """
        result: list[str] = []
        loop_var = ""
        start_val = ""
        end_val = ""
        step_val = "1"
        body_lines: list[str] = []
        depth = 0

        for line in block:
            upper = line.upper()

            # FOR #var := start TO end BY step DO [inline_body]
            for_match = re.match(
                r"FOR\s+(.+?)\s*:=\s*(.+?)\s+TO\s+(.+?)(?:\s+BY\s+(.+?))?\s+DO\b(.*)",
                line,
                re.IGNORECASE,
            )
            if for_match and depth == 0:
                loop_var = self.expr_translator.translate(for_match.group(1))
                start_val = self.expr_translator.translate(for_match.group(2))
                end_val = self.expr_translator.translate(for_match.group(3))
                if for_match.group(4):
                    step_val = self.expr_translator.translate(for_match.group(4))
                depth = 1
                # Capture any inline body content after DO on the same line.
                # Skip pure comment lines (starting with //) which TIA Portal sometimes
                # emits inline after DO (e.g. FOR j := 1 TO 6 DO // some comment).
                inline_body = for_match.group(5).strip().rstrip(";").strip() if for_match.group(5) else ""
                if inline_body and not inline_body.startswith("//"):
                    body_lines.append(inline_body)
                    # If inline body contains additional FOR loops, adjust depth to account
                    # for them (they will need matching END_FORs in subsequent lines)
                    inline_for_count = len(re.findall(r"\bFOR\s+\S", inline_body.upper()))
                    inline_end_for_count = len(re.findall(r"\bEND_FOR\b", inline_body.upper()))
                    depth += inline_for_count - inline_end_for_count
                continue

            # Nested FOR (may contain multiple FOR...DO on the same line)
            if upper.startswith("FOR ") and depth > 0:
                # Count all FOR and END_FOR on this line for accurate depth tracking
                line_for_count = len(re.findall(r"\bFOR\s+\S", upper))
                line_end_for_count = len(re.findall(r"\bEND_FOR\b", upper))
                depth += line_for_count - line_end_for_count
                body_lines.append(line)
                continue

            # END_FOR
            if upper.rstrip("; ") == "END_FOR":
                depth -= 1
                if depth == 0:
                    # Python range is exclusive on the upper bound
                    if step_val == "1":
                        result.append(f"for {loop_var} in range({start_val}, {end_val} + 1):")
                    else:
                        result.append(f"for {loop_var} in range({start_val}, {end_val} + 1, {step_val}):")
                    body = self._translate_statements(body_lines)
                    if body:
                        result.extend(["    " + ln for ln in body])
                    else:
                        result.append("    pass")
                    break
                else:
                    body_lines.append(line)
                    continue

            body_lines.append(line)

        return result

    # Pattern for quoted-name block call: "BlockName"(param1 := val, out => var, ...)
    _NAMED_BLOCK_CALL_PATTERN = re.compile(
        r'^"([^"]+)"\s*\((.*)[\);]',
        re.DOTALL,
    )

    def _translate_named_block_call(self, line: str) -> list[str] | None:
        """Translate a ``"BlockName"(param := val, ...)`` call to Python.

        This handles SCL FUNCTION/FUNCTION_BLOCK calls using the quoted-name
        syntax, dispatching to ``self._runtime.call_named_block()``.

        Parameters
        ----------
        line : str
            The SCL statement line.

        Returns
        -------
        list[str] | None
            Translated Python statements, or ``None`` if the line is not a
            quoted-name block call.
        """
        # Quick rejection: must start with a double-quote
        stripped = line.strip()
        if not stripped.startswith('"'):
            return None

        # Try to match "BlockName"(...)
        # We need to handle the full parameter list which may contain nested parens
        # Step 1: find the closing paren of the argument list
        match = re.match(r'^"([^"]+)"\s*\(', stripped)
        if not match:
            return None

        block_name = match.group(1)
        paren_start = match.end()  # position just after the opening '('

        # Find matching closing paren
        depth = 1
        pos = paren_start
        while pos < len(stripped) and depth > 0:
            if stripped[pos] == "(":
                depth += 1
            elif stripped[pos] == ")":
                depth -= 1
            pos += 1

        if depth != 0:
            return None  # unbalanced parens - not a valid call

        params_str = stripped[paren_start : pos - 1]  # content between outer parens

        return self._emit_named_call(block_name, params_str)[0]

    def _emit_named_call(self, block_name: str, params_str: str) -> tuple[list[str], str]:
        """Emit the Python statements for a ``"BlockName"(...)`` call.

        Shared by the standalone-call path and the return-value-assignment path
        so both wire ``=>`` outputs (and ``:=`` in-out write-back) identically.

        Parameters
        ----------
        block_name : str
            The sub-block name (without quotes).
        params_str : str
            The raw argument list between the outer parentheses.

        Returns
        -------
        tuple[list[str], str]
            The call + output-assignment statements, and the result-dict
            variable name (so the caller can also read the return value).
        """
        # Parse parameters: split by top-level commas
        params = self.stmt_translator._split_params(params_str)

        # Categorise parameters:
        #   param := val   ->  input (or in-out passed in)
        #   param => var   ->  output assignment
        input_params: dict[str, str] = {}  # name -> translated value expr
        output_params: list[tuple[str, str]] = []  # (block_output_name, target_var_expr)

        for param in params:
            param = param.strip()
            if not param:
                continue

            # Normalize `:=` and `=>`
            param = re.sub(r":\s*=", ":=", param)
            param = re.sub(r"=\s*>", "=>", param)

            if ":=" in param:
                name, value = param.split(":=", 1)
                name = name.strip()
                value_expr = self.expr_translator.translate(value.strip())
                input_params[name] = value_expr
            elif "=>" in param:
                name, target = param.split("=>", 1)
                name = name.strip()
                target_expr = self.expr_translator.translate(target.strip())
                output_params.append((name, target_expr))

        # Build Python statements
        # 1. Call the sub-block and capture its result dict
        result_var = f"_sub_{block_name.replace(' ', '_')}_result"
        inputs_dict = "{" + ", ".join(f'"{k}": {v}' for k, v in input_params.items()) + "}"
        call_line = f"{result_var} = self._runtime.call_named_block(" f'"{block_name}", {inputs_dict}, {{}})'
        result_lines = [call_line]

        # 2. Assign output parameters from result dict
        for out_name, target_expr in output_params:
            result_lines.append(f'{target_expr} = {result_var}["{out_name}"]')

        # 3. For `:=` params that are also outputs (i.e. in-out params),
        #    we read them back from the result dict if they appear there.
        #    The `:=` in-out semantics: value goes in, updated value comes out.
        #    We handle this by updating the target variable if the param appears in result.
        for in_name, value_expr in input_params.items():
            # Only write back if the value_expr is a self.xxx reference (not a literal)
            if value_expr.startswith("self.") and " " not in value_expr.strip():
                # This param may be an in-out: write back if present in result
                result_lines.append(
                    f'if "{in_name}" in {result_var}: {value_expr} = {result_var}["{in_name}"]'
                )

        return result_lines, result_var

    def _translate_named_call_assignment(
        self, target_expr: str, block_name: str, params_str: str
    ) -> list[str]:
        """Translate ``<target> := "BlockName"(... out => var ...)``.

        A FUNCTION whose return value is consumed in an assignment may ALSO bind
        ``=>`` outputs. The expression path can only return the value (it cannot
        emit the output-assignment statements), so this routes such a call
        through the multi-statement form and assigns the return value last.
        """
        result_lines, result_var = self._emit_named_call(block_name, params_str)
        result_lines.append(f'{target_expr} = {result_var}["{block_name}"]')
        return result_lines

    def _match_named_call_with_outputs(self, rhs: str) -> tuple[str, str] | None:
        """Return ``(block_name, params_str)`` if ``rhs`` is exactly one
        ``"BlockName"(...)`` call that binds at least one ``=>`` output.

        Returns ``None`` for anything else (plain return-value calls, mixed
        expressions, no outputs) so those keep the existing expression path.
        """
        rhs = rhs.strip().rstrip(";").strip()
        match = re.match(r'^"([^"]+)"\s*\(', rhs)
        if not match:
            return None
        # Find the matching close paren of the argument list.
        depth = 1
        pos = match.end()
        while pos < len(rhs) and depth > 0:
            if rhs[pos] == "(":
                depth += 1
            elif rhs[pos] == ")":
                depth -= 1
            pos += 1
        # The call must span the ENTIRE rhs (no trailing operators / operands).
        if depth != 0 or pos != len(rhs):
            return None
        params_str = rhs[match.end() : pos - 1]
        normalized_params = re.sub(r"=\s*>", "=>", params_str)
        if "=>" not in normalized_params:
            return None
        return match.group(1), params_str

    def _translate_simple_statement(self, line: str) -> list[str]:
        """Translate a simple (non-control-flow) statement.

        Parameters
        ----------
        line : str
            Single statement line.

        Returns
        -------
        list[str]
            Translated Python statements.
        """
        # Normalize spaces
        normalized = re.sub(r"#\s+", "#", line)
        normalized = re.sub(r"=\s*>", "=>", normalized)
        normalized = re.sub(r":\s*=", ":=", normalized)

        # Handle RETURN statement
        if normalized.strip().rstrip(";").strip().upper() == "RETURN":
            return ["return"]

        # Handle quoted-name block call: "BlockName"(params...)
        # Must be checked before assignment detection since these lines start with "
        named_block_result = self._translate_named_block_call(normalized)
        if named_block_result is not None:
            return named_block_result

        # Handle compound assignment (+=, -=, etc.)
        compound_match = re.match(r"(.+?)\s*(\+|-|\*|/)=\s*(.+);?", normalized)
        if compound_match:
            target = self.expr_translator.translate(compound_match.group(1).strip())
            op = compound_match.group(2)
            value = self.expr_translator.translate(compound_match.group(3).strip().rstrip(";"))
            return [f"{target} {op}= {value}"]

        # Assignment: `:=` must appear BEFORE the first `(` in the statement.
        # This distinguishes:
        #   - `#ca := COS(#alpha);`  → assignment (`:=` before first `(`)
        #   - `#timer(IN := #x, ...);` → FB call (first `(` before `:=`)
        assign_pos = normalized.find(":=")
        paren_pos = normalized.find("(")
        is_assignment = assign_pos != -1 and (paren_pos == -1 or assign_pos < paren_pos)
        if is_assignment:
            # Special case: RHS is a single named-block call that ALSO binds `=>`
            # outputs (e.g. `#ret := "Foo"(x := #a, out => #b)`). The expression
            # path can only return the value and silently drops the `=>` outputs,
            # so route it through the multi-statement call form instead.
            lhs, rhs = normalized.split(":=", 1)
            named_out = self._match_named_call_with_outputs(rhs)
            if named_out is not None:
                call_block_name, call_params = named_out
                target_expr = self.expr_translator.translate(lhs.strip())
                return self._translate_named_call_assignment(target_expr, call_block_name, call_params)
            # Use `normalized` (with `# var` collapsed to `#var`) so that the
            # expression translator's INSTANCE_VAR_PATTERN (#\w+) matches.
            return [self.stmt_translator.translate_assignment(normalized)]

        # FB call pattern: #name(...);
        if normalized.startswith("#") and "(" in normalized and ")" in normalized:
            return self.stmt_translator.translate_fb_call(normalized)

        # Other expression
        translated = self.expr_translator.translate(normalized.rstrip(";"))
        if translated:
            return [translated]

        return []


# Default instance
default_control_flow_translator = ControlFlowTranslator()


def translate_control_flow(scl_code: str) -> list[str]:
    """Translate SCL code with control flow to Python.

    Parameters
    ----------
    scl_code : str
        SCL code block.

    Returns
    -------
    list[str]
        Python statements.
    """
    return default_control_flow_translator.translate_block(scl_code)
