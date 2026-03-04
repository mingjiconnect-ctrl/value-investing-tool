from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader


def render_report(context: dict, output_path: str) -> None:
    env = Environment(loader=FileSystemLoader("src/reporting/templates"))
    template = env.get_template("report.md.jinja")
    content = template.render(**context)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(content, encoding="utf-8")
