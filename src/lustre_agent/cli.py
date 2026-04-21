import typer
from .llm import get_llm

app = typer.Typer(help="Lustre Agent CLI")


@app.command()
def hello():
    """最小 LLM 调用演示"""
    llm = get_llm()
    response = llm.invoke("Say hi in one sentence")
    typer.echo(response.content)


@app.command()
def version():
    """显示版本信息"""
    typer.echo("lustre-agent 0.1.0")


if __name__ == "__main__":
    app()
