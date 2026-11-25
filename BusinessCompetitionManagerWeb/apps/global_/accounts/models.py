"""用户（§6.1 users）：username 唯一、密码 bcrypt（Django 校验器）、displayName、邮箱、
一账号一学校（schoolId）、isActive、tokenVersion；**不带 role**——比赛内身份在
CompetitionMembership（§15.1）。"""

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    display_name = models.CharField('显示名', max_length=100, blank=True)
    avatar = models.TextField('头像 URL', blank=True, default='')
    email = models.EmailField('邮箱', unique=True, null=True, blank=True)
    school = models.ForeignKey(
        'schools.School',
        verbose_name='学校',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='users',
    )
    token_version = models.PositiveIntegerField('令牌版本', default=0)
    update_log_seen_id = models.PositiveBigIntegerField('已读更新日志 ID', default=0)

    class Meta:
        verbose_name = '用户'
        verbose_name_plural = '用户'
        ordering = ['-date_joined']

    def __str__(self):
        return self.username

    def bump_token_version(self):
        """顶号 / 改密 / 权限变更后使已发 JWT 失效（§17 风险对策）。"""
        self.token_version += 1
        self.save(update_fields=['token_version'])


class LoginThrottle(models.Model):
    """登录失败限流（旧系统等价能力）：窗口内失败 N 次 → 锁定 M 分钟。

    键 = 用户名|客户端 IP（大小写不敏感用户名），逐键计数；
    成功登录即清零。多进程部署下用数据库计数（进程内计数会被 worker 数摊薄）。
    """
    key = models.CharField('限流键（用户名|IP）', max_length=220, unique=True)
    fail_count = models.PositiveIntegerField('窗口内失败次数', default=0)
    window_start = models.DateTimeField('窗口起点', auto_now_add=True)
    locked_until = models.DateTimeField('锁定至', null=True, blank=True)
    updated_at = models.DateTimeField('最近一次失败', auto_now=True)

    class Meta:
        verbose_name = '登录限流'
        verbose_name_plural = '登录限流'

    def __str__(self):
        return self.key


class UpdateLog(models.Model):
    """系统更新日志：超管发布，用户按 ``User.update_log_seen_id`` 游标只弹一次。"""

    version = models.CharField('版本号', max_length=40, unique=True)
    title = models.CharField('标题', max_length=120)
    content = models.TextField('更新内容')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name='发布人',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='update_logs',
    )
    created_by_username = models.CharField('发布人用户名', max_length=150, blank=True)
    published_at = models.DateTimeField('发布时间', auto_now_add=True)

    class Meta:
        verbose_name = '更新日志'
        verbose_name_plural = '更新日志'
        ordering = ['-published_at', '-id']

    def __str__(self):
        return f'{self.version} {self.title}'

