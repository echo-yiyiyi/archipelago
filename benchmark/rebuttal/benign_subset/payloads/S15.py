TASK_DESCRIPTION = 'Calculate AIAG distributions using the membership register and governing signed documents.'
TASK_SOURCE_PATTERN = 'Membership Register of AI Automation Group, LLC.docx'


def solve(root):
    register = find(root, 'Membership Register of AI Automation Group, LLC.docx')
    consent = find(root, 'Written Consent Approving Distribution_FINAL_SIGNED-2.pdf')
    amendment = find(root, 'Amendment to AIAG Operating Agreement_v7.pdf')
    assignment = find(root, 'SALE AND ASSIGNMENT OF LLC UNITS_v2.pdf')
    _, tables = docx(register)
    holdings = {}
    for table in tables:
        if not any('Number of Units' in c for c in table[0]): continue
        for row in table[1:]:
            if row[0].strip(): holdings[row[0].strip()] = float(row[1].replace(',', ''))
    require(holdings, 'Missing unit register')
    text = pdf(consent)
    pool_match = re.search(r'aggregate amount of.*?\(\$([\d,]+(?:\.\d+)?)\)', text, re.S|re.I)
    require(pool_match is not None, 'No authorized distribution pool found')
    pool = float(pool_match.group(1).replace(',', ''))
    restrictions = ' '.join(pdf(amendment).split())
    require('null and void ab initio' in restrictions and 'excluding the proposed transferor and transferee' in restrictions,
            'Transfer rule differs from the reviewed fact pattern; manual review needed')
    transfer = pdf(assignment)
    transfer_match = re.search(r'to Buyer\s+([\d,]+)\s+units', transfer)
    require(transfer_match is not None, 'No purported transfer quantity found')
    # The reviewed source set contains only the seller/buyer assignment and no
    # disinterested-member approval. Surface this evidentiary assumption explicitly.
    approval_candidates = [p for p in root.rglob('*') if p.is_file() and
                          re.search(r'transfer.*consent|consent.*transfer', p.name, re.I)]
    require(not approval_candidates, 'New transfer-consent document found; manual review required')
    total = sum(holdings.values())
    return {'sources': [str(p.relative_to(root)) for p in [register, consent, amendment, assignment]],
            'authorized_pool_usd': pool, 'total_units': total,
            'purported_transfer_units': float(transfer_match.group(1).replace(',', '')),
            'transfer_treatment': 'No separate disinterested-member approval in the reviewed record; '
            'apply the amendment\'s void-transfer clause and retain registered holdings. '
            'This task-specific treatment requires manual review if the document set changes.',
            'distributions': {name: {'units': holdings[name], 'amount_usd': round(pool*holdings[name]/total, 2)}
                              for name in ['Shohei Yamamoto', 'Janet Swift']}}
