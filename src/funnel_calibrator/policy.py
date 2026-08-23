"""Failure-mode diagnosis and action recommendation.

A product missing its CPL target is not one problem but several, each with a
different remedy. Cheap leads that fail to convert on the phone indicate a
targeting or creative problem; leads that convert but fail at the post office
indicate an offer or price problem. Recommending the wrong remedy is worse
than recommending none.

This module maps observed evidence to a diagnosis, and a diagnosis to an
action, keeping that mapping explicit and inspectable.
"""

from __future__ import annotations
