# Modifications © 2025 snoodleboot, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Source analysis for patterns that lazy registration cannot serve.
"""

import ast

from sweet_tea.audit_finding import AuditFinding


class LazyAudit:
    """
    Find, without importing, the reasons a module needs eager registration.

    Lazy filling assumes a module can be left unimported until something asks for one
    of its classes. Three habits break that assumption:

    - **Reading the registry while importing.** A module body that calls
      ``Factory.create`` needs entries that lazy filling has not resolved yet, so the
      import fails outright rather than merely running late.
    - **Registering while importing.** A registration performed as an import side
      effect never happens if the module is never imported, so the key is missing
      until something forces a sweep.
    - **Creating classes at runtime.** ``globals()[name] = type(...)`` leaves nothing
      in the source to read, so the name cannot be registered from a scan.

    Detection is deliberately shallow: module-level statements, the branches of
    module-level ``if``/``try``, and one hop into functions the module body calls.
    Anything deeper is left to the registry's runtime warning, which reports the same
    problem from the other side.
    """

    #: Attribute names that read the registry. Matched only on receivers bound from
    #: sweet_tea, so an unrelated ``self.create(...)`` is not mistaken for one.
    READ_METHODS = frozenset(
        {"create", "entries", "typed_entries", "list_keys", "list_singletons", "pop"}
    )

    #: Attribute names that write to the registry. ``fill_registry`` is deliberately
    #: absent: calling it from a package's ``__init__`` is the documented way to
    #: populate the registry, so flagging it would mark every consumer hostile.
    WRITE_METHODS = frozenset({"register", "register_lazy"})

    @classmethod
    def audit_source(cls, source: str, module: str) -> list[AuditFinding]:
        """
        Analyse one module's source.

        Args:
            source: Python source text.
            module: Dotted module path, used in the findings.

        Returns:
            Findings, in line order. Empty when the module is safe to register lazily.
        """
        try:
            tree = ast.parse(source)
        except SyntaxError:
            # Unparsable source is the scanner's to report, not the audit's: the fill
            # skips such a module with a warning and a skipped() record (SWE-23), and
            # a finding here would only duplicate that.
            return []

        sweet_tea_names = cls._sweet_tea_names(tree)
        functions = {
            node.name: node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        findings: list[AuditFinding] = []
        cls._scan_statements(
            tree.body, module, sweet_tea_names, functions, findings, depth=0
        )
        return sorted(findings, key=lambda finding: (finding.line, finding.kind))

    @classmethod
    def audit_file(cls, path: str, module: str) -> list[AuditFinding]:
        """
        Analyse one module's source file.

        Args:
            path: Path to the ``.py`` file.
            module: Dotted module path, used in the findings.

        Returns:
            Findings, in line order. An unreadable file yields none; the scanner
            reports that failure instead.
        """
        try:
            with open(path, encoding="utf-8") as handle:
                source = handle.read()
        except OSError:
            return []
        return cls.audit_source(source, module)

    @classmethod
    def _sweet_tea_names(cls, tree: ast.Module) -> set[str]:
        """
        Collect the local names that refer to sweet_tea.

        Args:
            tree: Parsed module.

        Returns:
            Names bound by an import of sweet_tea, including any aliases.
        """
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".")[0] == "sweet_tea":
                    names.update(alias.asname or alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "sweet_tea":
                        names.add(alias.asname or alias.name.split(".")[0])
        return names

    @classmethod
    def _scan_statements(
        cls,
        body: list[ast.stmt],
        module: str,
        sweet_tea_names: set[str],
        functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
        findings: list[AuditFinding],
        depth: int,
    ) -> None:
        """
        Walk statements that run at import time.

        Args:
            body: Statements to inspect.
            module: Dotted module path.
            sweet_tea_names: Local names referring to sweet_tea.
            functions: Module-level functions, for the single hop.
            findings: Accumulator.
            depth: 0 while in the module body, 1 inside a function it calls.
        """
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # Definitions do not run; only a call to one does.
                continue
            if isinstance(node, ast.If):
                cls._scan_statements(
                    node.body, module, sweet_tea_names, functions, findings, depth
                )
                cls._scan_statements(
                    node.orelse, module, sweet_tea_names, functions, findings, depth
                )
                continue
            if isinstance(node, ast.Try):
                for block in (node.body, node.orelse, node.finalbody):
                    cls._scan_statements(
                        block, module, sweet_tea_names, functions, findings, depth
                    )
                for handler in node.handlers:
                    cls._scan_statements(
                        handler.body,
                        module,
                        sweet_tea_names,
                        functions,
                        findings,
                        depth,
                    )
                continue
            if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                # Loops are where classes get generated in bulk, so their bodies carry
                # as much weight as the module body itself.
                cls._scan_statements(
                    node.body, module, sweet_tea_names, functions, findings, depth
                )
                cls._scan_statements(
                    node.orelse, module, sweet_tea_names, functions, findings, depth
                )
                continue
            if isinstance(node, (ast.With, ast.AsyncWith)):
                cls._scan_statements(
                    node.body, module, sweet_tea_names, functions, findings, depth
                )
                continue

            cls._scan_expressions(
                node, module, sweet_tea_names, functions, findings, depth
            )

    @classmethod
    def _scan_expressions(
        cls,
        node: ast.stmt,
        module: str,
        sweet_tea_names: set[str],
        functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
        findings: list[AuditFinding],
        depth: int,
    ) -> None:
        """
        Inspect one executable statement and everything it evaluates.

        Args:
            node: The statement.
            module: Dotted module path.
            sweet_tea_names: Local names referring to sweet_tea.
            functions: Module-level functions, for the single hop.
            findings: Accumulator.
            depth: 0 in the module body, 1 inside a called function.
        """
        if isinstance(node, ast.Assign):
            cls._check_dynamic_binding(node, module, findings)

        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue

            if cls._is_module_setattr(inner):
                findings.append(
                    AuditFinding(
                        module=module,
                        line=inner.lineno,
                        kind="dynamic-class",
                        detail="setattr() on a module binds a name no scan can see",
                    )
                )

            receiver, method = cls._call_target(inner)
            if receiver in sweet_tea_names and method:
                if method in cls.WRITE_METHODS:
                    findings.append(
                        AuditFinding(
                            module=module,
                            line=inner.lineno,
                            kind="registration-at-import",
                            detail=(
                                f"{receiver}.{method}(...) runs while the module is "
                                f"imported, so it never runs if the module is not"
                            ),
                        )
                    )
                elif method in cls.READ_METHODS:
                    findings.append(
                        AuditFinding(
                            module=module,
                            line=inner.lineno,
                            kind="registry-read-at-import",
                            detail=(
                                f"{receiver}.{method}(...) needs a populated registry "
                                f"while this module is still importing"
                            ),
                        )
                    )

            # One hop: a module-level call into a function defined here.
            if depth == 0 and isinstance(inner.func, ast.Name):
                target = functions.get(inner.func.id)
                if target is not None:
                    cls._scan_statements(
                        target.body,
                        module,
                        sweet_tea_names,
                        functions,
                        findings,
                        depth=1,
                    )

    @classmethod
    def _check_dynamic_binding(
        cls, node: ast.Assign, module: str, findings: list[AuditFinding]
    ) -> None:
        """
        Report ``globals()[name] = ...``, which binds a name no scan can see.

        Args:
            node: The assignment.
            module: Dotted module path.
            findings: Accumulator.
        """
        for target in node.targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Call)
                and isinstance(target.value.func, ast.Name)
                and target.value.func.id == "globals"
            ):
                findings.append(
                    AuditFinding(
                        module=module,
                        line=node.lineno,
                        kind="dynamic-class",
                        detail="globals()[...] binds a name no scan can see",
                    )
                )

    @classmethod
    def _is_module_setattr(cls, call: ast.Call) -> bool:
        """
        Whether a call looks like ``setattr`` against a module.

        Args:
            call: The call node.

        Returns:
            True for a three-argument ``setattr`` whose target is a subscript of
            ``sys.modules`` or a plain name — the shapes used to inject a class.
        """
        if not (isinstance(call.func, ast.Name) and call.func.id == "setattr"):
            return False
        if not call.args:
            return False
        first = call.args[0]
        if isinstance(first, ast.Subscript):
            return True
        return isinstance(first, ast.Name)

    @classmethod
    def _call_target(cls, call: ast.Call) -> tuple[str, str]:
        """
        Split a call into the name it is made on and the method called.

        Handles subscripted factories, so ``AbstractFactory[Knot].create(...)``
        reports ``AbstractFactory`` and ``create``.

        Args:
            call: The call node.

        Returns:
            (receiver name, method name), either of which may be empty.
        """
        if not isinstance(call.func, ast.Attribute):
            return "", ""

        value = call.func.value
        if isinstance(value, ast.Subscript):
            value = value.value
        if isinstance(value, ast.Attribute):
            value = value.value  # type: ignore[assignment]

        if isinstance(value, ast.Name):
            return value.id, call.func.attr
        return "", call.func.attr
