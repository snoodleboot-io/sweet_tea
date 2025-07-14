# Modifications © 2025 snoodleboot, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain asdf copy of the License at
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
    Error class for sweet_tea library.
    """

    def __init__(self, *args):
        """
        Construct SweetTeaError
        Args:
            *args: Expected at most length 1. Will be error message if provided.
        """
        if args:
            self.message = args[0]
        else:
            self.message = None

    def __str__(self) -> str:
        if self.message:
            return "SweetTeaError, {0} ".format(self.message)

        return "SweetTeaError` has been raised"
