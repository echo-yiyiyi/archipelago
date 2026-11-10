TASK_DESCRIPTION = 'Extract EV unit prices from 2022 expert calls and the 2025 synthesis and calculate changes.'


def solve(root):
    families = ['Vehicle electronics sensors and controls', 'EV charging and onboard power']
    # Section boundaries follow the family introductions used in the source summaries.
    all_families = ['vehicle electronics sensors and controls', 'ev charging and onboard power',
                    'hybrid transmissions and e drive units', 'power electronics and electric motors',
                    'battery management systems', 'thermal management', 'engine control',
                    'exhaust', 'fuel and injection', 'driveline', 'engine core', 'sensors and wiring',
                    'low voltage wiring and harnesses']
    data = {family: [] for family in families}
    calls = sorted(root.glob('122022_Call_Summary_*.docx'))
    require(len(calls) == 10, f'Expected ten 2022 call summaries, found {len(calls)}')
    for path in calls:
        paragraphs, _ = docx(path)
        text = '\n'.join(paragraphs)
        lower = text.lower()
        # Each price belongs to the most recent family mention. The local section
        # is bounded at the next family mention; powertrain must be explicit there.
        mentions = sorted((m.start(), m.end(), family) for family in all_families
                          for m in re.finditer(re.escape(family), lower))
        for match in re.finditer(r'€([\d]+(?:\.\d+)?)', text):
            before = [m for m in mentions if m[0] < match.start()]
            if not before: continue
            start, end, family = before[-1]
            target = next((f for f in families if f.lower() == family), None)
            if target is None: continue
            next_start = next((m[0] for m in mentions if m[0] > start), len(text))
            section = text[start:next_start]
            # Mentions may occur late in the introduction: include the preceding sentence.
            powertrains = set(re.findall(r'\b(EV|Hybrid|ICE)\b', section))
            if powertrains != {'EV'}: continue
            data[target].append({'expert': paragraphs[0].replace('Expert Call Summary – ', ''),
                                 'price_eur': float(match.group(1)),
                                 'source': str(path.relative_to(root))})
    synthesis = find(root, '20251120_Helios_expert_synthesis_v2.xlsx')
    sheet = workbook(synthesis)['Family_synthesis']
    result = []
    for family in families:
        points = data[family]
        require(points, f'No 2022 EV prices for {family}')
        candidates = [row for row in records(sheet) if row.get('A') == family and row.get('B') == 'EV']
        require(len(candidates) == 1, 'Ambiguous 2025 synthesis price')
        mean = sum(p['price_eur'] for p in points) / len(points)
        current = float(candidates[0]['F'])
        result.append({'family': family, '2022_price_points': points,
                       '2022_mean_eur': round(mean, 2), '2025_synthesis_eur': current,
                       'change_percent': round((current/mean-1)*100, 2)})
    return {'2025_source': str(synthesis.relative_to(root)), 'families': result}

