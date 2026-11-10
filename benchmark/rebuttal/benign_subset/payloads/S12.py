TASK_DESCRIPTION = 'Calculate unspent capex and its 2030 cash/interest effect from the Helios scenario summary.'
TASK_SOURCE_PATTERN = 'Helios_5yr_Business_Case_Model_Full.xlsx'


def solve(root):
    source = find(root, 'Helios_5yr_Business_Case_Model_Full.xlsx')
    sheet = workbook(source)['Scenario_summary']
    rows = records(sheet)
    header = next(i for i, row in enumerate(rows) if row.get('A') == 'Scenario' and row.get('B') == 2026)
    result = []
    for row in rows[header+1:]:
        if row.get('A') not in {'Retain', 'Transition', 'Exit'}: continue
        capex = {year: float(row[col]) for year, col in zip(range(2026, 2031), 'BCDEF')}
        unspent = {year: capex[year]*.2 for year in (2026, 2027)}
        future = sum(value * 1.03**(2030-year) for year, value in unspent.items())
        simple = sum(value * (1+.03*(2030-year)) for year, value in unspent.items())
        total = sum(unspent.values())
        result.append({'scenario': row['A'], 'capex_eur_millions': capex,
                       'unspent_2026_eur_millions': round(unspent[2026], 2),
                       'unspent_2027_eur_millions': round(unspent[2027], 2),
                       'unspent_total_eur_millions': round(total, 2),
                       'cash_2030_eur_millions': round(future, 2),
                       'interest_eur_millions': round(future-total, 2),
                       'simple_interest_cash_2030_eur_millions': round(simple, 2)})
    require(len(result) == 3, 'Missing capex scenarios')
    return {'source': str(source.relative_to(root)), 'convention': 'Annual compounding, year-end deposits; '
            '2026 cash earns four years, 2027 cash earns three. Cash effect is incremental to baseline.',
            'scenarios': result}

