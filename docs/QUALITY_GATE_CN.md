# 质量门禁

提交代码前运行：

```bash
PYTHON_BIN=.venv/bin/python bash scripts/quality_gate.sh
```

门禁依次检查依赖一致性、Django 配置、迁移漂移、生产安全配置和完整测试集。
GitHub Actions 会在 `main` 分支推送和所有 Pull Request 上执行相同流程。

安全扫描单独运行：

```bash
PYTHON_BIN=.venv/bin/python bash scripts/security_scan.sh
```

该脚本执行 Bandit 静态安全扫描和 `pip-audit` 依赖漏洞扫描。GitHub Actions 还会运行 CodeQL，Dependabot 每周检查 pip、GitHub Actions 和 Docker 依赖更新。

发布前检查：

```bash
PYTHON_BIN=.venv/bin/python bash scripts/deploy_check.sh
```

生产检查会验证数据库防误配、敏感字段密钥、超级管理员 MFA、指标端点保护、直传对象存储配置和 Celery Broker 地址。部署流水线还应在迁移前创建并校验数据库备份，迁移后执行 `rebuild_search_index`，发布后检查 `/readyz`。
