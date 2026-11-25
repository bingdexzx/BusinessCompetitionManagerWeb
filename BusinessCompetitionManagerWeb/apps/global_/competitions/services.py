"""比赛元数据服务：创建比赛 + 自动建库（M0：创建即建库；M1 起由比赛包导入触发）。"""

from django.db import transaction
from django.utils import timezone

from apps.competition import provisioning
from apps.global_.competitions.models import Competition


@transaction.atomic
def create_competition(*, name, created_by, cover_image='', host_schools=None,
                       location='', staffing_info='', code='',
                       ticket_image='') -> Competition:
    """创建比赛记录并自动创建该比赛专属数据库（决策 D1 / §2.2 阶段二）。"""
    competition = Competition(
        name=name,
        code=code or f'C{timezone.now().year % 100:02d}{Competition.objects.count() + 1:04d}',
        cover_image=cover_image,
        ticket_image=ticket_image,
        location=location,
        staffing_info=staffing_info,
        created_by=created_by,
    )
    competition.save()
    if host_schools:
        competition.host_schools.set(host_schools)
    competition.db_name = provisioning.competition_db_name(competition.pk)
    competition.save(update_fields=['db_name'])
    provisioning.create_competition_database(competition.db_name)
    return competition
