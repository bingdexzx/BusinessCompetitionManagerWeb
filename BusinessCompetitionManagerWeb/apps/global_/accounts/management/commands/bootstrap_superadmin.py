"""引导超级管理员（§15.1：系统级只有超级管理员与用户；首个超级管理员由此命令指定）。"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = '创建或提升超级管理员：bootstrap_superadmin <username> [--password ...]'

    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('--password', dest='password')
        parser.add_argument('--email', dest='email', default=None)
        parser.add_argument('--display-name', dest='display_name', default='')

    def handle(self, *args, **options):
        User = get_user_model()
        username = options['username']
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                'display_name': options['display_name'] or username,
                'is_staff': True,
                'email': options['email'],
            },
        )
        password = options['password']
        if created:
            if not password:
                raise CommandError('新建用户必须提供 --password')
            user.set_password(password)
        elif password:
            user.set_password(password)
        if options['email']:
            user.email = options['email']
        user.is_superuser = True
        user.is_staff = True
        user.save()
        user.bump_token_version()
        self.stdout.write(self.style.SUCCESS(f'超级管理员已就绪：{username}'))
