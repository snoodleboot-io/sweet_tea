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
Registry entry model for storing class registration information.
"""

from typing import Callable

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

#: Set by :mod:`sweet_tea.registry` at import time. Takes an entry's module and
#: attribute and returns the class, importing the module if needed. It lives here as a
#: hook because ``registry`` imports ``entry``, so ``entry`` cannot import it back.
_resolver: Callable[[str, str], type] | None = None


def set_resolver(resolver: Callable[[str, str], type]) -> None:
    """
    Install the function that turns a lazy entry's coordinates into a class.

    Args:
        resolver: Callable taking (module, attribute) and returning the class.
    """
    global _resolver
    _resolver = resolver


class Entry(BaseModel):
    """
    A registry entry containing information about a registered class.

    Each entry represents a class that has been registered with the factory system,
    including metadata for filtering and instantiation.

    ``model_dump()`` names the class ``class_def`` — the name an entry is constructed
    with — and reports it as stored, so dumping a lazy entry yields None rather than
    importing. A resolved entry dumps a live class, which no JSON encoder accepts, so
    :class:`~sweet_tea.registry_snapshot.RegistrySnapshot` stays the serialisation
    path for anything leaving the process.
    """

    key: str = Field(
        description="Lowercase key used to reference this class for instantiation",
        examples=["myclass", "databaseconnection"],
    )

    class_object: type | None = Field(
        default=None,
        alias="class_def",
        description=(
            "The class as stored. None while the entry is registered lazily and its "
            "module has not been imported; read :attr:`class_def` to resolve it. "
            "Serialises under its alias, so a dump reports it as ``class_def``."
        ),
    )

    library: str = Field(
        default="",
        description="Name of the library or module group this class belongs to",
        examples=["mylib", "database"],
    )

    label: str = Field(
        default="",
        description="Optional label for categorizing classes (e.g., by environment or feature set)",
        examples=["production", "testing", "v2"],
    )

    module: str = Field(
        default="",
        description="Dotted module path holding the class, set only for lazy entries",
        examples=["mypkg.services.database"],
    )

    attribute: str = Field(
        default="",
        description="Module attribute the class is bound to, set only for lazy entries",
        examples=["DatabaseConnection"],
    )

    # populate_by_name lets construction keep saying ``class_def=...`` after the field
    # was renamed to free that name for the resolving property below (SWE-13).
    # serialize_by_alias finishes that job in the other direction: without it
    # ``model_dump()`` emitted ``class_object``, publishing the storage name this
    # model exists to hide and forcing every caller to pass ``by_alias=True`` to get
    # the name they constructed with. Serialisation stays a read of the stored field,
    # never of the property, so dumping a lazy entry yields ``class_def: None`` and
    # imports nothing -- a dump reports what the entry holds, not what it could
    # resolve to. ``model_dump(by_alias=False)`` remains the way to ask for the
    # storage name on purpose.
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    #: Where a resolved class is cached when this entry is still lazy. Deliberately a
    #: private attribute rather than ``class_object``: entries() hands out the
    #: registry's own Entry objects (the copy is of the list), so writing the public
    #: field from a reader flipped ``is_lazy`` to False and changed ``identity`` on a
    #: live entry -- which made it survive resolution's drop and slip past the dedupe
    #: index, duplicating entries and breaking lookups (SWE-37). Nothing the registry
    #: reasons about touches this, so caching here cannot disturb it. Private attrs
    #: are excluded from model_dump, so the serialised shape is unchanged.
    _resolved: type | None = PrivateAttr(default=None)

    @property
    def class_def(self) -> type | None:
        """
        The registered class, imported on first read if the entry is lazy.

        Reading this is how a lazily registered entry becomes a real one, so existing
        code that introspects the registry keeps seeing a class rather than None:

            matches = [entry.class_def for entry in Registry.entries() if ...]

        Only this entry's own module is imported, so a filtered read resolves only what
        it touched. Use :attr:`is_lazy` to check the state without importing anything.

        Reading this does **not** make the entry look resolved. ``entries()`` returns a
        copy of the registry's list, not of its entries, so this object may well be the
        registry's own -- and a reader must not change what the registry reasons about.
        The class is cached privately instead (see :attr:`_resolved`); the registry
        becomes the resolved entry's author when it reconciles the module.

        Returns:
            The class, or None for an entry that is neither resolved nor resolvable.

        Raises:
            SweetTeaError: When importing the module fails. Reading an attribute can
                therefore raise, which is the cost of keeping the old contract.
        """
        if self.class_object is not None:
            return self.class_object
        if self._resolved is not None:
            return self._resolved
        if not self.module or not self.attribute or _resolver is None:
            return None

        resolved = _resolver(self.module, self.attribute)
        self._resolved = resolved
        return resolved

    provisional: bool = Field(
        default=False,
        description=(
            "Whether this lazy entry came from reading source rather than from an "
            "explicit register_lazy call, which decides whether discovery's rules "
            "override it when its module is imported"
        ),
    )

    @property
    def is_lazy(self) -> bool:
        """
        Whether this entry still needs its module imported.

        Deliberately reads the stored field rather than :attr:`class_def`, so asking
        the question does not answer it by importing -- and so that a reader having
        resolved this entry's class does not make it look registered (SWE-37).
        """
        return self.class_object is None

    @property
    def identity(self) -> tuple[str, object, str, str]:
        """
        The four values that decide whether two registrations are duplicates.

        Mirrors what ``Entry.__eq__`` compares for eager entries. A lazy entry has no
        class object yet, so it identifies its target by ``module:attribute`` instead
        — which also means a lazy and an eager registration of one class do not
        collapse into a single entry (see SWE-10).
        """
        # Reads the stored field, never the resolving property: computing identity
        # happens during registration, and importing the tree while filling it is
        # exactly what lazy filling exists to avoid.
        target: object = (
            self.class_object
            if self.class_object is not None
            else f"{self.module}:{self.attribute}"
        )
        return (self.key, target, self.library, self.label)
