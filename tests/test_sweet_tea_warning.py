"""
Tests for the SweetTeaWarning warning class.
"""

import warnings
from unittest import TestCase

from sweet_tea.sweet_tea_warning import SweetTeaWarning


class TestSweetTeaWarning(TestCase):
    """Test SweetTeaWarning functionality."""

    def test_warning_inheritance(self):
        """Test that SweetTeaWarning inherits from UserWarning."""
        # SweetTeaWarning should be a subclass of UserWarning
        self.assertTrue(issubclass(SweetTeaWarning, UserWarning))

    def test_warning_instance(self):
        """Test creating a SweetTeaWarning instance."""
        warning = SweetTeaWarning("Test warning message")
        self.assertIsInstance(warning, UserWarning)
        self.assertIsInstance(warning, SweetTeaWarning)

    def test_warning_with_warnings_module(self):
        """Test using SweetTeaWarning with the warnings module."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            # Issue a SweetTeaWarning
            warnings.warn("Test warning", SweetTeaWarning)

            # Check that it was captured
            self.assertEqual(len(w), 1)
            self.assertIsInstance(w[0].message, SweetTeaWarning)
            self.assertEqual(str(w[0].message), "Test warning")

    def test_warning_category_filtering(self):
        """Test that SweetTeaWarning can be filtered specifically."""
        # Test that SweetTeaWarning is a subclass of UserWarning
        self.assertTrue(issubclass(SweetTeaWarning, UserWarning))

        # Test filtering works by checking the category
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            # Issue both types of warnings
            warnings.warn("SweetTea warning", SweetTeaWarning)
            warnings.warn("Regular warning", UserWarning)

            # Should capture both
            self.assertEqual(len(w), 2)

            # Check that the first is SweetTeaWarning
            self.assertIsInstance(w[0].message, SweetTeaWarning)
            # Check that the second is UserWarning
            self.assertIsInstance(w[1].message, UserWarning)

    def test_warning_message_formatting(self):
        """Test SweetTeaWarning message formatting."""
        warning = SweetTeaWarning("Custom warning message")
        self.assertEqual(str(warning), "Custom warning message")

    def test_warning_empty_message(self):
        """Test SweetTeaWarning with empty message."""
        warning = SweetTeaWarning("")
        self.assertEqual(str(warning), "")

    def test_warning_none_message(self):
        """Test SweetTeaWarning with None message (should work like UserWarning)."""
        warning = SweetTeaWarning(None)
        # UserWarning handles None gracefully
        self.assertIsNotNone(str(warning))
