TASK_DESCRIPTION = 'Determine the cancellation interval from the final shipbuilding contract.'


def solve(root):
    source = find(root, 'LNG_Shipbuilding_Contract Final.docx')
    paragraphs, tables = docx(source)
    intervals = []
    for table in tables:
        header = next((r for r in table if any('Cancelling Date' in c for c in r)), None)
        if not header:
            continue
        delivery = next(i for i, c in enumerate(header) if 'Contractual Delivery Date' in c)
        cancellation = next(i for i, c in enumerate(header) if 'Cancelling Date' in c)
        for row in table[table.index(header) + 1:]:
            if len(row) <= max(delivery, cancellation): continue
            start = datetime.strptime(row[delivery].strip(), '%B %d, %Y')
            end = datetime.strptime(row[cancellation].strip(), '%B %d, %Y')
            intervals.append({'vessel': row[0], 'delivery': row[delivery],
                              'cancelling_date': row[cancellation], 'days': (end-start).days})
    require(intervals, 'No cancellation-date table was found')
    return {'answer': 'Yes.' if all(r['days'] == 180 for r in intervals) else 'No.',
            'source': str(source.relative_to(root)), 'intervals': intervals,
            'note': 'The 180-day liquidated-damages cap is distinct from the cancelling date.'}

