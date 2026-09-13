import typer
import httpx
import json
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from sage_cli.config import config

app = typer.Typer(
    name="sage",
    help="Sovereign On-Premise Agentic AI Workbench CLI",
    add_completion=False
)
console = Console()

@app.command()
def health():
    """Check the health of the SAGE backend."""
    console.print(f"Pinging SAGE backend at [bold blue]{config.backend_url}[/bold blue]...")
    try:
        response = httpx.get(f"{config.backend_url}/health", timeout=10.0)
        response.raise_for_status()
        data = response.json()
        
        status = data.get("status", "unknown")
        color = "green" if status == "ok" else "red"
        
        table = Table(title="System Health")
        table.add_column("Service", style="cyan")
        table.add_column("Status", style=color)
        
        for srv, val in data.get("services", {}).items():
            table.add_row(srv.capitalize(), str(val))
            
        console.print(table)
        
        models = data.get("models", [])
        if models:
            m_table = Table(title="Registered Models")
            m_table.add_column("ID", style="magenta")
            m_table.add_column("Name", style="blue")
            m_table.add_column("Capabilities", style="yellow")
            for m in models:
                m_table.add_row(m.get("id", ""), m.get("name", ""), ", ".join(m.get("capabilities", [])))
            console.print(m_table)
            
    except httpx.ConnectError:
        console.print(f"[bold red]Connection Error:[/bold red] Could not connect to backend at {config.backend_url}. Is the SAGE backend running?")
    except httpx.TimeoutException:
        console.print(f"[bold red]Timeout Error:[/bold red] Health check request to {config.backend_url} timed out.")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")

# NOTE: login command removed — SAGE is offline-focused and does not require
# authentication.  Re-add when JWT auth is re-enabled in the backend.

@app.command()
def ask(
    prompt: str = typer.Argument(..., help="Prompt/task for the SAGE agent"),
    profile: str = typer.Option("general", "--profile", "-p", help="Agent profile to use (analyst, coder, inspector, general)"),
    timeout: float = typer.Option(300.0, "--timeout", "-t", help="Timeout in seconds for agent execution (default: 300s)")
):
    """Submit a task to the SAGE Agent Core and view live step progress & trace."""
    console.print(Panel(f"[bold cyan]Task:[/bold cyan] {prompt}\n[bold yellow]Profile:[/bold yellow] {profile}", title="SAGE Agent Request"))

    url = f"{config.backend_url}/api/chat/completions"
    payload = {
        "prompt": prompt,
        "profile": profile
    }

    try:
        with console.status("[bold green]Executing Agent Task...[/bold green]"):
            resp = httpx.post(url, json=payload, timeout=timeout)
            if resp.status_code != 200:
                err_msg = resp.text
                try:
                    err_data = resp.json()
                    err_msg = err_data.get("error", {}).get("message") or err_data.get("detail") or err_msg
                except Exception:
                    pass
                console.print(Panel(
                    f"[bold red]Status:[/bold red] {resp.status_code}\n[bold red]Detail:[/bold red] {err_msg}",
                    title="[bold red]SAGE Execution Failed[/bold red]",
                    border_style="red"
                ))
                return
            data = resp.json()

        output = data.get("output", "")
        status = data.get("status", "")
        trace = data.get("trace", {})

        # Display Model Routing info
        console.print(f"[bold green]Selected Model:[/bold green] {trace.get('selected_model')}")
        console.print(f"[bold dim]Routing Reason:[/bold dim] {trace.get('routing_reason')}\n")

        # Display Step Trace Table
        table = Table(title="Execution Trace Events")
        table.add_column("#", style="dim")
        table.add_column("State", style="bold cyan")
        table.add_column("Tool / Details", style="yellow")
        table.add_column("Output / Result", style="green")

        events = trace.get("events", [])
        for idx, ev in enumerate(events, 1):
            state = ev.get("agent_state", "")
            tool = ev.get("tool_name") or "-"
            result = ev.get("tool_result") or ev.get("reflection") or ev.get("error") or "-"
            if len(str(result)) > 80:
                result = str(result)[:77] + "..."
            table.add_row(str(idx), str(state), str(tool), str(result))

        console.print(table)
        console.print("\n" + Panel(output, title=f"Final Output ({status})", border_style="green" if status == "COMPLETED" else "red"))

    except httpx.ConnectError:
        console.print(f"[bold red]Connection Error:[/bold red] Could not connect to SAGE backend at {config.backend_url}. Please ensure the server is running.")
    except httpx.TimeoutException:
        console.print(f"[bold red]Timeout Error:[/bold red] Agent request timed out after {timeout}s. The model may be running intensive inference or the backend is busy.")
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")

if __name__ == "__main__":
    app()
