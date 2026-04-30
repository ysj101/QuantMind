"""ローカル Claude Code / Codex CLI を subprocess 駆動する抽象層.

API キーに依存せず、ユーザーがローカルにインストールした CLI を呼び出す。
"""

from __future__ import annotations

import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from quantmind.storage import get_conn

DEFAULT_TIMEOUT = 180  # 秒


class LLMRunError(RuntimeError):
    """LLM 実行が失敗したことを示す例外."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    raw_stdout: str
    raw_stderr: str
    duration_sec: float


class LLMRunner(Protocol):
    """Bull/Bear/Judge 等で使う LLM 実行抽象."""

    name: str

    def run(self, system_prompt: str, user_prompt: str, timeout: int = DEFAULT_TIMEOUT) -> LLMResponse:
        ...


def _run_subprocess(cmd: list[str], stdin_text: str, timeout: int) -> tuple[str, str, float]:
    started = datetime.now()
    try:
        proc = subprocess.run(
            cmd,
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as e:
        raise LLMRunError(f"CLI が見つかりません: {cmd[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise LLMRunError(f"LLM 実行がタイムアウト ({timeout}s)") from e
    duration = (datetime.now() - started).total_seconds()
    if proc.returncode != 0:
        raise LLMRunError(
            f"LLM 実行失敗 rc={proc.returncode} stderr={proc.stderr.strip()[:500]}"
        )
    return proc.stdout, proc.stderr, duration


class _SubprocessRunner:
    """共通の subprocess 起動ロジック."""

    name: str = "subprocess"
    cli_name: str = ""

    def __init__(
        self,
        cli_path: str | None = None,
        extra_args: list[str] | None = None,
        model_label: str | None = None,
    ) -> None:
        self.cli_path = cli_path or shutil.which(self.cli_name) or self.cli_name
        self.extra_args = list(extra_args or [])
        self.model_label = model_label or self.name

    def _build_command(self) -> list[str]:
        return [self.cli_path, *self.extra_args]

    def _format_input(self, system_prompt: str, user_prompt: str) -> str:
        # 多くの CLI は stdin に入った文字列をプロンプトとして扱う。
        # システムプロンプトは "System: ... \n\nUser: ..." 形式で同梱する。
        return f"System: {system_prompt}\n\nUser: {user_prompt}\n"

    def run(
        self, system_prompt: str, user_prompt: str, timeout: int = DEFAULT_TIMEOUT
    ) -> LLMResponse:
        cmd = self._build_command()
        stdin_text = self._format_input(system_prompt, user_prompt)
        stdout, stderr, dur = _run_subprocess(cmd, stdin_text, timeout)
        return LLMResponse(
            text=stdout.strip(),
            model=self.model_label,
            raw_stdout=stdout,
            raw_stderr=stderr,
            duration_sec=dur,
        )


class ClaudeCodeRunner(_SubprocessRunner):
    """ローカル `claude` CLI ラッパ."""

    name = "claude_code"
    cli_name = "claude"

    def __init__(self, cli_path: str | None = None, extra_args: list[str] | None = None) -> None:
        # Claude CLI は対話モード以外で stdin → 出力を返す `--print` 系オプションを想定。
        super().__init__(
            cli_path=cli_path,
            extra_args=extra_args if extra_args is not None else ["--print"],
            model_label="claude_code",
        )


class CodexRunner(_SubprocessRunner):
    """ローカル `codex` CLI ラッパ."""

    name = "codex"
    cli_name = "codex"

    def __init__(self, cli_path: str | None = None, extra_args: list[str] | None = None) -> None:
        super().__init__(
            cli_path=cli_path,
            extra_args=extra_args if extra_args is not None else ["exec", "-"],
            model_label="codex",
        )


def log_decision(
    *,
    code: str | None,
    role: str,
    response: LLMResponse,
    prompt: str,
    confidence: float | None = None,
    as_of: date | None = None,
    decision_id: str | None = None,
) -> str:
    """llm_decisions テーブルに保存."""
    did = decision_id or str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO llm_decisions(id, code, as_of_date, role, model, prompt, output, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [did, code, as_of, role, response.model, prompt, response.text, confidence],
        )
    return did


def write_log_file(directory: Path, role: str, code: str | None, response: LLMResponse) -> Path:
    """補助: 実行ログをファイルにも残す."""
    directory.mkdir(parents=True, exist_ok=True)
    fname = directory / f"{datetime.now():%Y%m%d-%H%M%S}-{role}-{code or 'na'}.txt"
    fname.write_text(response.text, encoding="utf-8")
    return fname
