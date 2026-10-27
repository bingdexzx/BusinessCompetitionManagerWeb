import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('competitions', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='MapBackground',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file_path', models.CharField(blank=True, max_length=512, verbose_name='文件路径（相对 MEDIA_ROOT）')),
                ('url', models.CharField(max_length=2048, verbose_name='背景图 URL')),
                ('transform', models.JSONField(blank=True, null=True, verbose_name='变换（scale/x/y）')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='更新时间')),
                ('competition', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='map_backgrounds', to='competitions.competition', verbose_name='比赛')),
            ],
            options={
                'verbose_name': '地图背景',
                'verbose_name_plural': '地图背景',
            },
        ),
    ]
