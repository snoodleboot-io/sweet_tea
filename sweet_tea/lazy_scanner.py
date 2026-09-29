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
Source scanner that finds registrable names without importing a module.
"""

import ast

from sweet_tea.sweet_tea_error import SweetTeaError


class LazyScanner:
    """
    Find the module-level names that eager registration would register.

    Eager registration keys off the *attribute name* a class is bound to, not the
    class's ``__name__`` — ``Mismatch = type("InnerName", (), {})`` registers as
    ``mismatch``. So this scans module-level *bindings* rather than ``class``
    statements, which is what lets a lazily filled registry use the same keys.

    Names are classified:

    - **definite** — an unconditional ``class`` statement. Certain to be a class.
    - **provisional** — a guarded ``class`` statement (inside ``if``/``try``), or an
      assignment whose right-hand side looks class-producing. May turn out not to be
      a class at all, so it is confirmed or discarded when the module is imported.

    What this cannot see — classes built by ``globals()[name] = ...``, ``setattr`` on
    the module, or any other runtime injection — is recovered by the registry's
    fallback sweep rather than guessed at here.
    """

    #: Callables whose result is conventionally a class. An assignment from one of
    #: these is registrable, the same way eager registration would find the class
    #: after the module ran.
    CLASS_FACTORIES = frozenset(
        {
            "type",
            "new_class",
            "namedtuple",
            "NamedTuple",
            "TypedDict",
            "create_model",
            "Enum",
            "IntEnum",
            "StrEnum",
            "Flag",
            "IntFlag",
            "make_dataclass",
        }
    )

    @classmethod
    def scan_file(cls, path: str) -> dict[str, bool]:
        """
        Scan one source file for registrable names.

        Args:
            path: Path to the ``.py`` file.

        Returns:
            Mapping of attribute name to True when the name is definite, False when
            provisional.

        Raises:
            SweetTeaError: When the file cannot be read or parsed. Eager filling fails
                on such a module too — via ImportError — so both paths reject it.
        """
        try:
            with open(path, encoding="utf-8") as handle:
                source = handle.read()
        except OSError as error:
            raise SweetTeaError(f"Cannot read {path}: {error}") from error

        return cls.scan_source(source, path)

    @classmethod
    def scan_source(cls, source: str, path: str = "<string>") -> dict[str, bool]:
        """
        Scan module source for registrable names.

        Args:
            source: Python source text.
            path: Origin of the source, used only for error messages.

        Returns:
            Mapping of attribute name to True when definite, False when provisional.

        Raises:
            SweetTeaError: When the source cannot be parsed.
        """
        try:
            tree = ast.parse(source)
        except SyntaxError as error:
            raise SweetTeaError(f"Cannot parse {path}: {error}") from error

        found: dict[str, bool] = {}
        # Names already known to be classes, so that `Alias = Existing` is recognised
        # as another binding of a class rather than an ordinary assignment.
        known: set[str] = set()

        cls._walk(tree.body, found, known, guarded=False)
        return found

    @classmethod
    def _walk(
        cls,
        body: list[ast.stmt],
        found: dict[str, bool],
        known: set[str],
        guarded: bool,
    ) -> None:
        """
        Collect bindings from a statement list, descending into conditional blocks.

        Args:
            body: Statements to inspect.
            found: Accumulator of name -> definite.
            known: Names already established as classes in this module.
            guarded: True when these statements sit inside an ``if``/``try``, which
                makes any binding they create provisional.
        """
        for node in body:
            if isinstance(node, ast.ClassDef):
                found[node.name] = not guarded
                known.add(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                cls._collect_assignment(node, found, known)
            elif isinstance(node, ast.Delete):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        found.pop(target.id, None)
                        known.discard(target.id)
            elif isinstance(node, ast.If):
                cls._walk(node.body, found, known, guarded=True)
                cls._walk(node.orelse, found, known, guarded=True)
            elif isinstance(node, ast.Try):
                cls._walk(node.body, found, known, guarded=True)
                for handler in node.handlers:
                    cls._walk(handler.body, found, known, guarded=True)
                cls._walk(node.orelse, found, known, guarded=True)
                cls._walk(node.finalbody, found, known, guarded=True)

    @classmethod
    def _collect_assignment(
        cls,
        node: ast.Assign | ast.AnnAssign,
        found: dict[str, bool],
        known: set[str],
    ) -> None:
        """
        Record an assignment when its right-hand side looks class-producing.

        Args:
            node: The assignment statement.
            found: Accumulator of name -> definite.
            known: Names already established as classes in this module.
        """
        if node.value is None or not cls._is_class_producing(node.value, known):
            return

        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                # Always provisional: only importing the module proves it is a class.
                found[target.id] = False
                known.add(target.id)

    @classmethod
    def _is_class_producing(cls, value: ast.expr, known: set[str]) -> bool:
        """
        Decide whether an expression plausibly evaluates to a class.

        Args:
            value: The right-hand side of an assignment.
            known: Names already established as classes in this module.

        Returns:
            True for a call to a known class factory, or an alias of a known class.
        """
        if isinstance(value, ast.Call):
            function = value.func
            if isinstance(function, ast.Name):
                return function.id in cls.CLASS_FACTORIES
            if isinstance(function, ast.Attribute):
                return function.attr in cls.CLASS_FACTORIES
            return False

        # `Alias = SomeClass` binds the same class under a second name, which eager
        # registration reports as two entries.
        return isinstance(value, ast.Name) and value.id in known
