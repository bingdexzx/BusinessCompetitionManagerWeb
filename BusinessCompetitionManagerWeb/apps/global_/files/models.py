"""文件上传服务模型（全局域，走全局库 default）。

文件本体按约定目录落在 MEDIA_ROOT 下（uploads/、map_backgrounds/、messages/），
数据库只保存相对路径与对外 URL；地图背景按比赛唯一（MapBackground）。
"""

from django.db import models


class MapBackground(models.Model):
    """比赛地图背景（每比赛至多一条）。

    - file_path：服务端上传文件相对 MEDIA_ROOT 的路径（外链/图片 URL 模式下为空）；
    - url：前端可直接渲染的地址（服务端文件为 /api/files/view/<相对路径>，
      也可能是外部图片 URL / data:image/...）；
    - transform：画布变换 {scale, x, y}；null 表示按节点包围盒自动适配。
    """

    competition = models.OneToOneField(
        'competitions.Competition', verbose_name='比赛',
        on_delete=models.CASCADE, related_name='map_backgrounds',
    )
    file_path = models.CharField('文件路径（相对 MEDIA_ROOT）', max_length=512, blank=True)
    url = models.CharField('背景图 URL', max_length=2048)
    transform = models.JSONField('变换（scale/x/y）', null=True, blank=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = '地图背景'
        verbose_name_plural = '地图背景'

    def __str__(self):
        return f'MapBackground(competition={self.competition_id})'
