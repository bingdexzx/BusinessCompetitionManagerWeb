"""多库路由单测（§5.2）：比赛域读写必须在比赛上下文中，迁移隔离正确。"""

from django.apps import apps
from django.test import SimpleTestCase

from apps.common import context as ctx
from apps.competition.routing import CompetitionDatabaseRouter

Company = apps.get_model('companies', 'Company')
User = apps.get_model('accounts', 'User')


class RouterTests(SimpleTestCase):
    def setUp(self):
        self.router = CompetitionDatabaseRouter()

    def tearDown(self):
        ctx.clear_request_context()

    def test_global_models_route_to_default(self):
        self.assertEqual(self.router.db_for_read(User), 'default')
        self.assertEqual(self.router.db_for_write(User), 'default')

    def test_competition_model_without_context_raises(self):
        with self.assertRaises(RuntimeError):
            self.router.db_for_read(Company)

    def test_competition_model_with_context(self):
        ctx.set_competition_context(1, 'comp_1')
        self.assertEqual(self.router.db_for_read(Company), 'comp_1')
        self.assertEqual(self.router.db_for_write(Company), 'comp_1')

    def test_migrate_isolation(self):
        self.assertFalse(self.router.allow_migrate('default', 'companies'))
        self.assertTrue(self.router.allow_migrate('comp_1', 'companies'))
        self.assertTrue(self.router.allow_migrate('default', 'accounts'))
        self.assertFalse(self.router.allow_migrate('comp_1', 'accounts'))

    def test_relation_same_domain_only(self):
        self.assertTrue(self.router.allow_relation(Company, Company))
        self.assertTrue(self.router.allow_relation(User, User))
        self.assertFalse(self.router.allow_relation(Company, User))
