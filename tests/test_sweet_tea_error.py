"""
Tests for the SweetTeaError exception class.
"""

from unittest import TestCase

from sweet_tea.sweet_tea_error import SweetTeaError


class TestSweetTeaError(TestCase):
    """Test SweetTeaError exception functionality."""

    def test_error_creation_with_message(self):
        """Test creating SweetTeaError with a message."""
        error = SweetTeaError("Test error message")
        self.assertEqual(error.message, "Test error message")
        self.assertEqual(str(error), "SweetTeaError: Test error message")

    def test_error_creation_without_message(self):
        """Test creating SweetTeaError without a message."""
        error = SweetTeaError()
        self.assertIsNone(error.message)
        self.assertEqual(str(error), "SweetTeaError has been raised")

    def test_error_creation_with_multiple_args(self):
        """Test creating SweetTeaError with multiple arguments."""
        error = SweetTeaError("First message", "Second message")
        self.assertEqual(error.message, "First message")

    def test_error_inheritance(self):
        """Test that SweetTeaError inherits from Exception."""
        error = SweetTeaError("test")
        self.assertIsInstance(error, Exception)

    def test_error_as_context_manager(self):
        """Test using SweetTeaError in exception handling."""
        with self.assertRaises(SweetTeaError) as cm:
            raise SweetTeaError("Context manager test")

        self.assertEqual(str(cm.exception), "SweetTeaError: Context manager test")

    def test_error_message_persistence(self):
        """Test that error message is properly stored and retrieved."""
        test_message = "This is a test error message"
        error = SweetTeaError(test_message)

        # Check that message is stored
        self.assertEqual(error.message, test_message)

        # Check that str() uses the message
        self.assertEqual(str(error), f"SweetTeaError: {test_message}")

    def test_error_empty_string_message(self):
        """Test SweetTeaError with empty string message."""
        error = SweetTeaError("")
        self.assertEqual(error.message, "")
        self.assertEqual(str(error), "SweetTeaError: ")
