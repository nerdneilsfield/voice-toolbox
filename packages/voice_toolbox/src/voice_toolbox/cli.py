import typer

app = typer.Typer(help="Voice Toolbox")


@app.callback()
def main() -> None:
    """Run Voice Toolbox commands."""
