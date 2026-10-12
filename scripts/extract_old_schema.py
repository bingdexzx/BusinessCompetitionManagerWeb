import re
from pathlib import Path

OLD = Path(r'C:\Users\32394\Desktop\GipfelBusinessCompetitionManagerWeb\backend\apps')
APPS = ['fuels', 'warehouses', 'vehicles', 'maps', 'materials', 'products', 'parts',
        'infrastructures', 'tech_tree', 'production_lines']
for app in APPS:
    model_file = OLD / app / 'models.py'
    if not model_file.exists():
        print(f'== {app}: 无 models.py ==')
        continue
    text = model_file.read_text(encoding='utf-8')
    print(f'== {app} ==')
    # 抽取字段行（models.XxxField(...) 声明）
    for line in text.splitlines():
        s = line.strip()
        if re.match(r'^\w+ = models\.\w+Field\(', s) or s.startswith('class '):
            print('   ', s[:110])
