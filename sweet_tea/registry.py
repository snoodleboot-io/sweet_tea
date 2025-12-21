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
import importlib
import inspect
import logging
import os
import pkgutil
import threading
import traceback
import warnings
from pathlib import Path
from typing import Any

from sweet_tea.entry import Entry
from sweet_tea.sweet_tea_error import SweetTeaError
from sweet_tea.sweet_tea_warning import SweetTeaWarning


class Registry:
    """
    Global registry for class definitions that can be instantiated via factories.

    This registry automatically discovers and registers classes from packages,
    supporting optional dependencies that may not be installed. Classes with
    missing dependencies are skipped with a warning rather than failing registration.

    The registry supports typed lookups for abstract factories, allowing filtering
    by inheritance hierarchy.

    Thread-safe: All registry operations are synchronized to prevent race conditions
    in multi-threaded environments.
    """

    # Threading lock for synchronizing registry operations
    __lock = threading.RLock()

    # This is the registry of packages
    __registry: list[Entry] = []

    __lookup: dict[Any, list[Entry]] = {}

    __lookup_keys: list[Any] = []

    # Logger instance using the global settings
    __logger = logging.getLogger()

    @classmethod
    def entries(cls) -> list[Entry]:
        """Get all registered entries."""
        with cls.__lock:
            return cls.__registry.copy()

    @classmethod
    def typed_entries(cls, lookup_type: Any = Any) -> list[Entry]:
        """
        Get entries that are subclasses of the specified type.

        Args:
            lookup_type: The base class to filter by. Defaults to Any.

        Returns:
            List of entries where the class_def is a subclass of lookup_type.
        """
        with cls.__lock:
            if lookup_type not in cls.__lookup_keys:
                cls.__lookup_keys.append(lookup_type)
                if lookup_type is Any:
                    # Any matches everything - return all entries without filtering
                    cls.__lookup[lookup_type] = cls.__registry.copy()
                else:
                    cls.__lookup[lookup_type] = [
                        filtered_type
                        for filtered_type in cls.__registry
                        if issubclass(filtered_type.class_def, lookup_type)
                    ]
            return cls.__lookup[lookup_type].copy()

    @classmethod
    def register(
        cls, key: str, class_def: type, library: str = "", label: str = ""
    ) -> None:
        """
        Register a class with the registry.

        Args:
            key: Name used to reference the class for instantiation.
            class_def: The class type to register.
            library: Name of the library the class belongs to.
            label: Optional label for categorizing classes (e.g., for different environments).
        """
        new_entry = Entry(
            key=key.lower(),
            class_def=class_def,
            library=library.lower(),
            label=label.lower(),
        )

        with cls.__lock:
            # Add entry if it is not currently present. Prevents duplicate entry.
            if new_entry not in cls.__registry:
                cls.__registry.append(new_entry)

            if class_def in cls.__lookup:
                cls.__lookup[class_def].append(new_entry)

    @classmethod
    def fill_registry(
        cls,
        path: str | None = None,
        module: str | None = None,
        library: str = "",
        label: str = "",
    ) -> None:
        """
        Recursively scan and register classes from packages starting from the given path.

        This method automatically discovers all classes in the package hierarchy,
        supporting optional dependencies by gracefully skipping modules that fail
        to import due to missing packages.

        Args:
            path: Package path where modules are located. If None, uses the caller's module path.
            module: Name of the root module. If None, inferred from path.
            library: Name of the library for categorization.
            label: Optional label for categorizing classes.
        """
        with cls.__lock:
            # Determine the path to scan
            if path is None:
                _module = inspect.getmodule(inspect.stack()[1][0])
                if _module is None or _module.__file__ is None:
                    raise SweetTeaError("Cannot determine module path automatically")
                path = str(Path(_module.__file__).parent)

            # Ensure path is a string
            path_str = str(path)

            # Make sure the root module is correctly specified
            if module is None:
                module = os.path.basename(path_str)

            if not library:
                library = module

            # Location of package
            pkg_dir = path_str

            # Loop over the modules. If it is a package, the make recursive call, otherwise for each non-package
            # module imports the module and registers it.
            for _, name, is_a_package in pkgutil.iter_modules([pkg_dir]):
                pkg_name = f"{module}.{name}"
                if not is_a_package:
                    cls.__add_entry_to_registry(
                        label=label, library=library, name_of_package=pkg_name
                    )
                else:
                    # Make recursive call to the
                    cls.fill_registry(
                        path=os.path.join(pkg_dir, name),
                        module=pkg_name,
                        library=library,
                        label=label,
                    )

    @classmethod
    def __add_entry_to_registry(
        cls, label: str, library: str, name_of_package: str
    ) -> None:
        """
        Import a module and register all classes defined in it.

        Handles optional dependencies by issuing warnings for ImportError/ModuleNotFoundError
        and continuing, while raising SweetTeaError for other exceptions.

        Args:
            label: Optional label for categorizing classes.
            library: Name of the library the classes belong to.
            name_of_package: Full module name to import and scan.

        Raises:
            SweetTeaError: For non-import related errors during module processing.
        """
        try:
            # exec("import " + name_of_package)
            module = importlib.import_module(name_of_package)

            classes = []
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if obj.__module__ == name_of_package:
                    classes.append((name, obj))

            for class_name, class_def in classes:
                Registry.register(
                    key=class_name.lower(),
                    class_def=class_def,
                    library=library,
                    label=label,
                )

        except (ImportError, ModuleNotFoundError):
            # Optional dependency not installed - issue warning and skip this module
            warnings.warn(
                f"Skipping module {name_of_package} due to missing optional dependency",
                SweetTeaWarning,
                stacklevel=2,
            )
            # Continue without registering this module
        except Exception:
            # Other errors (e.g., syntax errors, runtime errors) should still fail
            error_message = traceback.format_exc()
            cls.__logger.error(
                f"Error processing module {name_of_package}: {error_message}"
            )
            raise SweetTeaError(error_message)
