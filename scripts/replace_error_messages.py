"""全量替换前端错误提示：`x instanceof Error ? x.message : '兜底'` → `errorMessage(x, '兜底')`，
并为每个改动文件自动补 `import { errorMessage } from '@/utils/errors'`。"""

import io
import re
from pathlib import Path

SRC = Path(r'C:\Users\32394\Desktop\BusinessCompetitionManagerWeb\BusinessCompetitionManagerWebFrontend\src')
PATTERN = re.compile(r"(\w+) instanceof Error \? \1\.message : '([^']*)'")

total = 0
for path in sorted(SRC.rglob('*.vue')) + sorted(SRC.rglob('*.ts')):
    if path.name == 'errors.ts':
        continue
    text = path.read_text(encoding='utf-8')
    new_text, count = PATTERN.subn(lambda m: f"errorMessage({m.group(1)}, '{m.group(2)}')", text)
    if count == 0:
        continue
    if 'utils/errors' not in new_text and "'@/utils/errors'" not in new_text:
        # 在最后一个顶层 import 后插入
        imports = list(re.finditer(r"^import .*?$", new_text, flags=re.M))
        if imports:
            pos = imports[-1].end()
            new_text = new_text[:pos] + "\nimport { errorMessage } from '@/utils/errors'" + new_text[pos:]
        else:
            new_text = f"import {{ errorMessage }} from '@/utils/errors'\n{new_text}"
    path.write_text(new_text, encoding='utf-8', newline='')
    total += count
    print(f'{count:3d}  {path.relative_to(SRC)}')
print(f'total replaced: {total}')
