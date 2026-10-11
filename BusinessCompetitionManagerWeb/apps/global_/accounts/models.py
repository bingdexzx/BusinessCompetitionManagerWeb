"""用户（§6.1 users）：username 唯一、密码 bcrypt（Django 校验器）、displayName、邮箱、
一账号一学校（schoolId）、isActive、tokenVersion；**不带 role**——比赛内身份在
CompetitionMembership（§15.1）。"""

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    display_name = models.CharField('显示名', max_length=100, blank=True)
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
