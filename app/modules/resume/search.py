from app.config import SEARCH_LIMIT
from app.errors import TrialError


def search_topup(candidates, plan, base, lo_steps, hi_steps, step):
    """Fewest newly opened lots, then older allocations in descending order.

    Lots already delivered stay in the tank and cost no new batch. Each draw is a
    whole number of new-scale steps; the total must land in [lo_steps, hi_steps]
    while dry and gel balances (seeded by the delivered base) stay non-negative.
    """
    dry0, low0, high0 = base
    capacities = [min(lot['remain_g'] // step, hi_steps) for lot in candidates]
    fresh = [0 if lot['delivered_g'] else 1 for lot in candidates]
    coefficients = []
    for lot in candidates:
        dry = step * (10_000 - lot['moisture_bp'])
        coefficients.append((dry, dry * (lot['gel_msag'] - plan['gel_low_sag']),
                             dry * (plan['gel_high_sag'] - lot['gel_msag'])))
    bounds = [(0, 0, 0, 0, 0)] * (len(candidates) + 1)
    for i in reversed(range(len(candidates))):
        capacity, dry, low, high, opened = bounds[i+1]
        d, lo, hi = coefficients[i]
        bounds[i] = (capacity + capacities[i], max(dry, d), max(low, lo), max(high, hi), opened + fresh[i])
    visited = 0

    def visit(i, new, steps, dry, low, high):
        nonlocal visited
        visited += 1
        if visited > SEARCH_LIMIT:
            raise TrialError('SEARCH_LIMIT')
        if i == len(candidates):
            return () if lo_steps <= steps <= hi_steps and dry >= 0 and low >= 0 and high >= 0 else None
        capacity, best_dry, best_low, best_high, opened = bounds[i]
        room = min(hi_steps - steps, capacity)
        if (new > opened or steps + capacity < lo_steps
                or dry + room * best_dry < 0 or low + room * best_low < 0 or high + room * best_high < 0):
            return None
        d, lo, hi = coefficients[i]
        top = min(capacities[i], hi_steps - steps) if new or not fresh[i] else 0
        for n in range(top, -1, -1):
            tail = visit(i+1, new - fresh[i] * (n > 0), steps + n, dry + n*d, low + n*lo, high + n*hi)
            if tail is not None:
                return (n, *tail)
        return None

    for opened in range(min(sum(fresh), hi_steps) + 1):
        found = visit(0, opened, 0, dry0, low0, high0)
        if found is not None:
            return list(found), visited
    return None, visited
