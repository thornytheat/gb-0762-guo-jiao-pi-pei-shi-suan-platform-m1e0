from itertools import product

import pytest

from app.errors import TrialError
from app.input import load
from app.modules.resume.contract import normalize_resume
from app.modules.resume.search import search_topup
from app.pipeline import process


@pytest.fixture
def swapped():
    return load('resume')


def resume(material):
    return process(material, 'resume')['resume']


def test_topup_is_weighable_on_new_scale(swapped):
    r = resume(swapped)
    assert (r['decision'], r['reason']) == ('TOP_UP', None)
    assert r['topup'] == {'PJ-21': 2400, 'PJ-22': 800}
    assert all(grams % r['step_g'] == 0 for grams in r['topup'].values())
    assert r['actual'] == {'PJ-21': 3900, 'PJ-22': 2300}
    assert (r['mass_g'], r['dry_g'], r['gel_sag'], r['new_lots']) == (6200, '5580.0000', '153.710', 0)
    assert r['window_g'] == [5700, 6300] and all(r['checks'].values())


def test_exact_target_unreachable_holds_for_review(swapped):
    swapped['resume']['tolerance_g'] = 0
    r = resume(swapped)
    assert (r['decision'], r['reason'], r['topup']) == ('HOLD', 'WINDOW_UNREACHABLE', {})


def test_overfilled_tank_cannot_be_saved(swapped):
    swapped['resume']['delivered'] = {'PJ-21': 1500, 'PJ-22': 5000}
    r = resume(swapped)
    assert (r['decision'], r['reason']) == ('HOLD', 'OVER_TOLERANCE')


def test_quality_wall_holds(swapped):
    swapped['plan'].update(gel_low_sag=140, gel_high_sag=145)
    r = resume(swapped)
    assert (r['decision'], r['reason']) == ('HOLD', 'QUALITY_INFEASIBLE')


def test_unknown_or_oversold_delivered_holds(swapped):
    swapped['resume']['delivered'] = {'PJ-99': 500}
    r = resume(swapped)
    assert (r['decision'], r['reason']) == ('HOLD', 'DELIVERED_FINDINGS')
    assert r['findings'][0]['codes'] == ['LOT_NOT_ACCEPTED']
    swapped['resume']['delivered'] = {'PJ-22': 6000}
    assert resume(swapped)['findings'][0]['codes'] == ['OVER_STOCK']


def test_expired_delivered_lot_holds(swapped):
    swapped['assays'] += 'PJ-24,2026-11-21,1000,g,10,150\n'
    swapped['resume']['delivered'] = {'PJ-21': 1500, 'PJ-24': 400}
    r = resume(swapped)
    assert r['reason'] == 'DELIVERED_FINDINGS'
    assert next(f for f in r['findings'] if f['lot'] == 'PJ-24')['codes'] == ['EXPIRED']


def test_zero_topup_when_delivered_already_compliant(swapped):
    swapped['resume']['delivered'] = {'PJ-21': 3900, 'PJ-22': 2300}
    r = resume(swapped)
    assert (r['decision'], r['topup'], r['mass_g']) == ('TOP_UP', {}, 6200)


def test_fresh_lot_opened_only_when_needed(swapped):
    swapped['resume']['delivered'] = {'PJ-21': 1500}
    r = resume(swapped)
    assert (r['decision'], r['new_lots']) == ('TOP_UP', 1)
    assert r['topup'] == {'PJ-21': 2400, 'PJ-22': 2400}


def test_stock_ledger_recognizes_actuals_only(swapped):
    s = process(swapped, 'stock')['stock']
    assert (s['delivered_g'], s['topup_g'], s['issued_g']) == (3000, 3200, 6200)
    rows = {row['lot']: row for row in s['rows']}
    assert (rows['PJ-21']['issued_g'], rows['PJ-21']['end_g'], rows['PJ-21']['code']) == (3900, 100, 'ISSUED')
    assert (s['begin_g'], s['end_g'], s['shortage_g'], s['balanced']) == (12000, 5800, -200, True)


def test_retry_never_double_deducts(client):
    one = client.post('/api/batches', json={'sample': 'resume'})
    two = client.post('/api/batches', json={'sample': 'resume'})
    assert (one.status_code, two.status_code, two.json['created']) == (201, 200, False)
    assert one.json['record'] == two.json['record']
    assert one.json['record']['stages']['stock']['issued_g'] == 6200
    assert len(client.get('/api/batches').json['batches']) == 1


