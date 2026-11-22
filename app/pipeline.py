from .errors import TrialError
from .modules.assay.service import receive
from .modules.dry.service import convert
from .modules.formula.contract import normalize
from .modules.formula.service import inspect
from .modules.blend.service import select
from .modules.resume.contract import normalize_resume
from .modules.resume.service import resume_batch
from .modules.stock.balance import reconcile, reconcile_actual


def process(material, stage='archive'):
    if len(material['assays']) > 250_000:
        raise TrialError('ASSAYS_TOO_LARGE', 413)
    assays = receive(material['assays'])
    result = {'assay': assays}
    if stage == 'assay':
        return result
    plan = normalize(material.get('plan'))
    result['dry'] = convert(assays['lots'], plan['as_of'])
    lots = result['dry']['lots']
    result['plan'] = plan
    if stage == 'dry':
        return result
    if stage in ('formula', 'archive'):
        result['formula'] = inspect(plan, lots, material.get('proposal', {}))
    if stage == 'formula':
        return result
    result['blend'] = select(plan, lots)
    if stage == 'blend':
        return result
    spec = material.get('resume')
    if spec is not None:
        result['resume'] = resume_batch(normalize_resume(spec, plan), plan, lots)
    elif stage == 'resume':
        result['resume'] = {'decision': 'NOT_REQUESTED'}
    if stage == 'resume':
        return result
    if spec is not None:
        result['stock'] = reconcile_actual(plan, lots, result['resume'])
    else:
        result['stock'] = reconcile(plan, lots, result['blend'])
    return result
