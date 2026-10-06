"""
BusinessCompetitionManagerWeb 项目的 WSGI 配置。

它将 WSGI 可调用对象作为名为 ``application`` 的模块级变量暴露出来。

有关此文件的更多信息，请参阅
https://docs.djangoproject.com/en/6.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'BusinessCompetitionManagerWeb.settings')

application = get_wsgi_application()
