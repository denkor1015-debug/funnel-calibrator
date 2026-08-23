"""Unit-economics recomputation.

Given observed funnel rates for a product, recompute the CPL bounds that
follow from them:

    returns_cost = ((1 - buyout) / buyout) * return_fee
    contribution = price + upsell - cogs - returns_cost - call_centre_fee
    stop_cpl     = contribution * (approval * buyout) / usd_uah
    goal_cpl     = stop_cpl * goal_ratio

Stop CPL is the cost per lead at which profit reaches zero; Goal CPL is the
target the campaign should be optimised toward.
"""

from __future__ import annotations
