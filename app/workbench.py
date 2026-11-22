import json

from flask import Blueprint, abort, current_app, render_template, request

from .config import REVISION
from .errors import TrialError
from .input import load
from .modules.batches.service import preserve
from .modules.batches.storage import history, read
from .modules.certificate.service import issue
from .pipeline import process
from .stages import LABELS, PLAN_FIELDS, STAGES

station = Blueprint('station', __name__)


def materials(mode):
    if mode != 'custom':
        return load(mode)
    try:
        proposal = json.loads(request.form.get('proposal', '{}'))
    except ValueError:
        raise TrialError('BAD_PROPOSAL_JSON') from None
    try:
        delivered = json.loads(request.form.get('delivered', '') or '{}')
    except ValueError:
        raise TrialError('BAD_DELIVERED_JSON') from None
    material = {'assays': request.form.get('assays', ''),
                'plan': {key: request.form.get(key, '') for key in PLAN_FIELDS},
                'proposal': proposal}
    step = request.form.get('resume_step_g', '').strip()
    tolerance = request.form.get('resume_tolerance_g', '').strip()
    if step or tolerance or delivered:
        material['resume'] = {'delivered': delivered, 'step_g': step, 'tolerance_g': tolerance}
    return material


@station.route('/', methods=['GET', 'POST'])
@station.route('/trial/<stage>', methods=['GET', 'POST'])
def review(stage='stock'):
    if stage not in LABELS:
        abort(404)
    mode = request.values.get('sample', 'dirty')
    data, pack, error, record, entries, fresh = {}, None, None, None, [], False
    root = current_app.config['ARCHIVE']
    source = {}
    try:
        source = materials(mode)
        if stage in ('batches', 'certificate'):
            if stage == 'batches' and request.method == 'POST':
                record, fresh = preserve(root, source)
            entries = history(root)
            if stage == 'certificate' and (entries or request.args.get('batch')):
                pack = issue(read(root, request.args.get('batch') or entries[0]['batch_id']))
        else:
            data = process(source, stage)
    except TrialError as exc:
        error = exc.code
    form_plan = request.form if mode == 'custom' else source.get('plan', {})
    form_assays = request.form.get('assays', '') if mode == 'custom' else source.get('assays', '')
    form_proposal = request.form.get('proposal', '{}') if mode == 'custom' else json.dumps(source.get('proposal', {}))
    if mode == 'custom':
        form_resume = {'step_g': request.form.get('resume_step_g', ''), 'tolerance_g': request.form.get('resume_tolerance_g', '')}
        form_delivered = request.form.get('delivered', '{}')
    else:
        form_resume = source.get('resume', {})
        form_delivered = json.dumps(form_resume.get('delivered', {}))
    return render_template('station.html', stages=STAGES, labels=LABELS, fields=PLAN_FIELDS,
                           revision=REVISION, stage=stage, mode=mode, data=data, error=error,
                           form_plan=form_plan, form_assays=form_assays, form_proposal=form_proposal,
                           form_resume=form_resume, form_delivered=form_delivered,
                           record=record, fresh=fresh, entries=entries, pack=pack)
