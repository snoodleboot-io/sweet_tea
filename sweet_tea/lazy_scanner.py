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

from sweet_tea.scanned_name import ScannedName
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

    Each name also carries the **base names** the source declares for it, which is
    what lets :meth:`~sweet_tea.registry.Registry.typed_candidates` answer a type
    question about a tree nothing has imported (SWE-46). They are names, not classes,
    so they are a source-level approximation; see :meth:`_base_name_of` for exactly
    what is normalised and what is given up on.
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

    #: Callables whose second positional argument is a tuple of base classes, the
    #: way ``class`` statements spell theirs. Only these two have it in that shape:
    #: ``namedtuple`` and friends take fields there, so reading an argument out of
    #: them would record a field name as a base.
    BASE_BEARING_FACTORIES = frozenset({"type", "new_class"})

    @classmethod
    def scan_file(cls, path: str) -> dict[str, bool]:
        """
        Scan one source file for registrable names.

        Args:
            path: Path to the ``.py`` file.

        Returns:
            Mapping of attribute name to True when the name is definite, False when
            provisional. Call :meth:`scan_file_detailed` for the declared base names
            as well.

        Raises:
            SweetTeaError: When the file cannot be read, with the ``OSError`` as the
                cause, or cannot be parsed, with the ``SyntaxError`` as the cause.
        """
        return {
            name: scanned.definite
            for name, scanned in cls.scan_file_detailed(path).items()
        }

    @classmethod
    def scan_file_detailed(cls, path: str) -> dict[str, ScannedName]:
        """
        Scan one source file, reporting each name's declared bases too.

        Read as bytes rather than text, and handed to :func:`ast.parse` that way, so
        that a module declaring a non-UTF-8 encoding is scanned rather than rejected.
        ``ast.parse`` honours a PEP 263 coding cookie in bytes, and an import honours
        it too, so reading as UTF-8 text would have failed on a module the eager path
        registers perfectly well.

        Args:
            path: Path to the ``.py`` file.

        Returns:
            Mapping of attribute name to what the scan learned about it.

        Raises:
            SweetTeaError: When the file cannot be read, with the ``OSError`` as the
                cause, or cannot be parsed, with the ``SyntaxError`` as the cause. The
                caller tells the two apart by that cause, because they do not mean the
                same thing: unparsable source cannot be imported either, while an
                unreadable one may still import from cached bytecode.
        """
        try:
            with open(path, "rb") as handle:
                source = handle.read()
        except OSError as error:
            raise SweetTeaError(f"Cannot read {path}: {error}") from error

        return cls.scan_source_detailed(source, path)

    @classmethod
    def scan_source(
        cls, source: str | bytes, path: str = "<string>"
    ) -> dict[str, bool]:
        """
        Scan module source for registrable names.

        Args:
            source: Python source, as text or as the raw bytes of a file. Bytes keep
                a PEP 263 coding declaration meaningful.
            path: Origin of the source, used only for error messages.

        Returns:
            Mapping of attribute name to True when definite, False when provisional.
            Call :meth:`scan_source_detailed` for the declared base names as well.

        Raises:
            SweetTeaError: When the source cannot be parsed.
        """
        return {
            name: scanned.definite
            for name, scanned in cls.scan_source_detailed(source, path).items()
        }

    @classmethod
    def scan_source_detailed(
        cls, source: str | bytes, path: str = "<string>"
    ) -> dict[str, ScannedName]:
        """
        Scan module source, reporting each name's declared bases too.

        Args:
            source: Python source, as text or as the raw bytes of a file. Bytes keep
                a PEP 263 coding declaration meaningful.
            path: Origin of the source, used only for error messages.

        Returns:
            Mapping of attribute name to what the scan learned about it.

        Raises:
            SweetTeaError: When the source cannot be parsed.
        """
        try:
            tree = ast.parse(source)
        except SyntaxError as error:
            raise SweetTeaError(f"Cannot parse {path}: {error}") from error

        found: dict[str, ScannedName] = {}
        # Names already known to be classes, so that `Alias = Existing` is recognised
        # as another binding of a class rather than an ordinary assignment.
        known: set[str] = set()

        # Collected over the whole tree in one pass before any class is read, rather
        # than as the walk reaches each import. A module is free to import below the
        # class that uses the name -- inside `if TYPE_CHECKING:`, at the foot of the
        # file, in a function -- and a walk-order alias map would miss exactly those.
        aliases = cls._collect_aliases(tree)

        cls._walk(tree.body, found, known, aliases, guarded=False)
        return found

    @classmethod
    def _collect_aliases(cls, tree: ast.Module) -> dict[str, str]:
        """
        Map each locally renamed import back to the name it was defined under.

        ``from .base import ObjectStore as Store`` makes ``Store`` the only spelling
        the source shows, while the class is still ``ObjectStore`` and that is what
        ``lookup_type.__name__`` will say. Without this the two never match and a
        true subclass is missed.

        Args:
            tree: The parsed module.

        Returns:
            Local name -> original name, for every import that renamed something.
        """
        aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for imported in node.names:
                    # `import a.b as m` renames a module, not a class, and a class
                    # reached through it is read from the attribute instead.
                    if imported.asname and "." not in imported.name:
                        aliases[imported.asname] = imported.name
        return aliases

    @classmethod
    def _walk(
        cls,
        body: list[ast.stmt],
        found: dict[str, ScannedName],
        known: set[str],
        aliases: dict[str, str],
        guarded: bool,
    ) -> None:
        """
        Collect bindings from a statement list, descending into conditional blocks.

        Args:
            body: Statements to inspect.
            found: Accumulator of name -> what was learned.
            known: Names already established as classes in this module.
            aliases: Local name -> original name, from :meth:`_collect_aliases`.
            guarded: True when these statements sit inside an ``if``/``try``, which
                makes any binding they create provisional.
        """
        for node in body:
            if isinstance(node, ast.ClassDef):
                found[node.name] = ScannedName(
                    definite=not guarded,
                    bases=cls._base_names(node.bases, aliases),
                )
                known.add(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                cls._collect_assignment(node, found, known, aliases)
            elif isinstance(node, ast.Delete):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        found.pop(target.id, None)
                        known.discard(target.id)
            elif isinstance(node, ast.If):
                cls._walk(node.body, found, known, aliases, guarded=True)
                cls._walk(node.orelse, found, known, aliases, guarded=True)
            elif isinstance(node, ast.Try):
                cls._walk(node.body, found, known, aliases, guarded=True)
                for handler in node.handlers:
                    cls._walk(handler.body, found, known, aliases, guarded=True)
                cls._walk(node.orelse, found, known, aliases, guarded=True)
                cls._walk(node.finalbody, found, known, aliases, guarded=True)

    @classmethod
    def _collect_assignment(
        cls,
        node: ast.Assign | ast.AnnAssign,
        found: dict[str, ScannedName],
        known: set[str],
        aliases: dict[str, str],
    ) -> None:
        """
        Record an assignment when its right-hand side looks class-producing.

        Args:
            node: The assignment statement.
            found: Accumulator of name -> what was learned.
            known: Names already established as classes in this module.
            aliases: Local name -> original name, from :meth:`_collect_aliases`.
        """
        if node.value is None or not cls._is_class_producing(node.value, known):
            return

        bases = cls._assigned_bases(node.value, aliases)
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                # Always provisional: only importing the module proves it is a class.
                found[target.id] = ScannedName(definite=False, bases=bases)
                known.add(target.id)

    @classmethod
    def _assigned_bases(
        cls, value: ast.expr, aliases: dict[str, str]
    ) -> tuple[str, ...]:
        """
        The base names an assignment's right-hand side declares, where it shows any.

        Two shapes carry them. ``type("Name", (Base,), {})`` spells its bases the way
        a ``class`` statement does, in a tuple it is worth reading. ``Alias = Known``
        binds a class that already has its own bases recorded, so the alias reports
        ``Known`` itself: reachability through the aliased name is the same question,
        and asking it that way needs no copy that could go stale.

        Args:
            value: The right-hand side of an assignment.
            aliases: Local name -> original name, from :meth:`_collect_aliases`.

        Returns:
            Declared base names, empty when the source shows none to read.
        """
        if isinstance(value, ast.Name):
            return (cls._resolve_alias(value.id, aliases),)

        if isinstance(value, ast.Call):
            function = value.func
            name_called = (
                function.id
                if isinstance(function, ast.Name)
                else function.attr if isinstance(function, ast.Attribute) else ""
            )

            candidates: list[ast.expr] = []
            if name_called in cls.BASE_BEARING_FACTORIES and len(value.args) >= 2:
                candidates.append(value.args[1])
            # make_dataclass takes its bases by keyword, and a caller may pass
            # type's the same way.
            candidates.extend(
                keyword.value for keyword in value.keywords if keyword.arg == "bases"
            )

            for candidate in candidates:
                if isinstance(candidate, (ast.Tuple, ast.List)):
                    return cls._base_names(list(candidate.elts), aliases)

        # Reached by a call that shows no readable base tuple, and by any other
        # expression: both mean the source has nothing to record, which is reported
        # as nothing rather than as a guess.
        return ()

    @classmethod
    def _base_names(
        cls, bases: list[ast.expr], aliases: dict[str, str]
    ) -> tuple[str, ...]:
        """
        Read a list of base expressions down to plain names, dropping what it cannot.

        Args:
            bases: Base expressions, as a ``class`` statement or a ``type()`` call
                spells them.
            aliases: Local name -> original name, from :meth:`_collect_aliases`.

        Returns:
            The names read, in source order, with duplicates and unreadable bases
            left out.
        """
        names: list[str] = []
        for base in bases:
            name = cls._base_name_of(base, aliases)
            if name is not None and name not in names:
                names.append(name)
        return tuple(names)

    @classmethod
    def _base_name_of(cls, base: ast.expr, aliases: dict[str, str]) -> str | None:
        """
        The name a single base expression refers to, as far as source can say.

        Normalised three ways, each of which would otherwise be a name that never
        matches a real class:

        - ``Store`` where the import renamed it becomes ``ObjectStore``, the name the
          class is defined under and the one ``__name__`` reports.
        - ``stores.base.ObjectStore`` becomes ``ObjectStore``: the last segment is the
          class, the rest is where it lives.
        - ``Base[int]`` becomes ``Base``, since a generic's subscript is not part of
          the name.

        What is given up on is a base no name describes — ``make_base()``,
        ``bases[0]``, anything computed. Nothing is recorded for it, which is honest:
        a guessed name would be worse than a missing one, because the registry treats
        a recorded name as evidence.

        Args:
            base: One base expression.
            aliases: Local name -> original name, from :meth:`_collect_aliases`.

        Returns:
            The base's name, or None when the expression does not name one.
        """
        # A generic base wraps the name it is parameterising; unwrap repeatedly so
        # Base[int][str] and other nestings reduce to Base as well.
        while isinstance(base, ast.Subscript):
            base = base.value

        if isinstance(base, ast.Name):
            return cls._resolve_alias(base.id, aliases)
        if isinstance(base, ast.Attribute):
            # Deliberately not alias-resolved: the attribute is read off whatever the
            # dotted path arrives at, so the local spelling of the path says nothing
            # about the class's own name.
            return base.attr
        return None

    @staticmethod
    def _resolve_alias(name: str, aliases: dict[str, str]) -> str:
        """
        Turn a locally renamed import back into the name it was defined under.

        Args:
            name: The name as the source spells it.
            aliases: Local name -> original name, from :meth:`_collect_aliases`.

        Returns:
            The original name when this one was renamed on import, else the name
            unchanged.
        """
        return aliases.get(name, name)

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
