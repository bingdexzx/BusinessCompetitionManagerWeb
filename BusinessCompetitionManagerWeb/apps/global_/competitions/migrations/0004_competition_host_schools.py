"""办赛学校：单校外键 → 多对多（并迁移存量单校数据）。"""

from django.db import migrations, models


def copy_host_school(apps, schema_editor):
    Competition = apps.get_model('competitions', 'Competition')
    for competition in Competition.objects.exclude(host_school__isnull=True):
        competition.host_schools.add(competition.host_school_id)


class Migration(migrations.Migration):

    dependencies = [
        ('competitions', '0003_competition_dashboard_layout'),
        ('schools', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='competition',
            name='host_schools',
            field=models.ManyToManyField(
                blank=True, related_name='hosted_competitions',
                to='schools.school', verbose_name='办赛学校',
            ),
        ),
        migrations.RunPython(copy_host_school, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='competition',
            name='host_school',
        ),
    ]
