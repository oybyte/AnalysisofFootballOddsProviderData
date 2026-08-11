"""Knowledge Engine V2 — 隔离式知识引擎子系统。

该包通过 ports/adapters 架构读取现有权威数据，先作为只读旁路运行，
达到前瞻验证门槛后替换正式草稿决策来源。

依赖规则:
- domain/ 只依赖标准库、Pydantic 和同层领域类型。
- application/ 只依赖 domain/ 与 ports/。
- ports/ 只定义 Protocol、输入输出契约和领域异常。
- 只有 adapters/ 可以导入现有 observations、facts、cases、rules、AI governance、
  MatchDocument 和 RepositoryTransaction。
"""

__version__ = "2.0.0"