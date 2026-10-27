"""历史获奖记录回填「奖项名称」（2026-10 需求变更的数据迁移）。

旧实现「按名次区间自动评奖」只写了 ``award_level``（如「一等奖」），没有 ``award_name``；
新的个人档案界面按**奖项名称**展示，因此把 ``award_level`` 回填到 ``award_name``，
避免历史记录在新界面上显示为空。不改动等级/奖牌/比赛等其它字段，可安全重复执行。
"""

from django.db import migrations
from django.db.models import F


def backfill_award_name(apps, schema_editor):
    AwardRecord = apps.get_model('profiles', 'AwardRecord')
    updated = (
        AwardRecord.objects
        .filter(award_name='')
        .exclude(award_level='')
        .update(award_name=F('award_level'))
    )
    if updated:
        print(f'  历史获奖记录回填奖项名称：{updated} 条')


def noop(apps, schema_editor):
    """反向迁移不回滚（回填是幂等的展示性修正，无副作用）。"""


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0002_remove_awardrecord_uniq_user_competition_award_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_award_name, noop),
    ]
