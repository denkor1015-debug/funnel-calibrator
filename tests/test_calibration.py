"""Unit tests for CPL recomputation.

The property that matters: worse observed rates must produce strictly lower
CPL bounds. A regression here would silently restore the open-loop behaviour
the server exists to correct.

STATUS: scaffold.
"""

from __future__ import annotations
