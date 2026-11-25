"""取消「管理员（主席团）」身份：存量 ADMIN → 比赛超管，并移除所辖公司字段。"""

from django.db import migrations, models


def admins_to_comp_super(apps, schema_editor):
    Membership = apps.get_model('memberships', 'CompetitionMembership')
    Membership.objects.filter(identity='ADMIN').update(identity='COMP_SUPER_ADMIN')


class Migration(migrations.Migration):

    dependencies = [
        ('memberships', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='competitionmembership',
            name='identity',
            field=models.CharField(
                choices=[('COMP_SUPER_ADMIN', '比赛超级管理员'), ('PLAYER', '参赛代表')],
                max_length=32, verbose_name='比赛内身份',
            ),
        ),
        migrations.RunPython(admins_to_comp_super, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='competitionmembership',
            name='managed_companies',
        ),
    ]
