"""账本重演单元测试（查账同步语义，需求方场景）：

合同一 cash -200（1000→800）→ 合同二 cash -200（当时 800→600）；
修改合同一为 -100 后，重演链自动变为 合同一 1000→900、合同二 900→700（当时值保留审计）。
"""

from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.competition.contracts import ledger


class FakeEffect:
    _seq = 0

    def __init__(self, contract, op, value, before, after, round_no):
        FakeEffect._seq += 1
        self.id = FakeEffect._seq
        self.contract = contract
        self.contract_id = contract.id
        self.company_id = 1
        self.field_key = 'cash'
        self.op = op
        self.value_raw = value
        self.before_raw = before
        self.after_raw = after
        self.round_no = round_no
        self.created_at = None


class LedgerReplayTests(SimpleTestCase):
    """链重放：生效轮次重算、已回滚轮次排除、上游修改后下游自动重算。"""

    def _patch_chain(self, rows):
        return lambda *args: rows

    def test_downstream_replay_updates_after_upstream_modify(self):
        # 修改后的生效链：合同一(第1轮) 1000→900，合同二(第0轮) 当时 800→600
        c1 = SimpleNamespace(id=1, name='合同一', unified_number='PO-1', round_no=1)
        c2 = SimpleNamespace(id=2, name='合同二', unified_number='PO-2', round_no=0)
        rows = [
            FakeEffect(c1, 'SUB', 100, 1000, 900, 1),   # 合同一修改后的新效果（链位在前）
            FakeEffect(c2, 'SUB', 200, 800, 600, 0),    # 合同二当时效果（未改）
        ]
        # 编号顺序 = 合同一 → 合同二（_chain_rows 由 ORM 排序，这里直接喂给重放逻辑）
        original = ledger._chain_rows
        ledger._chain_rows = self._patch_chain(rows)
        try:
            chain = ledger.field_chain(1, 'cash')
        finally:
            ledger._chain_rows = original

        self.assertEqual(chain['initialValue'], 1000)
        self.assertEqual(len(chain['nodes']), 2)
        # 合同一：重演=当时（自身刚重落账）
        self.assertEqual(chain['nodes'][0]['replayBefore'], 1000)
        self.assertEqual(chain['nodes'][0]['replayAfter'], 900)
        # 合同二：**重演自动同步**（800→600 的当时值保留，但重演为 900→700）
        self.assertEqual(chain['nodes'][1]['auditBefore'], 800)
        self.assertEqual(chain['nodes'][1]['auditAfter'], 600)
        self.assertEqual(chain['nodes'][1]['replayBefore'], 900)
        self.assertEqual(chain['nodes'][1]['replayAfter'], 700)
        self.assertEqual(chain['currentValue'], 700)

    def test_rolled_back_rounds_excluded_from_chain(self):
        c1 = SimpleNamespace(id=1, name='合同一', unified_number='PO-1', round_no=1)
        old = FakeEffect(c1, 'SUB', 200, 1000, 800, 0)   # 旧轮（已回滚）不应进链
        new = FakeEffect(c1, 'SUB', 100, 1000, 900, 1)   # 新轮
        original = ledger._chain_rows
        ledger._chain_rows = self._patch_chain([e for e in (old, new) if e.round_no == e.contract.round_no])
        try:
            chain = ledger.field_chain(1, 'cash')
        finally:
            ledger._chain_rows = original
        self.assertEqual(len(chain['nodes']), 1)
        self.assertEqual(chain['nodes'][0]['replayAfter'], 900)
