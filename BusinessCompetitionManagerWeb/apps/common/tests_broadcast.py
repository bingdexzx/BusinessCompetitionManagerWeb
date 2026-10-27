"""资源变更广播测试（resource:changed + 断线 seq 重放）。"""

from django.test import TestCase
from rest_framework.test import APIClient

from apps.common.broadcast import emit_resource_changed, events_since
from apps.global_.logs.models import BroadcastEvent


class BroadcastTests(TestCase):
    databases = {'default'}

    def test_emit_and_replay_since_seq(self):
        seq1 = emit_resource_changed(7, 'contracts', 'created', {'id': 1})
        seq2 = emit_resource_changed(7, 'contracts', 'updated', {'id': 1})
        self.assertIsNotNone(seq1)
        self.assertGreater(seq2, seq1)

        replayed = events_since(7, 0)
        self.assertEqual([e['seq'] for e in replayed], [seq1, seq2])
        self.assertEqual(replayed[0]['resource'], 'contracts')

        # 断线重放只补发 lastSeq 之后的事件
        self.assertEqual([e['seq'] for e in events_since(7, seq1)], [seq2])
        self.assertEqual(events_since(7, seq2), [])
        # 其他比赛不串台
        self.assertEqual(events_since(8, 0), [])

    def test_broadcast_failure_never_raises(self):
        # payload 不可序列化时静默失败（返回 None），不影响业务
        self.assertIsNone(emit_resource_changed(7, 'contracts', 'created', {'x': {1, 2}}))

    def test_global_scope_broadcast_and_replay(self):
        """系统级（无比赛上下文）事件进 global 流，且与比赛流互不串台。"""
        from apps.common.broadcast import group_for

        self.assertEqual(group_for(None), 'global')
        self.assertEqual(group_for(0), 'global')
        self.assertEqual(group_for(7), 'comp_7')

        seq = emit_resource_changed(None, 'users', 'created', {'id': 1})
        self.assertIsNotNone(seq)
        global_events = events_since(None, 0)
        self.assertIn(seq, [e['seq'] for e in global_events])
        self.assertTrue(all(e['competitionId'] is None for e in global_events))
        # 全局事件不进比赛流；比赛事件不进全局流
        self.assertNotIn(seq, [e['seq'] for e in events_since(7, 0)])
        comp_seq = emit_resource_changed(7, 'contracts', 'created', {'id': 2})
        self.assertNotIn(comp_seq, [e['seq'] for e in events_since(None, 0)])

    def test_scope_follows_path_not_header(self):
        """作用域按路径判定：全局资源带 X-Competition-Id 头时仍进 global 流。"""
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(
            username='badmin3', password='x' * 12, email='badmin3@test.local', is_superuser=True)
        client = APIClient()
        client.force_authenticate(user)

        resp = client.post('/api/schools', {'name': '带比赛头的学校'},
                           format='json', HTTP_X_COMPETITION_ID='7')
        self.assertIn(resp.status_code, (200, 201), resp.content)
        row = BroadcastEvent.objects.order_by('-seq').first()
        self.assertEqual(row.resource, 'schools')
        self.assertIsNone(row.competition_id)  # 全局库资源：不进 comp_7

    def test_middleware_broadcasts_on_successful_write(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(
            username='badmin', password='x' * 12, email='badmin@test.local', is_superuser=True)
        client = APIClient()
        client.force_authenticate(user)

        before = BroadcastEvent.objects.count()
        resp = client.post('/api/schools', {'name': '广播测试学校'}, format='json')
        self.assertIn(resp.status_code, (200, 201), resp.content)
        events = BroadcastEvent.objects.all()
        self.assertEqual(events.count(), before + 1)
        self.assertEqual(events.first().resource, 'schools')
        self.assertEqual(events.first().action, 'created')

        # 读请求不广播
        resp = client.get('/api/schools')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(BroadcastEvent.objects.count(), before + 1)

    def test_middleware_skips_failed_write(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(
            username='badmin2', password='x' * 12, email='badmin2@test.local', is_superuser=True)
        client = APIClient()
        client.force_authenticate(user)
        before = BroadcastEvent.objects.count()
        resp = client.post('/api/schools', {'name': ''}, format='json')  # 非法请求
        self.assertGreaterEqual(resp.status_code, 400)
        self.assertEqual(BroadcastEvent.objects.count(), before)
