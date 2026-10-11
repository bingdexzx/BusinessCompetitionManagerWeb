"""比赛生命周期状态机单测（§10.1）。"""

from django.test import TestCase

from apps.global_.competitions.models import Competition


class CompetitionStateMachineTests(TestCase):
    def test_legal_chain(self):
        c = Competition.objects.create(name='x')
        self.assertEqual(c.status, Competition.Status.CREATED)
        chain = [
            Competition.Status.PACKAGE_IMPORTED,
            Competition.Status.ENROLLING,
            Competition.Status.RUNNING,
            Competition.Status.SETTLING,
            Competition.Status.CLOSED,
        ]
        for target in chain:
            c.transition_to(target)
            self.assertEqual(c.status, target)

    def test_illegal_transition_rejected(self):
        c = Competition.objects.create(name='y')
        with self.assertRaises(ValueError):
            c.transition_to(Competition.Status.RUNNING)
        self.assertEqual(c.status, Competition.Status.CREATED)

    def test_no_backward_transition(self):
        c = Competition.objects.create(name='z')
        c.transition_to(Competition.Status.PACKAGE_IMPORTED)
        with self.assertRaises(ValueError):
            c.transition_to(Competition.Status.CREATED)
