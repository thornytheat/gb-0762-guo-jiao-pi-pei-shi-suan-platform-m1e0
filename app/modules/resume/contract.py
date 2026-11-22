from app.config import MAX_STEPS
from app.errors import TrialError
from app.modules.assay.units import scaled

FIELDS = ('delivered', 'step_g', 'tolerance_g')


def normalize_resume(spec, plan):
    if not isinstance(spec, dict) or set(spec) != set(FIELDS):
        raise TrialError('RESUME_FIELDS_REQUIRED')
    delivered = spec['delivered']
    if not isinstance(delivered, dict) or any(type(lot) is not str or type(grams) is not int
                                              or not 0 <= grams <= 10**9 for lot, grams in delivered.items()):
        raise TrialError('BAD_DELIVERED')
    try:
        value = {}
        for field in FIELDS[1:]:
            raw = spec[field]
            if not isinstance(raw, str) and type(raw) is not int:
                raise ValueError
            value[field] = scaled(str(raw), 1, 10**9)
    except (TypeError, ValueError):
        raise TrialError('BAD_RESUME_VALUE') from None
    step, tolerance = value['step_g'], value['tolerance_g']
    if not step or (plan['target_g'] + tolerance) // step > MAX_STEPS:
        raise TrialError('BAD_RESUME_STEP')
    if tolerance > plan['target_g']:
        raise TrialError('BAD_RESUME_RANGE')
    return {'delivered': {lot: grams for lot, grams in delivered.items() if grams},
            'step_g': step, 'tolerance_g': tolerance}
