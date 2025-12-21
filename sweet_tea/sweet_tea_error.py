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


class SweetTeaError(Exception):
    """
    Exception raised for errors in the sweet_tea factory system.

    This includes cases like missing keys, ambiguous matches, or
    other factory-related configuration issues.
    """

    def __init__(self, *args):
        """
        Initialize SweetTeaError.

        Args:
            *args: Variable arguments. If provided, the first argument is used as the error message.
        """
        if args:
            self.message = args[0]
        else:
            self.message = None

    def __str__(self) -> str:
        """Return string representation of the error."""
        if self.message is not None:
            return f"SweetTeaError: {self.message}"
        return "SweetTeaError has been raised"
