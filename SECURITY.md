# Security Policy

[简体中文](#安全策略)

## Supported versions

| Version | Supported |
|---------|-----------|
| 2.3.x   | ✅        |
| 2.2.x   | ⚠️ security fixes only |
| 2.1.x   | ⚠️ security fixes only |
| 2.0.x   | ⚠️ security fixes only |
| 1.0.x   | ⚠️ security fixes only |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately through GitHub's
[private vulnerability reporting](https://github.com/jiangqingliu88/langchaingraph_cdv/security/advisories/new)
or contact the maintainer [@jiangqingliu88](https://github.com/jiangqingliu88).

Please include:

- A description of the issue and its impact
- Steps to reproduce (a minimal example if possible)
- Affected version / commit and your environment
- Any suggested mitigation

You can expect an initial acknowledgement within 7 days and a status update
within 30 days. We will credit reporters in the advisory unless you prefer to
remain anonymous.

## Scope

SignOffAI orchestrates LLM calls, shell commands, and EDA tools. Security-relevant
areas include, but are not limited to:

- Command injection or path traversal in tool execution and regression runners
- Sandbox/approval bypasses in the LangGraph governance and approval nodes
- Credential leakage in logs, evidence archives, or generated reports
- Prompt-injection paths that can cause unsafe tool invocation
- Authentication/authorization flaws in the optional HTTP service

## Handling secrets

The current tree is scanned by `scripts/check_secrets.py` in CI. This does **not**
rewrite history: if a credential was committed before, assume it is compromised,
rotate it, and coordinate a `git filter-repo` history purge with maintainers.
Use `.env` (ignored by git) or environment variables, and start from
[`.env.example`](.env.example). `.jwt_secret` is generated locally and must not
be committed.

If you believe a secret was committed, rotate it immediately and open a private
report. Do not paste the secret value into a public issue.

---

## 安全策略

### 报告漏洞

**请勿通过公开 Issue 报告安全问题。** 请使用 GitHub 的
[私密漏洞报告](https://github.com/jiangqingliu88/langchaingraph_cdv/security/advisories/new)，
或私信维护者 [@jiangqingliu88](https://github.com/jiangqingliu88)。

请附上问题描述与影响、复现步骤、受影响版本/提交以及你的运行环境。我们会在
7 天内确认收到，并在 30 天内给出进展；默认在公告中致谢报告者（除非你要求匿名）。

### 范围

本项目会编排 LLM、Shell 命令与 EDA 工具，重点关注：命令注入/路径穿越、
治理与审批节点绕过、日志与证据包中的凭据泄露、提示词注入导致的危险工具调用，
以及可选 HTTP 服务的认证授权问题。

### 密钥处理

仓库不包含任何真实凭据。请使用 `.env`（已被 git 忽略）或环境变量，并从
[`.env.example`](.env.example) 开始配置。`.jwt_secret` 只在本地生成，不得提交。
如果怀疑密钥已泄露，请立即轮换并私密报告，切勿在公开 Issue 中粘贴密钥。
