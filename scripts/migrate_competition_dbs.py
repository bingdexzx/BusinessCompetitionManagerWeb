"""为所有比赛库补迁移（新增索引/字段后同步存量 comp_<id> 库；幂等）。"""

import os
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'BusinessCompetitionManagerWeb.settings')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'BusinessCompetitionManagerWeb'))
import django  # noqa: E402

django.setup()

from apps.competition import provisioning  # noqa: E402
from apps.global_.competitions.models import Competition  # noqa: E402

for comp in Competition.objects.exclude(db_name='').order_by('id'):
    provisioning.create_competition_database(comp.db_name)  # CREATE(若缺) + migrate（幂等）
    print('migrated:', comp.db_name)
print('done')
