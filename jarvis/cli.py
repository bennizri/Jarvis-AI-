import json
import subprocess

from .config import CONFIG


def parse_json_array(stdout: str) -> list | None:
    """claude --output-format json stdout -> list, None if unparseable."""
    try:
        result = json.loads(stdout).get("result", "")
    except json.JSONDecodeError:
        return None
    text = result.strip()
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    try:
        items = json.loads(text)
    except json.JSONDecodeError:
        return None
    return items if isinstance(items, list) else None


def run_json_prompt(prompt: str, timeout: int = 180) -> list | None:
    """Headless claude call (cheap model) that must answer with a JSON array."""
    try:
        res = subprocess.run(
            ["claude", "-p", prompt, "--model", CONFIG.fleet_model,
             "--output-format", "json"],
            capture_output=True, text=True, timeout=timeout,
            cwd=CONFIG.working_dir)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return parse_json_array(res.stdout) if res.returncode == 0 else None
