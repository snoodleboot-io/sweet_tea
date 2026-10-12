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
One registrable name as the source scanner saw it.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScannedName:
    """
    What a scan learned about one module-level binding.

    A plain frozen dataclass rather than a pydantic model, unlike its neighbours:
    this never leaves the process and is never validated against untrusted input —
    it is built once per binding per file while a tree is being scanned, which is
    the path lazy filling exists to keep cheap. :class:`ScannedName` is the
    scanner's own vocabulary; what the registry keeps is an
    :class:`~sweet_tea.entry.Entry`, and what a snapshot writes is a
    :class:`~sweet_tea.snapshot_entry.SnapshotEntry`.
    """

    #: True when an unconditional ``class`` statement bound the name, so it is
    #: certain to be a class. False when the binding is a guess — a guarded
    #: ``class`` statement, or an assignment that looks class-producing — which only
    #: importing the module can confirm.
    definite: bool

    #: Base names as the source spells them, normalised: an aliased import is
    #: reported under the name the class was defined with, a dotted reference under
    #: its last segment, and a generic base without its subscript. Empty when the
    #: source declares none, and empty rather than wrong when they cannot be read —
    #: a base computed at runtime leaves nothing to record.
    bases: tuple[str, ...] = ()
