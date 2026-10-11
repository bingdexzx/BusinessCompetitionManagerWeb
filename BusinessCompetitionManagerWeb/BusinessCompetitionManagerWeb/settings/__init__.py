"""项目配置包。

按重构方案 §5.3「settings 按 global/competition 拆分」：

- ``base.py``：全局域配置（应用、中间件、认证、日志等公共部分）；
- ``databases.py``：数据库拓扑（全局库 + 动态比赛库注册表）与多库路由入口。
"""

from .base import *  # noqa: F401,F403
from .databases import *  # noqa: F401,F403
