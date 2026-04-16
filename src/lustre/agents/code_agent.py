"""CodeAgent — a real LLM-powered code generation specialist.

Phase 4: replaces EchoAgent with actual LLM calls via ReAct executor.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from lustre.agents.base import AgentConfig, SpecialistAgent
from lustre.bus.message import TaskRequest, TaskResult
from lustre.models.client import ChatMessage, create_client
from lustre.models.executor import ReActExecutor
from lustre.tools.builtin import get_builtin_tools

if TYPE_CHECKING:
    from lustre.bus.base import MessageBus

logger = logging.getLogger(__name__)


class CodeAgent(SpecialistAgent):
    """A specialist agent that generates and writes code using an LLM.

    Uses the ReAct (Reason + Act + Observe) pattern to:
    1. Understand the coding task
    2. Write files, run commands, search codebases
    3. Verify results until the task is complete

    The agent is given these built-in tools:
    - read_file / write_file / patch  — file operations
    - terminal                         — run shell commands
    - search_files                     — grep and glob
    """

    def __init__(
        self,
        config: AgentConfig,
        bus: "MessageBus",
        *,
        system_prompt: str | None = None,
    ) -> None:
        super().__init__(config=config, bus=bus)

        # Build LLM client from config
        provider = config.model_provider or "anthropic"
        api_key = config.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._client = create_client(provider, api_key=api_key)
        self._model = config.model_name or "claude-sonnet-4-6"

        # System prompt
        self._system_prompt = system_prompt or _DEFAULT_CODE_AGENT_PROMPT

        # ReAct executor with built-in tools
        tools = get_builtin_tools()
        self._executor = ReActExecutor(
            client=self._client,
            system_prompt=self._system_prompt,
            tools=tools,
            max_iterations=20,
            model=self._model,
            temperature=0.0,
        )

    # ------------------------------------------------------------------
    # SpecialistAgent contract
    # ------------------------------------------------------------------

    def process_task(self, task: TaskRequest) -> TaskResult:
        """Run the ReAct loop to complete the coding task."""
        logger.info(
            "CodeAgent processing task %s: %s",
            task.task_id,
            task.description[:80],
        )

        # Build context string for the executor
        context_parts = [f"# 任务描述\n{task.description}"]
        if task.context:
            context_parts.append("\n# 上下文信息")
            for k, v in task.context.items():
                if k == "all_steps":
                    context_parts.append(f"\n## 完整计划\n{v}")
                else:
                    context_parts.append(f"\n- {k}: {v}")

        context = "\n".join(context_parts)

        try:
            answer, trace = self._executor.execute(
                task=context,
                task_id=task.task_id,
            )
            logger.info(
                "CodeAgent task %s completed in %d trace steps",
                task.task_id,
                len(trace.steps),
            )
            return TaskResult(
                task_id=task.task_id,
                status="completed",
                output=answer,
                artifacts={},
                agent_name=self.name,
            )
        except Exception as exc:
            logger.exception("CodeAgent task %s failed", task.task_id)
            return TaskResult(
                task_id=task.task_id,
                status="failed",
                error=str(exc),
                agent_name=self.name,
            )


# ---------------------------------------------------------------------------
# Default system prompt for code agents
# ---------------------------------------------------------------------------

_DEFAULT_CODE_AGENT_PROMPT = """你是一个专业的 Python 编程助手。

你的职责是根据用户的需求编写高质量的 Python 代码。

工作方式（ReAct 循环）：
1. 理解任务 — 仔细阅读任务描述，理解用户想要什么
2. 规划步骤 — 决定需要创建/修改哪些文件
3. 行动 — 使用工具创建或修改文件、运行测试命令等
4. 观察 — 检查工具返回的结果
5. 迭代 — 根据观察结果调整代码，直到任务完成

你拥有以下工具：
- read_file(path) — 读取文件内容
- write_file(path, content) — 写入完整文件（会覆盖！）
- patch(path, old_string, new_string) — 精确替换文件中的一小段文字
- terminal(command, timeout?) — 执行 Shell 命令
- search_files(pattern, target, path?, file_glob?, limit?) — 搜索文件或内容

重要原则：
- 先了解项目结构和现有代码再动手
- patch 工具要求 old_string 和 new_string 同时提供，且 old_string 必须精确匹配（包括空白字符）
- 写完代码后运行测试验证正确性
- 保持代码简洁、可读、符合 PEP 8
- 如果任务不明确，先描述你的理解再开始

最终回答应该清楚说明：
1. 你创建/修改了哪些文件
2. 关键的设计决策
3. 如何运行和测试
""".strip()
