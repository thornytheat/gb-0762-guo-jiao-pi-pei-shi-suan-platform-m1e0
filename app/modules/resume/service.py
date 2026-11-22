from app.config import MAX_LOTS
from app.errors import TrialError
from app.modules.formula.metrics import measurements, weigh
from .search import search_topup


def quality_checks(plan, window, mass, dry, moment):
    low, high = window
    return {'mass': low <= mass <= high, 'dry': dry >= plan['dry_min_u'],
            'gel_low': bool(dry and moment >= dry * plan['gel_low_sag']),
            'gel_high': bool(dry and moment <= dry * plan['gel_high_sag'])}


def resume_batch(spec, plan, lots):
    delivered, step, tolerance = spec['delivered'], spec['step_g'], spec['tolerance_g']
    window = (plan['target_g'] - tolerance, plan['target_g'] + tolerance)
    known = {row['lot']: row for row in lots}
    findings = []
    for lot_id, grams in delivered.items():
        lot = known.get(lot_id)
        codes = []
        if lot is None:
            codes.append('LOT_NOT_ACCEPTED')
        else:
            if lot['status'] != 'ELIGIBLE':
                codes.append(lot['status'])
            if grams > lot['stock_g']:
                codes.append('OVER_STOCK')
        findings.append({'lot': lot_id, 'line': lot['line'] if lot else None, 'grams': grams, 'codes': codes})
    dry0, moment0 = weigh(lots, [delivered.get(lot['lot'], 0) for lot in lots])
    mass0 = sum(delivered.values())

    def build(decision, reason, topup, visited=0, capacity=0):
        actual = dict(delivered)
        for lot_id, grams in topup.items():
            actual[lot_id] = actual.get(lot_id, 0) + grams
        dry, moment = weigh(lots, [actual.get(lot['lot'], 0) for lot in lots])
        mass = sum(actual.values())
        codes = {row['lot']: row['codes'] for row in findings}
        rows = [{'lot': lot['lot'], 'line': lot['line'], 'delivered_g': delivered.get(lot['lot'], 0),
                 'topup_g': topup.get(lot['lot'], 0), 'actual_g': actual[lot['lot']],
                 'steps': topup.get(lot['lot'], 0) // step, 'end_g': lot['stock_g'] - actual[lot['lot']],
                 'codes': codes.get(lot['lot'], [])}
                for lot in lots if actual.get(lot['lot'], 0)]
        return {'decision': decision, 'reason': reason, 'delivered': delivered, 'topup': topup, 'actual': actual,
                'step_g': step, 'tolerance_g': tolerance, 'window_g': list(window),
                'new_lots': sum(1 for lot_id in topup if lot_id not in delivered),
                'delivered_g': mass0, 'topup_g': sum(topup.values()), 'mass_g': mass,
                **measurements(dry, moment), 'checks': quality_checks(plan, window, mass, dry, moment),
                'findings': findings, 'rows': rows, 'visited': visited, 'step_capacity_g': capacity}

    if any(row['codes'] for row in findings):
        return build('HOLD', 'DELIVERED_FINDINGS', {})
    if mass0 > window[1]:
        return build('HOLD', 'OVER_TOLERANCE', {})
    candidates = []
    for lot in lots:
        remain = lot['stock_g'] - delivered.get(lot['lot'], 0)
        if lot['status'] == 'ELIGIBLE' and remain >= step:
            candidates.append({**lot, 'remain_g': remain, 'delivered_g': delivered.get(lot['lot'], 0)})
    if len(candidates) > MAX_LOTS:
        raise TrialError('TOO_MANY_LOTS')
    capacity = sum(lot['remain_g'] // step * step for lot in candidates)
    lo_steps = max(0, -(-(window[0] - mass0) // step))
    hi_steps = (window[1] - mass0) // step
    if lo_steps > hi_steps or mass0 + capacity < window[0]:
        return build('HOLD', 'WINDOW_UNREACHABLE', {}, 0, capacity)
    base = (dry0 - plan['dry_min_u'], moment0 - plan['gel_low_sag'] * dry0,
            plan['gel_high_sag'] * dry0 - moment0)
    allocation, visited = search_topup(candidates, plan, base, lo_steps, hi_steps, step)
    if allocation is None:
        return build('HOLD', 'QUALITY_INFEASIBLE', {}, visited, capacity)
    topup = {lot['lot']: n * step for lot, n in zip(candidates, allocation) if n}
    return build('TOP_UP', None, topup, visited, capacity)