def test_certificate_signs_only_quality_and_balanced(client, swapped):
    pack = client.post('/api/batches', json={'sample': 'resume'}).json
    assert client.get('/api/certificate/' + pack['batch_id']).json['can_trial'] is True
    swapped['resume']['tolerance_g'] = 0
    held = client.post('/api/batches', json=swapped).json
    assert client.get('/api/certificate/' + held['batch_id']).json['can_trial'] is False
    swapped['resume'].update(tolerance_g=300, delivered={'PJ-22': 6000})
    broken = client.post('/api/batches', json=swapped).json
    record = client.get('/api/certificate/' + broken['batch_id']).json
    assert record['can_trial'] is False and record['record']['stages']['stock']['balanced'] is False


def test_resume_contract(swapped):
    plan = process(swapped, 'dry')['plan']
    spec = swapped['resume']
    assert normalize_resume(spec, plan) == {'delivered': {'PJ-21': 1500, 'PJ-22': 1500},
                                            'step_g': 400, 'tolerance_g': 300}
    with pytest.raises(TrialError, match='RESUME_FIELDS_REQUIRED'):
        normalize_resume({'delivered': {}}, plan)
    with pytest.raises(TrialError, match='BAD_DELIVERED'):
        normalize_resume({**spec, 'delivered': {'PJ-21': -1}}, plan)
    with pytest.raises(TrialError, match='BAD_RESUME_VALUE'):
        normalize_resume({**spec, 'step_g': 'soon'}, plan)
    with pytest.raises(TrialError, match='BAD_RESUME_STEP'):
        normalize_resume({**spec, 'step_g': 0}, plan)
    with pytest.raises(TrialError, match='BAD_RESUME_STEP'):
        normalize_resume({**spec, 'step_g': 100}, plan)
    with pytest.raises(TrialError, match='BAD_RESUME_RANGE'):
        normalize_resume({**spec, 'tolerance_g': 6001}, plan)


def test_resume_api_and_pages(client):
    r = client.post('/api/resume', json={'sample': 'resume'}).json
    assert r['decision'] == 'TOP_UP' and r['topup'] == {'PJ-21': 2400, 'PJ-22': 800}
    assert client.post('/api/resume', json={'sample': 'dirty'}).json['decision'] == 'NOT_REQUESTED'
    page = client.get('/trial/resume?sample=resume')
    assert page.status_code == 200 and '补投可行'.encode() in page.data and b'2400' in page.data
    assert '未提供续配参数'.encode() in client.get('/trial/resume').data
    stock_page = client.get('/trial/stock?sample=resume')
    assert '实投批'.encode() in stock_page.data and b'6200 g' in stock_page.data


def test_custom_form_retains_resume_fields(client):
    response = client.post('/trial/resume', data={'sample': 'custom', 'proposal': '{}', 'delivered': '{broken',
                                                  'assays': 'draft,row', 'resume_step_g': '400'})
    assert all(value in response.data for value in (b'BAD_DELIVERED_JSON', b'{broken', b'draft,row', b'400'))


def test_topup_search_matches_brute_force():
    lots = [{'lot': 'A', 'remain_g': 3, 'delivered_g': 2, 'moisture_bp': 1000, 'gel_msag': 100000},
            {'lot': 'B', 'remain_g': 2, 'delivered_g': 0, 'moisture_bp': 0, 'gel_msag': 230000},
            {'lot': 'C', 'remain_g': 3, 'delivered_g': 5, 'moisture_bp': 2000, 'gel_msag': 140000},
            {'lot': 'D', 'remain_g': 2, 'delivered_g': 0, 'moisture_bp': 3000, 'gel_msag': 175000}]
    dry0 = 2 * 9000 + 5 * 8000
    moment0 = 2 * 9000 * 100000 + 5 * 8000 * 140000
    for low in (100000, 140000, 150000, 160000, 190000, 240000):
        plan = dict(dry_min_u=40000, gel_low_sag=low, gel_high_sag=low + 20000)
        base = (dry0 - 40000, moment0 - low * dry0, (low + 20000) * dry0 - moment0)
        possible = []
        for draw in product(*(range(lot['remain_g'] + 1) for lot in lots)):
            if not 4 <= sum(draw) <= 6:
                continue
            dry = dry0 + sum(n * (10000 - lot['moisture_bp']) for n, lot in zip(draw, lots))
            moment = moment0 + sum(n * (10000 - lot['moisture_bp']) * lot['gel_msag'] for n, lot in zip(draw, lots))
            if dry >= 40000 and low * dry <= moment <= (low + 20000) * dry:
                possible.append(draw)
        expected = min(possible, key=lambda draw: (sum(1 for n, lot in zip(draw, lots)
                                                       if n and not lot['delivered_g']),
                                                   tuple(-n for n in draw))) if possible else None
        actual, _ = search_topup(lots, plan, base, 4, 6, 1)
        assert actual == (list(expected) if expected else None)
