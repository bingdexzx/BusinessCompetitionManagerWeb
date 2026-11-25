"""取消「比赛超级管理员」身份：存量 COMP_SUPER_ADMIN → 管理员（主席团），恢复所辖公司字段。"""

from django.db import migrations, models


def comp_super_to_admin(apps, schema_editor):
    Membership = apps.get_model('memberships', 'CompetitionMembership')
    Membership.objects.filter(identity='COMP_SUPER_ADMIN').update(identity='ADMIN')


class Migration(migrations.Migration):

    dependencies = [
        ('memberships', '0002_remove_admin_identity'),
    ]

    operations = [
        migrations.AddField(
            model_name='competitionmembership',
            name='managed_companies',
            field=models.JSONField(blank=True, default=list, verbose_name='所辖公司'),
        ),
        migrations.RunPython(comp_super_to_admin, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='competitionmembership',
            name='identity',
            field=models.CharField(
                choices=[('ADMIN', '管理员（主席团）'), ('PLAYER', '参赛代表')],
                max_length=32, verbose_name='比赛内身份',
            ),
        ),
    ]
