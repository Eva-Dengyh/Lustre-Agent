---
appendix: D
title: "Docker 化与代码执行沙箱"
status: draft
est_minutes: 120
depends_on: [day7]
---

# Appendix D · Docker 化与代码执行沙箱

> 让 Lustre-Agent 可以容器化分发，且让 Coder 写出的代码在隔离容器里跑——别把宿主机搞坏。

## 0. 30 秒速览

- **为什么**：Day 3 的 `run_shell` 只是白名单+超时，离"安全"还差很远；Coder 生成的代码（尤其 demo FastAPI）也最好别污染本地环境
- **做什么**：
  1. 给 Lustre-Agent 自身做 `Dockerfile` + `docker compose up` 的运行方式
  2. 把 `run_shell` 升级为 `run_in_sandbox`，在一次性 Docker 容器内跑命令
- **不做什么**：不做 Kubernetes、不做 GPU；只做单机最小化沙箱

## 1. 概念

- **Image vs Container**：build 出 image，run 出 container；沙箱模式 = 每次任务起一个新 container
- **Bind mount**：把宿主项目目录挂到容器里，让 agent 改的代码能持久化
- **网络隔离**：`--network=none` 或自定义 network；防止 agent 偷偷请求外网
- **资源上限**：`--memory=512m --cpus=1`；防止失控

## 2. 前置条件

- 已完成 Day 7
- 宿主装好 Docker
- 新增依赖：Python 端 `docker`（或直接 subprocess 调 `docker` CLI，更简单）

## 3. 目标产物

```tree
Dockerfile                   ← 新增（Lustre-Agent 本体镜像）
docker-compose.yml           ← 新增
sandbox.Dockerfile           ← 新增（执行沙箱镜像，最小 python + pytest）
src/lustre_agent/
├── tools/
│   └── sandbox.py           ← 新增：run_in_sandbox 工具
├── config.py                ← 修改：LUSTRE_SANDBOX = "shell"|"docker"
docs/
└── appendix-d-docker.md     ← 本文
tests/
└── appendix_d_smoke.py      ← 新增（需要 docker 才跑）
```

## 4. 实现步骤

### Step 1 — Lustre 本体镜像

- 基础镜像 `python:3.11-slim`
- `COPY pyproject.toml uv.lock . && uv sync --frozen`
- `ENTRYPOINT ["uv","run","lustre"]`
- `docker-compose.yml`：挂载 `.env` 与项目目录；交互模式 `tty: true`

### Step 2 — 沙箱镜像

- 同样 `python:3.11-slim`
- 预装 `pytest fastapi httpx`（demo 常用），其它按需 pip install
- 单独 build 一次：`docker build -f sandbox.Dockerfile -t lustre-sandbox:0.1 .`

### Step 3 — `run_in_sandbox` 工具

```python
@tool
def run_in_sandbox(cmd: str, timeout: int = 60) -> dict:
    """在隔离容器内执行命令，返回 {returncode, stdout, stderr}"""
    # docker run --rm --network=none --memory=512m --cpus=1 \
    #   -v <project>:/work -w /work lustre-sandbox:0.1 sh -c "<cmd>"
```

### Step 4 — 配置开关

- `LUSTRE_SANDBOX=docker` 时，把 `run_shell` 替换为 `run_in_sandbox`
- 默认 `shell`（向后兼容；CI 环境可能没 docker）

### Step 5 — Reviewer 也走沙箱

- `pytest_runner` 同样支持 sandbox 模式

## 5. 关键代码骨架

```dockerfile
# Dockerfile
FROM python:3.11-slim
RUN pip install uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen
COPY . .
ENTRYPOINT ["uv","run","lustre"]
```

```yaml
# docker-compose.yml
services:
  lustre:
    build: .
    env_file: .env
    volumes:
      - .:/app
      - /var/run/docker.sock:/var/run/docker.sock   # 让容器内的 lustre 也能拉沙箱
    stdin_open: true
    tty: true
```

```python
# src/lustre_agent/tools/sandbox.py
import subprocess, shlex
def run_in_sandbox(cmd: str, timeout=60) -> dict:
    args = ["docker","run","--rm","--network=none","--memory=512m","--cpus=1",
            "-v",f"{os.getcwd()}:/work","-w","/work","lustre-sandbox:0.1","sh","-c",cmd]
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    return {"returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr}
```

## 6. 验收

```bash
docker build -t lustre:0.1 .
docker build -f sandbox.Dockerfile -t lustre-sandbox:0.1 .

# 方式 A：直接 compose
docker compose run --rm lustre
> /code 写一个 add 函数并测试

# 方式 B：本地 lustre + 沙箱 run
LUSTRE_SANDBOX=docker uv run lustre
> /code 同上
# 观察：tests 是在沙箱容器里跑的（可在另一终端 `docker ps` 看到短暂容器）
```

自动：`uv run pytest tests/appendix_d_smoke.py -v -m docker`（需 docker）

## 7. 常见坑

- 容器内访问宿主 docker：要么挂 socket（强权限），要么用 sysbox / docker-in-docker
- 性能：每个命令都起一次容器有冷启动；如需高频可考虑长生命周期容器 + `docker exec`
- 安全：`--network=none` 默认拒绝；如果 agent 任务需要访问外部 API，请用专用 network + allowlist
- macOS 上 bind mount 性能差：可用 `:cached` 或 mutagen 加速
