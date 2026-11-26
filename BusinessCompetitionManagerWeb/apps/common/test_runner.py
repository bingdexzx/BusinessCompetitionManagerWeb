"""Django 测试运行器（多进程底层配套）。

唯一职责：**测试库销毁前关闭 channel layer 的 PostgreSQL 长连接**。

``apps.common.pg_channel_layer`` 会持有一条后台 drainer 连接（每线程还有复用连接），
测试结束 ``DROP DATABASE`` 时这些连接会报
``database is being accessed by other users``——在此统一收尾。
"""

from django.test.runner import DiscoverRunner


class GipfelTestRunner(DiscoverRunner):
    def teardown_databases(self, old_config, **kwargs):
        from apps.common.network_log_buffer import flush_network_logs
        from apps.common.pg_channel_layer import close_open_layers

        flush_network_logs()
        close_open_layers()
        return super().teardown_databases(old_config, **kwargs)
