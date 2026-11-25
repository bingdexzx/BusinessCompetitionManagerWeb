"""后台任务服务：入队、消费、进度回报（不依赖 Redis/Celery）。"""

from django.utils import timezone

from apps.global_.jobs.models import BackgroundJob

SUPPORTED_KINDS = {choice.value for choice in BackgroundJob.Kind}


class JobError(Exception):
    pass


def enqueue(*, kind: str, competition_id: int, user=None, payload: dict | None = None):
    """入队；同类型同比赛已有待执行/执行中的任务时直接复用（防重复点击）。"""
    if kind not in SUPPORTED_KINDS:
        raise JobError(f'不支持的任务类型：{kind}')
    existing = (BackgroundJob.objects.using('default')
                .filter(kind=kind, competition_id=competition_id,
                        status__in=[BackgroundJob.Status.PENDING,
                                    BackgroundJob.Status.RUNNING])
                .order_by('-id').first())
    if existing is not None:
        return existing
    return BackgroundJob.objects.using('default').create(
        kind=kind, competition_id=competition_id,
        payload=payload or {},
        created_by=getattr(user, 'id', None),
        created_by_username=getattr(user, 'username', ''),
    )


def serialize(job: BackgroundJob) -> dict:
    return {
        'id': job.id,
        'kind': job.kind,
        'kindLabel': job.get_kind_display(),
        'status': job.status,
        'statusLabel': job.get_status_display(),
        'progress': job.progress,
        'message': job.message,
        'result': job.result,
        'error': job.error,
        'createdAt': job.created_at.isoformat(),
        'startedAt': job.started_at.isoformat() if job.started_at else None,
        'finishedAt': job.finished_at.isoformat() if job.finished_at else None,
    }


def _run_settlement(job: BackgroundJob) -> dict:
    from apps.competition.settlement import services as settlement_services

    job.progress = 30
    job.message = '正在计算得分'
    job.save(update_fields=['progress', 'message'])
    from apps.global_.competitions.models import Competition

    competition = Competition.objects.using('default').get(pk=job.competition_id)
    run = settlement_services.run_settlement(competition=competition)
    return {'runId': run.id, 'entries': len((run.result or {}).get('entries') or [])}


def _run_fiscal_open(job: BackgroundJob) -> dict:
    from apps.competition.fiscal import services as fiscal_services

    job.progress = 30
    job.message = '正在开启财年并跑定时器'
    job.save(update_fields=['progress', 'message'])
    year = fiscal_services.open_fiscal_year(user=None)
    return {'fiscalYearId': year.id, 'year': year.year}


def _run_fiscal_close(job: BackgroundJob) -> dict:
    from apps.competition.fiscal import services as fiscal_services

    job.progress = 30
    job.message = '正在结束财年并备份'
    job.save(update_fields=['progress', 'message'])
    year = fiscal_services.close_fiscal_year(user=None)
    return {'fiscalYearId': year.id, 'year': year.year}


def _run_package_import(job: BackgroundJob) -> dict:
    """后台导入比赛包：zip 已落盘（packages/pending/），这里跑完整导入流程。"""
    from django.core.files.storage import default_storage

    from apps.global_.competitions.models import Competition
    from apps.global_.packages import importer

    stored = str((job.payload or {}).get('storedPath') or '')
    file_name = str((job.payload or {}).get('fileName') or 'package.zip')
    if not stored or not default_storage.exists(stored):
        raise JobError('待导入的比赛包文件已不存在')

    job.progress = 20
    job.message = '正在解析与建库'
    job.save(update_fields=['progress', 'message'])

    from django.contrib.auth import get_user_model

    user = None
    if job.created_by:
        user = get_user_model().objects.using('default').filter(pk=job.created_by).first()
    competition = Competition.objects.using('default').get(pk=job.competition_id)
    zip_path = default_storage.path(stored)
    try:
        package = importer.import_package(
            competition=competition, zip_path=zip_path, file_name=file_name, user=user)
    finally:
        try:
            default_storage.delete(stored)
        except Exception:  # noqa: BLE001 —— 清理失败不影响导入结果
            pass
    return {'packageId': package.id, 'status': package.status}


HANDLERS = {
    BackgroundJob.Kind.SETTLEMENT: _run_settlement,
    BackgroundJob.Kind.FISCAL_OPEN: _run_fiscal_open,
    BackgroundJob.Kind.FISCAL_CLOSE: _run_fiscal_close,
    BackgroundJob.Kind.PACKAGE_IMPORT: _run_package_import,
}


def run_job(job: BackgroundJob) -> BackgroundJob:
    """执行单个任务：状态、进度、结果、错误全部落库。"""
    from apps.common import context as ctx
    from apps.global_.competitions.models import Competition
    from BusinessCompetitionManagerWeb.settings.databases import register_competition_db

    job.status = BackgroundJob.Status.RUNNING
    job.started_at = timezone.now()
    job.progress = 10
    job.message = '准备执行'
    job.save(update_fields=['status', 'started_at', 'progress', 'message'])

    competition = Competition.objects.using('default').filter(pk=job.competition_id).first()
    if competition is None:
        job.status = BackgroundJob.Status.FAILED
        job.error = '比赛不存在'
        job.finished_at = timezone.now()
        job.save(update_fields=['status', 'error', 'finished_at'])
        return job

    try:
        register_competition_db(competition.db_name)
        ctx.set_competition_context(competition.id, competition.db_name)
        handler = HANDLERS.get(job.kind)
        if handler is None:
            raise JobError(f'未实现的任务类型：{job.kind}')
        result = handler(job)
        job.result = result or {}
        job.status = BackgroundJob.Status.SUCCESS
        job.progress = 100
        job.message = '已完成'
    except Exception as exc:  # noqa: BLE001 —— 任务失败要落库，不冒泡
        job.status = BackgroundJob.Status.FAILED
        job.error = f'{type(exc).__name__}: {exc}'
        job.message = '执行失败'
    finally:
        job.finished_at = timezone.now()
        job.save(update_fields=['status', 'progress', 'message', 'result', 'error',
                                'finished_at'])
        ctx.clear_request_context()
    return job


def run_pending(*, limit: int = 5) -> list:
    """取一批待执行任务顺序跑（worker 命令调用）。"""
    jobs = list(BackgroundJob.objects.using('default')
                .filter(status=BackgroundJob.Status.PENDING)
                .order_by('id')[:limit])
    return [run_job(job) for job in jobs]
