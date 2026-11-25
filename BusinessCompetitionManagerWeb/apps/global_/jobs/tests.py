"""后台任务队列（2026-11）：入队 / 去重 / 执行 / 失败落库 / 接口权限。"""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.common import context as ctx
from apps.global_.competitions.models import Competition
from apps.global_.jobs import services as job_services
from apps.global_.jobs.models import BackgroundJob
from apps.global_.memberships.models import CompetitionMembership
from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

ALIAS = 'comp_unittest'
register_competition_db(ALIAS)

User = get_user_model()


class BackgroundJobTests(TestCase):
    databases = {'default', ALIAS}

    @classmethod
    def tearDownClass(cls):
        ctx.clear_request_context()
        super().tearDownClass()

    def setUp(self):
        self.competition = Competition.objects.create(
            name='任务队列赛', code='JOB', db_name=ALIAS)
        self.cid = self.competition.pk
        ctx.set_competition_context(self.cid, ALIAS)
        self.root = User.objects.create_user(
            username='job_root', password='x' * 12, email='job_root@test.local',
            is_superuser=True)
        self.player = User.objects.create_user(
            username='job_player', password='x' * 12, email='job_player@test.local')
        CompetitionMembership.objects.create(
            user=self.player, competition=self.competition,
            identity=CompetitionMembership.Identity.PLAYER)
        self.client = APIClient()
        self.client.force_authenticate(self.root)

    def _url(self):
        return f'/api/competitions/{self.cid}/jobs'

    def test_enqueue_dedupes_active_job(self):
        first = job_services.enqueue(kind='SETTLEMENT', competition_id=self.cid)
        second = job_services.enqueue(kind='SETTLEMENT', competition_id=self.cid)
        self.assertEqual(first.id, second.id)
        self.assertTrue(first.is_active)

    def test_enqueue_rejects_unknown_kind(self):
        with self.assertRaises(job_services.JobError):
            job_services.enqueue(kind='NOPE', competition_id=self.cid)

    def test_run_job_marks_success_with_result(self):
        job = job_services.enqueue(kind='SETTLEMENT', competition_id=self.cid)
        with mock.patch(
                'apps.competition.settlement.services.run_settlement') as runner:
            runner.return_value = mock.Mock(id=7, result={'entries': [{}, {}]})
            done = job_services.run_job(job)
        self.assertEqual(done.status, BackgroundJob.Status.SUCCESS)
        self.assertEqual(done.progress, 100)
        self.assertEqual(done.result, {'runId': 7, 'entries': 2})
        self.assertIsNotNone(done.finished_at)

    def test_run_job_records_failure(self):
        job = job_services.enqueue(kind='SETTLEMENT', competition_id=self.cid)
        with mock.patch(
                'apps.competition.settlement.services.run_settlement',
                side_effect=RuntimeError('boom')):
            done = job_services.run_job(job)
        self.assertEqual(done.status, BackgroundJob.Status.FAILED)
        self.assertIn('boom', done.error)

    def test_run_pending_takes_only_pending(self):
        first = job_services.enqueue(kind='SETTLEMENT', competition_id=self.cid)
        first.status = BackgroundJob.Status.SUCCESS
        first.save(update_fields=['status'])
        pending = job_services.enqueue(kind='FISCAL_OPEN', competition_id=self.cid)
        with mock.patch(
                'apps.competition.fiscal.services.open_fiscal_year') as opener:
            opener.return_value = mock.Mock(id=3, year=2)
            jobs = job_services.run_pending(limit=5)
        self.assertEqual([job.id for job in jobs], [pending.id])
        self.assertEqual(jobs[0].status, BackgroundJob.Status.SUCCESS)

    def test_api_submit_and_poll(self):
        response = self.client.post(self._url(), {'kind': 'SETTLEMENT'},
                                   format='json', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 201, response.content)
        job_id = response.json()['id']
        self.assertEqual(response.json()['status'], 'PENDING')

        detail = self.client.get(f'{self._url()}/{job_id}', HTTP_HOST='127.0.0.1')
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()['id'], job_id)

        listing = self.client.get(self._url(), HTTP_HOST='127.0.0.1')
        self.assertEqual(len(listing.json()), 1)

    def test_package_import_job_runs_importer(self):
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        stored = default_storage.save('packages/pending/test.zip', ContentFile(b'PK\x03\x04'))
        job = job_services.enqueue(
            kind='PACKAGE_IMPORT', competition_id=self.cid, user=self.root,
            payload={'storedPath': stored, 'fileName': 'test.zip'})

        fake_package = mock.Mock(id=42, status='SUCCESS')
        with mock.patch('apps.global_.packages.importer.import_package',
                        return_value=fake_package) as importer_call:
            done = job_services.run_job(job)

        self.assertEqual(done.status, BackgroundJob.Status.SUCCESS)
        self.assertEqual(done.result, {'packageId': 42, 'status': 'SUCCESS'})
        self.assertTrue(importer_call.called)
        # 导入完成后临时文件要清理
        self.assertFalse(default_storage.exists(stored))

    def test_package_import_job_fails_when_file_missing(self):
        job = job_services.enqueue(
            kind='PACKAGE_IMPORT', competition_id=self.cid, user=self.root,
            payload={'storedPath': 'packages/pending/not-exists.zip'})
        done = job_services.run_job(job)
        self.assertEqual(done.status, BackgroundJob.Status.FAILED)
        self.assertIn('文件已不存在', done.error)

    def test_player_cannot_use_jobs(self):
        client = APIClient()
        client.force_authenticate(self.player)
        response = client.post(self._url(), {'kind': 'SETTLEMENT'},
                               format='json', HTTP_HOST='127.0.0.1')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            client.get(self._url(), HTTP_HOST='127.0.0.1').status_code, 403)
