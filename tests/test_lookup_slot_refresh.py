"""
Tests for SWE-43: every lookup key the registry memoises is one it refreshes.

``typed_entries`` memoises a slot per lookup type so repeated queries do not rescan
(SWE-34), and ``register`` refreshes the slots a new class belongs in (GH #6). The two
ends disagreed about what a lookup key may be: ``issubclass`` accepts a tuple of
classes, so a slot was built for one, and ``register``'s refresh skipped anything that
was not itself a class, so the slot was never updated again.
"""

from typing import Any, Protocol, runtime_checkable
from unittest import TestCase

from sweet_tea.registry import Registry


class Base:
    """Root of the fixture hierarchy."""


class Other:
    """A second, unrelated root, so a tuple lookup spans two branches."""


class Early(Base):
    """Registered before the lookup slot is built."""


class Later(Base):
    """Registered after it, which is what the refresh has to notice."""


class OtherLater(Other):
    """Registered after it, on the tuple's second branch."""


def reset_registry() -> None:
    """Clear the registry and every memoised lookup slot."""
    Registry._Registry__registry.clear()
    Registry._Registry__seen.clear()
    Registry._Registry__lookup.clear()
    Registry._Registry__lookup_keys.clear()
    Registry._Registry__unresolved.clear()


class LookupSlotCase(TestCase):
    """Shared scaffolding: an empty registry either side of each test."""

    def setUp(self):
        reset_registry()

    def tearDown(self):
        reset_registry()

    def keys_for(self, lookup_type: Any) -> list[str]:
        return sorted(entry.key for entry in Registry.typed_entries(lookup_type))


class TestATupleLookupStaysCurrent(LookupSlotCase):
    """A tuple is a legal second argument to issubclass, so it is a legal lookup."""

    def test_a_registration_after_the_lookup_shows_up(self):
        """['early'] came back forever; the slot was built once and never refreshed."""
        Registry.register(key="early", class_def=Early)
        self.assertEqual(self.keys_for((Base, Other)), ["early"])

        Registry.register(key="later", class_def=Later)

        self.assertEqual(self.keys_for((Base, Other)), ["early", "later"])

    def test_both_branches_of_the_tuple_are_refreshed(self):
        """A tuple spans several hierarchies; the refresh must honour all of them."""
        Registry.register(key="early", class_def=Early)
        self.keys_for((Base, Other))

        Registry.register(key="otherlater", class_def=OtherLater)

        self.assertEqual(self.keys_for((Base, Other)), ["early", "otherlater"])

    def test_a_class_in_neither_branch_is_not_added(self):
        """Refreshing more slots must not mean refreshing them wrongly."""
        Registry.register(key="early", class_def=Early)
        self.keys_for((Base, Other))

        Registry.register(key="unrelated", class_def=type("Unrelated", (), {}))

        self.assertEqual(self.keys_for((Base, Other)), ["early"])

    def test_the_single_type_slot_behaves_the_same(self):
        """The baseline the tuple case is measured against; this always worked."""
        Registry.register(key="early", class_def=Early)
        self.assertEqual(self.keys_for(Base), ["early"])

        Registry.register(key="later", class_def=Later)

        self.assertEqual(self.keys_for(Base), ["early", "later"])


class TestOtherLegalLookupKeys(LookupSlotCase):
    """Whatever issubclass accepts, the memo has to keep current."""

    def test_a_union_lookup_stays_current(self):
        """issubclass takes a union since 3.10, so typed_entries does too."""
        Registry.register(key="early", class_def=Early)
        self.assertEqual(self.keys_for(Base | Other), ["early"])

        Registry.register(key="otherlater", class_def=OtherLater)

        self.assertEqual(self.keys_for(Base | Other), ["early", "otherlater"])

    def test_a_runtime_checkable_protocol_lookup_stays_current(self):
        """A method-only Protocol answers issubclass, so it is a usable key."""

        @runtime_checkable
        class Speaks(Protocol):
            def speak(self) -> str: ...

        class EarlySpeaker:
            def speak(self) -> str:
                return "early"

        class LaterSpeaker:
            def speak(self) -> str:
                return "later"

        Registry.register(key="earlyspeaker", class_def=EarlySpeaker)
        self.assertEqual(self.keys_for(Speaks), ["earlyspeaker"])

        Registry.register(key="laterspeaker", class_def=LaterSpeaker)

        self.assertEqual(self.keys_for(Speaks), ["earlyspeaker", "laterspeaker"])

    def test_any_still_collects_everything(self):
        """The Any slot has always been refreshed unconditionally; keep it that way."""
        Registry.register(key="early", class_def=Early)
        self.keys_for(Any)

        Registry.register(key="unrelated", class_def=type("Unrelated", (), {}))

        self.assertEqual(self.keys_for(Any), ["early", "unrelated"])


class TestAnUnusableLookupKeyIsRefused(LookupSlotCase):
    """
    SWE-31 made typed_entries repeat issubclass's own TypeError rather than raise a
    bare KeyError later. Over an *empty* registry the comprehension never evaluates
    issubclass, so the argument was never tested and the honest error never arrived —
    the one case that fix could not see. It also matters now: register applies
    issubclass to every memoised key, so a key it cannot be applied to must not be
    memoised.
    """

    def test_a_plain_value_is_refused_over_an_empty_registry(self):
        """Returned [] and memoised the key; now it says what is wrong."""
        with self.assertRaises(TypeError):
            Registry.typed_entries(5)

    def test_a_plain_value_is_refused_over_a_filled_registry(self):
        """The case SWE-31 did cover, unchanged."""
        Registry.register(key="early", class_def=Early)

        with self.assertRaises(TypeError):
            Registry.typed_entries(5)

    def test_a_tuple_containing_a_non_class_is_refused(self):
        """A tuple is legal; a tuple of the wrong things is not."""
        with self.assertRaises(TypeError):
            Registry.typed_entries((Base, 5))

    def test_a_refused_key_is_not_memoised(self):
        """A key with no slot is the state that raised KeyError out of the library."""
        with self.assertRaises(TypeError):
            Registry.typed_entries(5)

        self.assertNotIn(5, Registry._Registry__lookup_keys)
        self.assertNotIn(5, Registry._Registry__lookup)

    def test_a_later_registration_is_unaffected_by_the_refusal(self):
        """
        The real cost of memoising an unusable key: register walks every memoised key
        and applies issubclass to it, so one bad key would break every registration
        that followed.
        """
        with self.assertRaises(TypeError):
            Registry.typed_entries(5)

        Registry.register(key="early", class_def=Early)

        self.assertEqual(self.keys_for(Base), ["early"])
