TASK_DESCRIPTION = 'Calculate Planet Fitness store FCFF and DCF enterprise value from the LBO model.'
TASK_SOURCE_PATTERN = 'PLTF_LBO_v06.xlsx'


def solve(root):
    source = find(root, 'PLTF_LBO_v06.xlsx')
    sheet = workbook(source)['Assumptions']
    # The successful trajectory identifies these four seasonally matched quarters.
    historical = {q: float(sheet[cell]) for q, cell in
                  [('Q4_2024', 'J75'), ('Q1_2025', 'L75'), ('Q2_2025', 'M75'), ('Q3_2025', 'N75')]}
    stores = float(sheet['N72'])
    require(stores > 0, 'Invalid store count')
    margin = (.39-.05)*(1-.20)+.05-.02
    annual = []
    for year in range(2026, 2031):
        exponent = year-2025
        revenue = stores*(sum(historical[q]*1.05**exponent for q in ['Q1_2025','Q2_2025','Q3_2025'])
                          + historical['Q4_2024']*1.05**(exponent+1))
        fcff = revenue*margin
        annual.append({'year': year, 'revenue_usd_mm': revenue, 'fcff_usd_mm': fcff,
                       'pv_usd_mm': fcff/1.12**exponent})
    terminal = annual[-1]['fcff_usd_mm']*1.02/(.12-.02)
    ev = sum(r['pv_usd_mm'] for r in annual)+terminal/1.12**5
    return {'source': str(source.relative_to(root)), 'stores': stores,
            'historical_revenue_per_store_usd_mm': historical,
            'fcff_margin': margin, 'annual': [{k: round(v, 2) if k != 'year' else v for k, v in r.items()}
                                             for r in annual],
            'terminal_value_usd_mm': round(terminal, 2),
            'enterprise_value_usd_mm': round(ev, 2),
            'convention': 'Year-end annual discounting; fixed existing-store portfolio; no incremental NWC assumption.'}

