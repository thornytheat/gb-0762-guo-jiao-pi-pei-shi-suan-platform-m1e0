from app.modules.batches.seal import canonical, sha


def issue(record):
    stages = record['stages']
    stock = stages['stock']
    resume = stages.get('resume')
    if resume:
        can_trial = (resume['decision'] == 'TOP_UP' and all(resume['checks'].values()) and stock['balanced'])
    else:
        blend = stages['blend']
        can_trial = blend['status'] == 'FEASIBLE' and stock['balanced'] and stock['shortage_g'] == 0
    return {'batch_id': record['batch_id'], 'integrity_sha256': sha(canonical(record)),
            'can_trial': can_trial,
            'stock_lines': len(stock['rows']), 'isolation_lines': len(stages['assay']['isolated']), 'record': record}
