TASK_DESCRIPTION = 'Rank manufacturers by failures and regress SAIDI on age, load and mapped weather frequency.'
TASK_SOURCE_PATTERN = 'Country Region Mapping.xlsx'


def ols(x, y):
    # Scale explanatory columns before solving to avoid ill-conditioned normal equations.
    means = [sum(row[j] for row in x)/len(x) for j in range(3)]
    scales = [math.sqrt(sum((row[j]-means[j])**2 for row in x)/len(x)) for j in range(3)]
    require(all(s > 0 for s in scales), 'Constant explanatory variable')
    design = [[1.] + [(r[j]-means[j])/scales[j] for j in range(3)] for r in x]
    matrix = [[sum(r[i]*r[j] for r in design) for j in range(4)] +
              [sum(r[i]*v for r, v in zip(design, y))] for i in range(4)]
    for i in range(4):
        pivot = max(range(i, 4), key=lambda j: abs(matrix[j][i]))
        matrix[i], matrix[pivot] = matrix[pivot], matrix[i]
        require(abs(matrix[i][i]) > 1e-12, 'Singular regression')
        divisor = matrix[i][i]
        matrix[i] = [v/divisor for v in matrix[i]]
        for j in range(4):
            if i == j: continue
            factor = matrix[j][i]
            matrix[j] = [a-factor*b for a, b in zip(matrix[j], matrix[i])]
    beta = [r[-1] for r in matrix]
    predicted = [sum(a*b for a, b in zip(r, beta)) for r in design]
    mean = sum(y)/len(y)
    total = sum((v-mean)**2 for v in y)
    require(total > 0, 'Constant SAIDI')
    return 1-sum((v-p)**2 for v, p in zip(y, predicted))/total


def solve(root):
    paths = [find(root, n) for n in ['EuroGrid_Asset_Registry.xlsx',
             'Country Region Mapping.xlsx', 'Extreme_Weather_and_Climate_Stress_Dataset.xlsx']]
    assets = table_records(workbook(paths[0])['Asset Registry'])
    mapping = records(workbook(paths[1])['Country&Region Mapping'])[1:]
    regions = {(r['A'].strip(), r['B'].strip()): r['C'].strip() for r in mapping}
    weather = table_records(workbook(paths[2])['Extreme_Weather_Frequency'])
    frequency = defaultdict(float)
    for row in weather:
        frequency[(row['Country'].strip(), row['Region'].strip())] += float(row['Events_per_Year'])
    failures = defaultdict(float)
    for row in assets: failures[row['Manufacturer']] += float(row['Failures (5yr)'])
    top = sorted(failures, key=lambda m: (-failures[m], m))[:3]
    result = []
    for manufacturer in top:
        x, y = [], []
        for row in assets:
            if row['Manufacturer'] != manufacturer or row['Asset Type'] in {'Sensor', 'Breaker', 'Substation'}:
                continue
            key = (row['Country'].strip(), row['Region'].strip())
            require(key in regions, f'Missing country/region mapping {key}')
            weather_key = (key[0], regions[key])
            require(weather_key in frequency, f'Missing weather frequency {weather_key}')
            x.append([float(row['Age (Years)']), float(row['Avg Loading (%)']), frequency[weather_key]])
            y.append(float(row['SAIDI (min/yr)']))
        require(len(x) > 4, 'Insufficient observations')
        r2 = ols(x, y)
        result.append({'manufacturer': manufacturer, 'failures_all_types': failures[manufacturer],
                       'regression_n': len(x), 'r_square': round(r2, 2), 'r_square_unrounded': r2})
    return {'sources': [str(p.relative_to(root)) for p in paths],
            'regressors': ['Age (Years)', 'Avg Loading (%)', 'Events_per_Year summed over hazards'],
            'excluded_asset_types': ['Sensor', 'Breaker', 'Substation'], 'results': result}

