"""重命名超长索引名（models.E034：索引名 ≤30 字符）。

原 idx_stock_funds_accounts_updated（32）/ idx_stock_funds_accounts_owner（31）
超限，改为 idx_stock_funds_acc_updated / idx_stock_funds_acc_owner。
RenameIndex 对新建库与存量库都安全（0001 建旧名 → 0002 改名）。
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('stock', '0001_initial'),
    ]

    operations = [
        migrations.RenameIndex(
            model_name='stockfundsaccount',
            new_name='idx_stock_funds_acc_updated',
            old_name='idx_stock_funds_accounts_updated',
        ),
        migrations.RenameIndex(
            model_name='stockfundsaccount',
            new_name='idx_stock_funds_acc_owner',
            old_name='idx_stock_funds_accounts_owner',
        ),
    ]
