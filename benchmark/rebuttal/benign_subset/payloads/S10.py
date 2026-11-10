TASK_DESCRIPTION = 'Calculate BBDC/TPVG pro forma business-services exposure from the September 2025 10-Qs.'


def solve(root):
    bbdc_path = find(root, 'BBDC_10Q_09.30.2025.pdf')
    tpvg_path = find(root, 'TPVG_10Q_09.30.2025.pdf')
    b = pdf(bbdc_path, True)
    t = pdf(tpvg_path, True)
    # The first balance-sheet line is the current-period value; the second is the prior period.
    btotal_line = next(l for l in b.splitlines() if re.search('Total investments at fair value', l, re.I))
    ttotal_line = next(l for l in t.splitlines() if 'Investments at fair value (amortized cost' in l)
    btotal = numbers(btotal_line)[0]
    ttotal = numbers(ttotal_line.split('respectively)')[-1])[0]
    # Restrict investment schedules to September, before the December comparative schedule.
    bstart = b.index('Unaudited Consolidated Schedule of Investments')
    bprior = re.search(r'Consolidated Schedule of Investments\s+December 31, 2024', b[bstart:])
    require(bprior is not None, 'Cannot locate prior-period BBDC schedule boundary')
    bcurrent = b[bstart:bstart + bprior.start()]
    lines = bcurrent.splitlines()
    subtotals = []
    for i, line in enumerate(lines):
        if 'Subtotal Services: Business' not in line: continue
        tail = line.split(')*')[-1].strip()
        if not tail:
            tail = next((s.strip() for s in lines[i+1:i+4] if s.strip()), '')
        require(tail, 'Empty BBDC business subtotal')
        vals = numbers(tail)
        subtotals.append(vals[-1] if vals else 0.0)
    require(len(subtotals) == 4, f'Expected four BBDC business subtotals, got {len(subtotals)}')
    # TPVG schedule is immediately followed by its December comparative schedule.
    start_match = re.search(r'CONSOLIDATED SCHEDULE OF INVESTMENTS\s*(?:\([^\n]*\)\s*)?(?:As of\s+)?September 30, 2025', t, re.I)
    require(start_match is not None, 'Cannot locate current-period TPVG schedule')
    tstart = start_match.start()
    prior = re.search(r'Consolidated Schedule of Investments\s*(?:\([^\n]*\)\s*)?(?:As of\s+)?December 31, 2024', t[tstart:], re.I)
    require(prior is not None, 'Cannot locate prior-period TPVG schedule boundary')
    current = t[tstart:tstart + prior.start()]
    tsub = [numbers(line.split('*', 1)[-1])[-1] for line in current.splitlines()
            if 'Total Business Products and Services -' in line]
    require(len(tsub) == 3, f'Expected three TPVG business subtotals, got {len(tsub)}')
    muon = []
    lines = current.splitlines()
    for i, line in enumerate(lines):
        if 'Muon Space, Inc.' not in line: continue
        if 'Preferred Stock' in line:
            muon.append(numbers(line)[-1])
        elif 'Growth Capital Loan' in line:
            # Sum the two loan fair values via their printed issuer subtotal.
            block = lines[i+1:i+7]
            candidates = [numbers(l) for l in block if re.fullmatch(r'[\s\d,]+', l) and len(numbers(l)) == 3]
            require(len(candidates) == 1, 'Ambiguous Muon loan subtotal')
            muon.append(candidates[0][-1])
    require(len(muon) == 2, 'Expected Muon loan and warrant holdings')
    numerator = sum(subtotals) + sum(tsub) - sum(muon)
    denominator = btotal + ttotal
    return {'sources': [str(p.relative_to(root)) for p in [bbdc_path, tpvg_path]],
            'units': 'USD thousands', 'bbdc_business_subtotals': subtotals,
            'tpvg_business_subtotals': tsub, 'muon_excluded': muon,
            'business_services_fair_value': numerator, 'total_fair_value': denominator,
            'exposure_percent': round(numerator / denominator * 100, 2)}

