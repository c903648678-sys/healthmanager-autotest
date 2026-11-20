"""CLI adapters. All prompts use stdin, never a shell command string."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import re

from .contracts import SCHEMA


class ProviderError(RuntimeError):
    pass


def executable(provider):
    override = os.environ.get(f"WORKBENCH_{provider.upper()}_BIN")
    found = override or shutil.which(provider)
    if found and Path(found).is_file():
        # Native binaries avoid cmd.exe interpolation of JSON/schema flags on Windows.
        if os.name == "nt" and Path(found).suffix.lower() != ".exe":
            return None
        return str(Path(found).resolve())
    return None


class CodexProvider:
    id = "codex"

    def command(self, binary, folder, model, schema=None):
        args = [binary, "--no-daemon", "-a", "never", "exec", "--ignore-user-config",
                "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only",
                "--json", "--color", "never", "--output-schema", str(folder / "schema.json"),
                "--output-last-message", str(folder / "result.json"),
                "-c", "project_doc_max_bytes=0", "-c", 'web_search="disabled"']
        for flag in ("shell_tool", "unified_exec", "apps", "hooks", "multi_agent", "browser_use", "computer_use", "image_generation"):
            args.extend(["--disable", flag])
        if model:
            args.extend(["--model", model])
        return args + ["-"]

    def result(self, folder):
        return json.loads((folder / "result.json").read_text(encoding="utf-8"))


class ClaudeProvider:
    id = "claude"

    def command(self, binary, folder, model, schema=None):
        args = [binary, "--safe-mode", "-p", "--tools", "", "--disallowedTools", "mcp__*",
                "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--no-session-persistence", "--output-format", "json",
                "--json-schema", json.dumps(schema or SCHEMA, separators=(",", ":")), "--max-turns", "3"]
        if model:
            args.extend(["--model", model])
        return args

    def result(self, folder):
        envelope = json.loads((folder / "stdout.log").read_text(encoding="utf-8"))
        if envelope.get("is_error") or envelope.get("subtype") not in (None, "success"):
            raise ProviderError("Claude 返回失败，检查本机登录、额度、模型及 CLI 版本")
        if not isinstance(envelope.get("structured_output"), dict):
            raise ProviderError("Claude 未返回 structured_output，请检查版本与结构化输出支持")
        return envelope["structured_output"]


PROVIDERS = {p.id: p for p in (CodexProvider(), ClaudeProvider())}


def stop_process(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=10)
    else:
        os.killpg(proc.pid, signal.SIGKILL)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


class ProgressReader:
    """Tail CLI output without forwarding prompts, credentials or reasoning text."""
    def __init__(self, folder, provider, report):
        self.folder, self.provider, self.report = folder, provider, report
        self.offsets = {"stdout.log": 0, "stderr.log": 0}
        self.buffers = {name: b"" for name in self.offsets}

    def consume(self, name, line):
        if name == "stdout.log" and self.provider == "codex":
            try:
                event = json.loads(line)
            except ValueError:
                return
            if not isinstance(event, dict):
                return
            kind = event.get("type")
            if kind == "thread.started":
                self.report("connecting", "Codex 会话已启动，正在连接模型")
            elif kind == "turn.started":
                self.report("waiting", "分析请求已启动，等待模型响应")
            elif kind == "turn.completed":
                self.report("receiving", "模型已完成回复，正在读取结构化结果")
            elif kind in ("item.started", "item.completed"):
                item = event.get("item", {})
                if not isinstance(item, dict):
                    return
                if item.get("type") == "agent_message":
                    self.report("receiving", "已收到模型回复，正在整理结果")
                elif item.get("type") == "reasoning":
                    self.report("analyzing", "收到模型处理事件，分析进行中")
                elif item.get("type") == "error":
                    self.network_message(str(item.get("message", "")))
            elif kind == "error":
                self.network_message(str(event.get("message", "")))
        elif name == "stderr.log":
            self.network_message(line)

    def network_message(self, text):
        lower = text.lower()
        if "falling back" in lower and ("http" in lower or "websocket" in lower):
            self.report("reconnecting", "连接不稳定，CLI 正在切换到 HTTPS 通道")
        elif "reconnect" in lower or "retrying sampling" in lower:
            match = re.search(r"(\d+)\s*/\s*(\d+)", text)
            count = f"（{match[1]}/{match[2]}）" if match else ""
            self.report("reconnecting", "模型连接中断，CLI 正在重试" + count)
        elif "timed out" in lower or "timeout" in lower:
            self.report("reconnecting", "模型连接超时，等待 CLI 恢复连接")

    def poll(self):
        for name in self.offsets:
            with (self.folder / name).open("rb") as stream:
                stream.seek(self.offsets[name])
                chunk = stream.read(1024 * 1024)
                self.offsets[name] = stream.tell()
            lines = (self.buffers[name] + chunk).split(b"\n")
            self.buffers[name] = lines.pop()[-1024 * 1024:]
            for line in lines:
                self.consume(name, line.decode("utf-8", errors="replace"))


def run_provider(provider_id, model, prompt, folder, cancelled, timeout=180, progress=None, schema=None):
    report = progress or (lambda stage, message: None)
    provider = PROVIDERS[provider_id]
    binary = executable(provider_id)
    if not binary:
        raise ProviderError(f"未找到 {provider_id} 原生可执行程序，请安装并登录，或设置 WORKBENCH_{provider_id.upper()}_BIN")
    (folder / "schema.json").write_text(json.dumps(schema or SCHEMA, ensure_ascii=False), encoding="utf-8")
    (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
    args = provider.command(binary, folder, model, schema)
    report("starting", f"正在启动 {provider_id} 本机进程")
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    with (folder / "prompt.txt").open("rb") as inp, (folder / "stdout.log").open("wb") as out, (folder / "stderr.log").open("wb") as err:
        proc = subprocess.Popen(args, cwd=folder, stdin=inp, stdout=out, stderr=err, shell=False, **options)
        start = time.monotonic()
        heartbeat = start
        reader = ProgressReader(folder, provider_id, report)
        report("waiting", "进程已启动，等待模型响应；无事件时每15秒报告存活状态")
        try:
            while proc.poll() is None:
                reader.poll()
                if cancelled.is_set():
                    raise ProviderError("已取消分析")
                if time.monotonic() - start > timeout:
                    raise ProviderError(f"分析超过 {timeout} 秒，已停止；可缩小资料范围后重试")
                if sum((folder / name).stat().st_size for name in ("stdout.log", "stderr.log")) > 8 * 1024 * 1024:
                    raise ProviderError("模型输出超限，已停止")
                if time.monotonic() - heartbeat >= 15:
                    elapsed = int(time.monotonic() - start)
                    report("heartbeat", f"进程仍在运行，已等待 {elapsed} 秒（单次上限 {timeout} 秒）；这不是模型完成百分比")
                    heartbeat = time.monotonic()
                cancelled.wait(0.2)
            reader.poll()
            if cancelled.is_set():
                raise ProviderError("已取消分析")
            if proc.returncode:
                raise ProviderError(f"{provider_id} 调用失败（退出码 {proc.returncode}）；请检查本机登录、网络、额度和 CLI 版本")
        finally:
            stop_process(proc)
    try:
        report("receiving", "进程已结束，正在读取最终结果")
        if any(p.stat().st_size > 8 * 1024 * 1024 for p in folder.iterdir() if p.name in ("stdout.log", "stderr.log", "result.json")):
            raise ProviderError("模型输出超限，候选未进入审阅")
        return provider.result(folder)
    except (OSError, ValueError) as exc:
        raise ProviderError("模型未返回有效 JSON；结果未进入审阅") from exc
