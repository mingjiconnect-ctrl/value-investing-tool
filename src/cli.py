from __future__ import annotations

import typer

from src.pipelines.run_example import run_example

app = typer.Typer(help="Value Investing Research System CLI")


@app.command()
def run(example: bool = typer.Option(False, "--example", help="Run example end-to-end pipeline.")) -> None:
    if example:
        run_example()
        typer.echo("Example pipeline completed. Outputs generated in outputs/.")
    else:
        typer.echo("Use --example for now.")


if __name__ == "__main__":
    app()
