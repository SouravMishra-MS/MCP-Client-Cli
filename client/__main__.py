import sys
import argparse
import json
import asyncio
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt
from rich.text import Text

from .mcp_client import MCPClient

console = Console()

CONFIG_PATH = Path(__file__).resolve().parent.parent / "servers.json"
LLM_CONFIG_PATH = Path(__file__).resolve().parent.parent / "llms.json"
INSTRUCTIONS_CONFIG_PATH = Path(__file__).resolve().parent.parent / "instruction_files.json"


_BANNER = r'''
M"""""`'"""`YM MM'""""'YMM MM"""""""`YM    MM"""""""`YM oo          oo          
M  mm.  mm.  M M' .mmm. `M MM  mmmmm  M    MM  mmmmm  M                         
M  MMM  MMM  M M  MMMMMooM M'        .M    M'        .M dP dP.  .dP dP .d8888b. 
M  MMM  MMM  M M  MMMMMMMM MM  MMMMMMMM    MM  MMMMMMMM 88  `8bd8'  88 88ooood8 
M  MMM  MMM  M M. `MMM' .M MM  MMMMMMMM    MM  MMMMMMMM 88  .d88b.  88 88.  ... 
M  MMM  MMM  M MM.     .dM MM  MMMMMMMM    MM  MMMMMMMM dP dP'  `dP dP `88888P' 
MMMMMMMMMMMMMM MMMMMMMMMMM MMMMMMMMMMMM    MMMMMMMMMMMM                                                 
'''


def print_banner() -> None:
    console.print(_BANNER, style="bold magenta", highlight=False)
    console.print("A lightweight MCP playground for rapid testing.", style="dim", highlight=False)
    # console.print()
    console.print("[version] v0.1.0", style="dim", markup=False, highlight=False)
    console.print()

def _is_quit_token(value: str) -> bool:
    v = (value or "").strip().lower()
    return v in {"q", "quit", "exit"}


def _prompt_toolkit_select_one(
    message: str,
    labels: list[str],
    *,
    allow_cancel: bool = True,
) -> int | None:
    """Return selected index into `labels`, or None if cancelled/unavailable."""
    if not labels:
        return None

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None

    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.dimension import Dimension
    from prompt_toolkit.styles import Style

    entries: list[tuple[str, int | None]] = []
    if allow_cancel:
        entries.append(("(cancel)", None))
    entries.extend([(label, i) for i, label in enumerate(labels)])

    cursor = 0
    if allow_cancel and labels:
        cursor = 1

    def _render() -> FormattedText:
        lines: list[tuple[str, str]] = []
        lines.append(("", f"{message}\n"))
        lines.append(("class:help", "Up/Down=move  Enter=select  Esc/Ctrl+C=cancel\n\n"))

        for i, (label, _idx) in enumerate(entries):
            style = "class:cursor" if i == cursor else ""
            lines.append((style, f"{label}\n"))
        return lines

    kb = KeyBindings()
    result: int | None = None

    @kb.add("up")
    def _up(event):
        nonlocal cursor
        cursor = max(0, cursor - 1)

    @kb.add("down")
    def _down(event):
        nonlocal cursor
        cursor = min(len(entries) - 1, cursor + 1)

    @kb.add("enter")
    def _enter(event):
        nonlocal result
        _label, idx = entries[cursor]
        result = idx
        event.app.exit(result=result)

    @kb.add("escape")
    @kb.add("c-c")
    def _cancel(event):
        event.app.exit(result=None)

    control = FormattedTextControl(_render)
    root = HSplit(
        [
            Window(
                content=control,
                always_hide_cursor=True,
                height=Dimension(min=8),
            )
        ]
    )
    style = Style.from_dict({"cursor": "reverse", "help": "dim"})
    app = Application(layout=Layout(root), key_bindings=kb, full_screen=False, style=style)

    # In asyncio-driven contexts, prompt_toolkit may choose an async runner.
    # Run UI in a thread to keep this function synchronous.
    import threading

    out: dict[str, Any] = {"result": None, "error": None}

    def _runner():
        try:
            out["result"] = app.run()
        except Exception as exc:
            out["error"] = exc

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join()

    if out["error"] is not None:
        return None
    return out["result"]

def load_instruction_files() -> list[dict[str, Any]]:
    if not INSTRUCTIONS_CONFIG_PATH.exists():
        return []
    try:
        return json.loads(INSTRUCTIONS_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        console.log("[red]Warning: could not read instruction_files.json; starting empty.[/red]")
        return []


def save_instruction_files(items: list[dict[str, Any]]) -> None:
    INSTRUCTIONS_CONFIG_PATH.write_text(json.dumps(items, indent=2), encoding="utf-8")


def _normalize_instruction_path(raw: str) -> str:
    p = Path(raw.strip().strip('"').strip("'"))
    if not p.is_absolute():
        # Store as workspace-relative path when possible.
        try:
            p = (INSTRUCTIONS_CONFIG_PATH.parent / p).resolve()
        except Exception:
            pass
    try:
        return str(p)
    except Exception:
        return raw.strip()


def _read_instruction_text(path_str: str) -> str:
    p = Path(path_str)
    if not p.is_absolute():
        p = (INSTRUCTIONS_CONFIG_PATH.parent / p).resolve()
    return p.read_text(encoding="utf-8")


def render_instruction_files(items: list[dict[str, Any]]) -> None:
    console.print("\n[bold yellow]Available instruction files:[/bold yellow]")
    if not items:
        console.print("[dim]None saved yet.[/dim]")
        return

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("Name")
    table.add_column("Path")
    for idx, item in enumerate(items, 1):
        table.add_row(str(idx), str(item.get("name", "")), str(item.get("path", "")))
    console.print(table)


def select_instruction_file_interactive(items: list[dict[str, Any]], message: str) -> dict[str, Any] | None:
    if not items:
        console.print("[yellow]No saved instruction files available.[/yellow]")
        return None

    labels = [
        f"{idx+1}. {str(item.get('name',''))} -> {str(item.get('path',''))}"
        for idx, item in enumerate(items)
    ]

    try:
        picked_idx = _prompt_toolkit_select_one(message, labels, allow_cancel=True)
        if picked_idx is not None:
            return items[picked_idx]
    except Exception:
        pass

    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise RuntimeError("stdin/stdout is not a TTY")

        import inquirer
        from inquirer.render.console import Terminal

        class _Theme(inquirer.themes.Default):
            def __init__(self):
                super().__init__()
                self.List.selection_cursor = "*"
                term = Terminal()
                self.List.selection_color = term.bold_white_on_blue

        choices = [
            f"{idx+1}. {str(item.get('name',''))} -> {str(item.get('path',''))}"
            for idx, item in enumerate(items)
        ]
        answer = inquirer.prompt(
            [inquirer.List("inst", message=message, choices=["(cancel)", *choices])],
            theme=_Theme(),
        )
        if not answer:
            return None
        picked = str(answer.get("inst") or "")
        if picked == "(cancel)":
            return None
        number = int(picked.split(".", 1)[0])
        return items[number - 1]
    except (KeyboardInterrupt, EOFError):
        return None
    except Exception as e:
        console.log(f"[dim]Interactive picker unavailable ({e}); falling back to number entry.[/dim]")
        render_instruction_files(items)
        selection = Prompt.ask("Enter number of instruction file to use (or blank/q to cancel)", default="")
        if not selection.strip() or _is_quit_token(selection):
            return None
        try:
            return items[int(selection) - 1]
        except Exception:
            console.print("[red]Invalid selection; try again.[/red]")
            return None


def add_instruction_file_flow(items: list[dict[str, Any]]) -> None:
    raw_path = Prompt.ask("Instruction file path (.md)", default="InstructionFiles/copilot-instructions.md").strip()
    default_name = Path(raw_path).stem or "instructions"
    name = Prompt.ask("Name (alias)", default=default_name).strip()
    add_instruction_file_by_path(items, raw_path=raw_path, name=name)


def add_instruction_file_by_path(
    items: list[dict[str, Any]],
    raw_path: str,
    name: str | None = None,
) -> None:
    if not raw_path.strip():
        console.print("[yellow]No path provided.[/yellow]")
        return

    try:
        normalized = _normalize_instruction_path(raw_path)
    except Exception:
        normalized = raw_path

    default_name = Path(raw_path).stem or "instructions"
    final_name = (name or default_name).strip() or default_name

    # Warn if the file doesn't exist, but still allow saving (user might create it later).
    try:
        p = Path(normalized)
        if not p.is_absolute():
            p = (INSTRUCTIONS_CONFIG_PATH.parent / p).resolve()
        if not p.exists():
            console.print(f"[yellow]Warning: file does not exist yet: {p}[/yellow]")
    except Exception:
        pass

    # De-dupe by path.
    for existing in items:
        if str(existing.get("path", "")) == normalized:
            console.print("[yellow]That instruction file path is already saved.[/yellow]")
            return

    items.append({"name": final_name, "path": normalized})
    save_instruction_files(items)
    console.print(f"[green]Saved instruction file '{final_name}'[/green]")


def delete_instruction_file_flow(items: list[dict[str, Any]]) -> None:
    inst = select_instruction_file_interactive(items, message="Select instruction file to delete")
    if not inst:
        return
    try:
        items.remove(inst)
        save_instruction_files(items)
        console.print(f"[red]Deleted instruction file '{inst.get('name','')}'[/red]")
    except Exception:
        console.print("[red]Could not delete the selected instruction file.[/red]")


async def manage_instruction_files_menu() -> None:
    while True:
        items = load_instruction_files()
        render_instruction_files(items)
        console.print("\nOptions: [b]l[/b]=list, [b]n[/b]=new & save, [b]d[/b]=delete, [b]b[/b]=back, [b]q[/b]=quit")
        choice = Prompt.ask("Choose option", default="l").lower().strip()

        if _is_quit_token(choice):
            raise SystemExit(0)
        if choice == "b":
            return
        if choice == "l":
            render_instruction_files(items)
            continue
        if choice == "n":
            add_instruction_file_flow(items)
            continue
        if choice == "d":
            if not items:
                console.print("[yellow]No saved instruction files to delete.[/yellow]")
                continue
            delete_instruction_file_flow(items)
            continue

        console.print("[red]Invalid option; try again.[/red]")


def load_llms() -> list[dict[str, Any]]:
    if not LLM_CONFIG_PATH.exists():
        return []
    try:
        return json.loads(LLM_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        console.log("[red]Warning: could not read llms.json; starting empty.[/red]")
        return []


def save_llms(llms: list[dict[str, Any]]) -> None:
    LLM_CONFIG_PATH.write_text(json.dumps(llms, indent=2), encoding="utf-8")


def _mask_secret(value: str | None) -> str:
    if not value:
        return ""
    return "***"


def render_llms(llms: list[dict[str, Any]]) -> None:
    console.print("\n[bold yellow]Available LLM profiles:[/bold yellow]")
    if not llms:
        console.print("[dim]None saved yet.[/dim]")
        return

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("Name")
    table.add_column("Type")
    table.add_column("Endpoint")
    table.add_column("Model")
    table.add_column("API Key")
    for idx, llm in enumerate(llms, 1):
        table.add_row(
            str(idx),
            str(llm.get("name", "")),
            str(llm.get("type", "")),
            str(llm.get("endpoint", "")),
            str(llm.get("model", "")),
            _mask_secret(str(llm.get("api_key", "") or "")),
        )
    console.print(table)


def select_llm_interactive(llms: list[dict[str, Any]], message: str) -> dict[str, Any] | None:
    if not llms:
        console.print("[yellow]No saved LLM profiles available.[/yellow]")
        return None

    labels = [
        f"{idx+1}. {str(llm.get('name',''))} ({str(llm.get('type',''))})" for idx, llm in enumerate(llms)
    ]

    try:
        picked_idx = _prompt_toolkit_select_one(message, labels, allow_cancel=True)
        if picked_idx is not None:
            return llms[picked_idx]
    except Exception:
        pass

    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise RuntimeError("stdin/stdout is not a TTY")

        import inquirer
        from inquirer.render.console import Terminal

        class _Theme(inquirer.themes.Default):
            def __init__(self):
                super().__init__()
                self.List.selection_cursor = "*"
                term = Terminal()
                self.List.selection_color = term.bold_white_on_blue

        choices = labels
        answer = inquirer.prompt(
            [inquirer.List("llm", message=message, choices=["(cancel)", *choices])],
            theme=_Theme(),
        )
        if not answer:
            return None
        picked = str(answer.get("llm") or "")
        if picked == "(cancel)":
            return None
        number = int(picked.split(".", 1)[0])
        return llms[number - 1]
    except (KeyboardInterrupt, EOFError):
        return None
    except Exception as e:
        console.log(f"[dim]Interactive picker unavailable ({e}); falling back to number entry.[/dim]")
        render_llms(llms)
        selection = Prompt.ask("Enter number of LLM profile to use (or blank/q to cancel)", default="")
        if not selection.strip() or _is_quit_token(selection):
            return None
        try:
            return llms[int(selection) - 1]
        except Exception:
            console.print("[red]Invalid selection; try again.[/red]")
            return None


def add_llm_flow(llms: list[dict[str, Any]]) -> None:
    name = Prompt.ask("Name this LLM profile", default="default-azure-openai")
    llm_type = Prompt.ask("LLM type", default="azure_openai")
    endpoint = Prompt.ask("Endpoint / base_url", default="https://<your-resource>.openai.azure.com/openai/v1/")
    model = Prompt.ask("Model (Azure: deployment name)", default="<your-deployment-name>")

    api_key = Prompt.ask("API key (will be stored in llms.json)", password=True)

    api_version = Prompt.ask("API version (optional)", default="")
    llms.append(
        {
            "name": name,
            "type": llm_type,
            "endpoint": endpoint,
            "api_key": api_key,
            "model": model,
            "api_version": api_version,
        }
    )
    save_llms(llms)
    console.print(f"[green]Saved LLM profile '{name}'[/green]")


def edit_llm_flow(llms: list[dict[str, Any]]) -> None:
    llm = select_llm_interactive(llms, message="Select desired LLM profile")
    if not llm:
        return

    current_name = str(llm.get("name", ""))
    current_type = str(llm.get("type", "azure_openai"))
    current_endpoint = str(llm.get("endpoint", ""))
    current_model = str(llm.get("model", ""))
    current_key = str(llm.get("api_key", "") or "")
    current_api_version = str(llm.get("api_version", "") or "")

    llm["name"] = Prompt.ask("Name", default=current_name)
    llm["type"] = Prompt.ask("Type", default=current_type)
    llm["endpoint"] = Prompt.ask("Endpoint / base_url", default=current_endpoint)
    llm["model"] = Prompt.ask("Model (Azure: deployment name)", default=current_model)
    llm["api_version"] = Prompt.ask("API version (optional)", default=current_api_version)

    if Prompt.ask("Update API key? (y/n)", default="n").lower() == "y":
        llm["api_key"] = Prompt.ask("API key (will be stored in llms.json)", password=True)
    else:
        llm["api_key"] = current_key

    save_llms(llms)
    console.print(f"[green]Updated LLM profile '{llm.get('name','')}'[/green]")


def delete_llm_flow(llms: list[dict[str, Any]]) -> None:
    llm = select_llm_interactive(llms, message="Select desired LLM profile")
    if not llm:
        return

    try:
        llms.remove(llm)
        save_llms(llms)
        console.print(f"[red]Deleted LLM profile '{llm.get('name','')}'[/red]")
    except Exception:
        console.print("[red]Could not delete the selected LLM profile.[/red]")


async def manage_llms_menu() -> None:
    while True:
        llms = load_llms()
        render_llms(llms)
        console.print("\nOptions: [b]l[/b]=list LLMs, [b]n[/b]=new & save, [b]e[/b]=edit, [b]d[/b]=delete, [b]b[/b]=back, [b]q[/b]=quit  [dim](Note: currently only API key auth is supported.)[/dim]")
        choice = Prompt.ask("Choose option", default="l").lower().strip()

        if _is_quit_token(choice):
            raise SystemExit(0)
        if choice == "b":
            return
        if choice == "l":
            render_llms(llms)
            continue
        if choice == "n":
            add_llm_flow(llms)
            continue
        if choice == "e":
            if not llms:
                console.print("[yellow]No saved LLMs to edit.[/yellow]")
                continue
            edit_llm_flow(llms)
            continue
        if choice == "d":
            if not llms:
                console.print("[yellow]No saved LLMs to delete.[/yellow]")
                continue
            delete_llm_flow(llms)
            continue

        console.print("[red]Invalid option; try again.[/red]")


def load_servers() -> list[dict[str, Any]]:
    if not CONFIG_PATH.exists():
        return []
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        console.log("[red]Warning: could not read servers.json; starting empty.[/red]")
        return []


def save_servers(servers: list[dict[str, Any]]) -> None:
    CONFIG_PATH.write_text(json.dumps(servers, indent=2), encoding="utf-8")


def prompt_extra_args() -> list[str]:
    if Prompt.ask("Add extra arguments? (y/n)", default="n").lower() != "y":
        return []
    args_input = Prompt.ask("Enter arguments (comma-separated)", default="")
    return [arg.strip() for arg in args_input.split(",") if arg.strip()]


def prompt_extra_args_edit(existing_args: list[str]) -> list[str]:
    if Prompt.ask("Edit extra arguments? (y/n)", default="n").lower() != "y":
        return existing_args
    args_input = Prompt.ask("Enter arguments (comma-separated)", default=", ".join(existing_args))
    return [arg.strip() for arg in args_input.split(",") if arg.strip()]


def render_saved_servers(servers: list[dict[str, Any]]) -> None:
    console.print("\n[bold yellow]Available MCP servers:[/bold yellow]")
    if not servers:
        console.print("[dim]None saved yet.[/dim]")
        return

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4)
    table.add_column("Name")
    table.add_column("URL / Path")
    table.add_column("Extra Args")
    for idx, srv in enumerate(servers, 1):
        table.add_row(
            str(idx),
            str(srv.get("name", "")),
            str(srv.get("url", "")),
            " ".join(srv.get("extra_args", []) or []),
        )
    console.print(table)


def _format_server_choice(srv: dict[str, Any]) -> str:
    name = str(srv.get("name", ""))
    url = str(srv.get("url", ""))
    extra_args = " ".join(srv.get("extra_args", []) or [])
    if extra_args:
        return f"{name} -> {url} ({extra_args})"
    return f"{name} -> {url}"


def select_server_interactive(
    servers: list[dict[str, Any]],
    message: str,
    allow_cancel: bool = True,
) -> dict[str, Any] | None:
    if not servers:
        console.print("[yellow]No saved servers available.[/yellow]")
        return None

    # Prefer a keyboard-driven selector (arrow keys) if we're in an interactive
    # terminal and the optional prompt dependency is available. Otherwise, fall
    # back to numeric selection.
    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise RuntimeError("stdin/stdout is not a TTY")

        import inquirer  # optional dependency; enabled when installed in the active environment

        class _MCPTheme(inquirer.themes.Default):
            def __init__(self):
                super().__init__()
                # Avoid '>' and keep ASCII-only markers for Windows terminals.
                self.List.selection_cursor = "*"
                self.Checkbox.selection_icon = "*"
                self.Checkbox.selected_icon = "[x]"
                self.Checkbox.unselected_icon = "[ ]"

        # Use strings (not tuple values) to avoid version-specific behavior.
        labels: list[str] = [f"{idx+1}. {_format_server_choice(srv)}" for idx, srv in enumerate(servers)]
        choices: list[str] = []
        if allow_cancel:
            choices.append("(cancel)")
        choices.extend(labels)

        answer = inquirer.prompt(
            [
                inquirer.List(
                    "server_index",
                    message=message,
                    choices=choices,
                )
            ],
            theme=_MCPTheme(),
        )

        if not answer:
            return None

        picked = answer.get("server_index")
        if not picked or picked == "(cancel)":
            return None

        try:
            # Expect "<n>. ..."
            number = int(str(picked).split(".", 1)[0])
            return servers[number - 1]
        except Exception:
            return None
    except (KeyboardInterrupt, EOFError):
        return None
    except Exception as e:
        console.log(f"[dim]Interactive picker unavailable ({e}); falling back to number entry.[/dim]")
        render_saved_servers(servers)
        selection = Prompt.ask("Enter number of server to use (or blank to cancel)", default="")
        if not selection.strip():
            return None
        try:
            i = int(selection) - 1
            return servers[i]
        except Exception:
            console.print("[red]Invalid selection; try again.[/red]")
            return None


def select_servers_interactive(
    servers: list[dict[str, Any]],
    message: str,
    allow_cancel: bool = True,
) -> list[dict[str, Any]] | None:
    if not servers:
        console.print("[yellow]No saved servers available.[/yellow]")
        return None

    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            raise RuntimeError("stdin/stdout is not a TTY")

        # Preferred UX: Enter toggles selection; Enter on (done) confirms.
        # This isn't supported by python-inquirer, so we use prompt_toolkit.
        try:
            from prompt_toolkit.application import Application
            from prompt_toolkit.formatted_text import FormattedText
            from prompt_toolkit.key_binding import KeyBindings
            from prompt_toolkit.layout import HSplit, Layout
            from prompt_toolkit.layout.controls import FormattedTextControl
            from prompt_toolkit.layout.dimension import Dimension
            from prompt_toolkit.layout.containers import Window
            from prompt_toolkit.styles import Style

            entries: list[tuple[str, int | None]] = [("(done)", None)]
            if allow_cancel:
                entries.append(("(cancel)", None))
            for idx, srv in enumerate(servers):
                entries.append((f"{idx+1}. {_format_server_choice(srv)}", idx))

            selected: set[int] = set()
            cursor = 2 if allow_cancel else 1
            if cursor >= len(entries):
                cursor = 0

            def _render() -> FormattedText:
                lines: list[tuple[str, str]] = []
                lines.append(("", f"{message}\n"))
                lines.append(("class:help", "Up/Down=move  Enter=toggle  Enter on '(done)'=confirm  Esc/Ctrl+C=cancel\n\n"))

                for i, (label, server_idx) in enumerate(entries):
                    if server_idx is None:
                        prefix = "  "
                    else:
                        prefix = "* " if server_idx in selected else "  "

                    text = f"{prefix}{label}\n"
                    style = "class:cursor" if i == cursor else ""
                    lines.append((style, text))

                return lines

            kb = KeyBindings()
            result: list[dict[str, Any]] | None = None

            @kb.add("up")
            def _up(event):
                nonlocal cursor
                cursor = max(0, cursor - 1)

            @kb.add("down")
            def _down(event):
                nonlocal cursor
                cursor = min(len(entries) - 1, cursor + 1)

            @kb.add("enter")
            def _enter(event):
                nonlocal result
                label, server_idx = entries[cursor]
                if label == "(cancel)":
                    result = None
                    event.app.exit(result=result)
                    return
                if label == "(done)":
                    result = [servers[i] for i in sorted(selected)] or None
                    event.app.exit(result=result)
                    return
                if server_idx is not None:
                    if server_idx in selected:
                        selected.remove(server_idx)
                    else:
                        selected.add(server_idx)

            @kb.add("escape")
            @kb.add("c-c")
            def _cancel(event):
                event.app.exit(result=None)

            control = FormattedTextControl(_render)
            root = HSplit(
                [
                    Window(
                        content=control,
                        always_hide_cursor=True,
                        height=Dimension(min=8),
                    )
                ]
            )
            style = Style.from_dict({"cursor": "reverse", "help": "dim"})
            app = Application(layout=Layout(root), key_bindings=kb, full_screen=False, style=style)
            # When called from within an asyncio-driven CLI flow, prompt_toolkit may choose an
            # async runner. To keep this function synchronous and avoid coroutine warnings,
            # run the UI in a dedicated thread.
            import threading

            out: dict[str, Any] = {"result": None, "error": None}

            def _runner():
                try:
                    out["result"] = app.run()
                except Exception as exc:
                    out["error"] = exc

            t = threading.Thread(target=_runner, daemon=True)
            t.start()
            t.join()

            if out["error"] is not None:
                raise out["error"]
            return out["result"]
        except Exception:
            # Fallback: if prompt_toolkit isn't available for some reason, keep a basic selector.
            import inquirer  # optional dependency

            class _MCPTheme(inquirer.themes.Default):
                def __init__(self):
                    super().__init__()
                    self.List.selection_cursor = "*"

            labels: list[str] = [f"{idx+1}. {_format_server_choice(srv)}" for idx, srv in enumerate(servers)]
            choices: list[str] = []
            if allow_cancel:
                choices.append("(cancel)")
            choices.extend(labels)

            answer = inquirer.prompt(
                [inquirer.List("server", message=f"{message} (Enter=select)", choices=choices)],
                theme=_MCPTheme(),
            )
            if not answer:
                return None
            picked = str(answer.get("server") or "")
            if picked == "(cancel)":
                return None
            try:
                number = int(picked.split(".", 1)[0])
                return [servers[number - 1]]
            except Exception:
                return None
    except (KeyboardInterrupt, EOFError):
        return None
    except Exception as e:
        console.log(f"[dim]Interactive picker unavailable ({e}); falling back to number entry.[/dim]")
        # Fallback: prompt for comma-separated numbers.
        render_saved_servers(servers)
        selection = Prompt.ask("Enter server numbers (comma-separated) or blank to cancel", default="")
        if not selection.strip():
            return None

        indexes: list[int] = []
        for part in selection.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                indexes.append(int(part) - 1)
            except Exception:
                console.print("[red]Invalid selection; try again.[/red]")
                return None

        picked: list[dict[str, Any]] = []
        for i in indexes:
            if i < 0 or i >= len(servers):
                console.print("[red]Selection out of range; try again.[/red]")
                return None
            if servers[i] not in picked:
                picked.append(servers[i])

        return picked


def add_server_flow(servers: list[dict[str, Any]]) -> tuple[str, list[str]]:
    name = Prompt.ask("Name this MCP server (alias)", default="default")
    url = Prompt.ask("Enter MCP server path or URL", default="https://learn.microsoft.com/api/mcp")
    extra_args = prompt_extra_args()
    servers.append({"name": name, "url": url, "extra_args": extra_args})
    save_servers(servers)
    console.print(f"[green]Saved server '{name}'[/green]")
    return url, extra_args


def delete_server_flow(servers: list[dict[str, Any]]) -> None:
    if not servers:
        console.print("[yellow]No saved servers to delete.[/yellow]")
        return
    selected = select_server_interactive(servers, message="Select desired MCP server", allow_cancel=True)
    if not selected:
        return
    try:
        servers.remove(selected)
        save_servers(servers)
        console.print(f"[red]Deleted '{selected.get('name', '')}'[/red]")
    except Exception:
        console.print("[red]Could not delete the selected server.[/red]")


def edit_server_flow(servers: list[dict[str, Any]]) -> None:
    if not servers:
        console.print("[yellow]No saved servers to edit.[/yellow]")
        return

    server = select_server_interactive(servers, message="Select desired MCP server", allow_cancel=True)
    if not server:
        return

    current_name = str(server.get("name", ""))
    current_url = str(server.get("url", ""))
    current_args = server.get("extra_args", []) or []

    new_name = Prompt.ask("Name (alias)", default=current_name)
    new_url = Prompt.ask("Server path or URL", default=current_url)
    new_args = prompt_extra_args_edit(list(current_args))

    server["name"] = new_name
    server["url"] = new_url
    server["extra_args"] = new_args
    save_servers(servers)
    console.print(f"[green]Updated server '{new_name}'[/green]")


def select_saved_server_flow(servers: list[dict[str, Any]]) -> tuple[str, list[str]] | None:
    selected = select_server_interactive(servers, message="Select desired MCP server", allow_cancel=True)
    if not selected:
        return None
    return selected.get("url", ""), selected.get("extra_args", []) or []


async def inspect_server_capabilities(server_input: str, session_args: list[str]) -> None:
    client = MCPClient()
    try:
        console.print(f"\n[bold cyan]Connecting to {server_input}...[/bold cyan]")
        await client.connect_to_server(server_input, extra_args=session_args)
        await display_server_capabilities(client)
    except Exception as e:
        console.print(f"[bold red]Error inspecting server: {e}[/bold red]")
    finally:
        await client.cleanup()


async def manage_servers_menu() -> None:
    while True:
        servers = load_servers()
        render_saved_servers(servers)
        console.print("\nOptions: [b]l[/b]=list servers, [b]n[/b]=new & save, [b]e[/b]=edit, [b]d[/b]=delete, [b]i[/b]=inspect capabilities, [b]b[/b]=back, [b]q[/b]=quit")
        choice = Prompt.ask("Choose option", default="l").lower().strip()

        if _is_quit_token(choice):
            raise SystemExit(0)
        if choice == "b":
            return
        if choice == "l":
            render_saved_servers(servers)
            continue
        if choice == "n":
            add_server_flow(servers)
            continue
        if choice == "e":
            edit_server_flow(servers)
            continue
        if choice == "d":
            delete_server_flow(servers)
            continue
        if choice == "i":
            selected = select_saved_server_flow(servers)
            if not selected:
                continue
            server_input, session_args = selected
            await inspect_server_capabilities(server_input, session_args)
            continue

        console.print("[red]Invalid option; try again.[/red]")


def choose_server_for_chat() -> tuple[str, list[str]] | None:
    while True:
        servers = load_servers()
        console.print("\nChat Options: [b]s[/b]=select MCP server(s), [b]a[/b]=ad-hoc (not saved), [b]b[/b]=back, [b]q[/b]=quit")
        default_choice = "s" if servers else "a"
        choice = Prompt.ask("Choose option", default=default_choice).lower().strip()

        if _is_quit_token(choice):
            raise SystemExit(0)
        if choice == "b":
            return None
        if choice == "a":
            url = Prompt.ask("Enter MCP server path or URL", default="https://learn.microsoft.com/api/mcp")
            extra_args = prompt_extra_args()
            return url, extra_args
        if choice == "s":
            picked = select_servers_interactive(servers, message="Select desired MCP server(s)")
            if picked:
                # For compatibility, if user chose exactly one server, return a single server tuple.
                if len(picked) == 1:
                    srv = picked[0]
                    return srv.get("url", ""), srv.get("extra_args", []) or []

                # Multi-select: encode as a special marker tuple; caller will handle.
                # Return the first server as a placeholder; actual selection list is stored in a private attr.
                # (Kept minimal to avoid changing too many call sites.)
                choose_server_for_chat._multi_selected = picked  # type: ignore[attr-defined]
                first = picked[0]
                return first.get("url", ""), first.get("extra_args", []) or []
            continue

        console.print("[red]Invalid option; try again.[/red]")

async def display_server_capabilities(client: MCPClient):
    """
    Display available tools, prompts, and resources.
    """
    console.print("\n[bold underline cyan]Server Capabilities:[/bold underline cyan]\n")

    # Get tools
    tools_response = await client.session.list_tools()
    if tools_response.tools:
        console.print("[bold yellow]Tools:[/bold yellow]")
        tools_table = Table(show_header=True, header_style="bold magenta")
        tools_table.add_column("Name")
        tools_table.add_column("Description")
        for tool in tools_response.tools:
            tools_table.add_row(tool.name, tool.description or "N/A")
        console.print(tools_table)
    
    # Get prompts (if available)
    try:
        prompts_response = await client.session.list_prompts()
        if prompts_response.prompts:
            console.print("\n[bold yellow]Prompts:[/bold yellow]")
            prompts_table = Table(show_header=True, header_style="bold magenta")
            prompts_table.add_column("Name")
            prompts_table.add_column("Description")
            for prompt in prompts_response.prompts:
                prompts_table.add_row(prompt.name, prompt.description or "N/A")
            console.print(prompts_table)
    except Exception as e:
        console.log(f"[dim]Prompts not available: {e}[/dim]")
    
    # Get resources (if available)
    try:
        resources_response = await client.session.list_resources()
        if resources_response.resources:
            console.print("\n[bold yellow]Resources:[/bold yellow]")
            resources_table = Table(show_header=True, header_style="bold magenta")
            resources_table.add_column("URI")
            resources_table.add_column("Name")
            for resource in resources_response.resources:
                resources_table.add_row(resource.uri, resource.name or "N/A")
            console.print(resources_table)
    except Exception as e:
        console.log(f"[dim]Resources not available: {e}[/dim]")

async def main(
    server_arg: str | None = None,
    extra_args: list[str] | None = None,
    instruction_text: str | None = None,
):
    print_banner()

    def require_llm_selection() -> dict[str, Any] | None:
        llms = load_llms()
        if not llms:
            console.print("[yellow]No LLM profiles found. Add one under Manage LLM profiles.[/yellow]")
            return None
        return select_llm_interactive(llms, message="Select desired LLM profile")

    async def run_chat_session(
        server_input: str,
        session_args: list[str],
        llm_profile: dict[str, Any],
        instruction_text: str | None,
    ):
        client = MCPClient(llm_config=llm_profile, instructions=instruction_text)
        try:
            console.print(f"\n[bold cyan]Connecting to {server_input}...[/bold cyan]")
            await client.connect_to_server(server_input, extra_args=session_args)
            console.print("\n[bold yellow]Chat[/bold yellow]")
            console.print("[dim]Type 'quit' to exit or 'refresh' to clear history[/dim]\n")
            await client.chat_loop()
        except Exception as e:
            console.print(f"[bold red]Error: {e}[/bold red]")
        finally:
            await client.cleanup()

    async def run_multi_server_chat(
        picked_servers: list[dict[str, Any]],
        llm_profile: dict[str, Any],
        instruction_text: str | None,
    ):
        clients: list[MCPClient] = []
        histories: list[list] = []
        labels: list[str] = []
        targets: list[tuple[str, list[str]]] = []

        for srv in picked_servers:
            labels.append(str(srv.get("name", "")) or str(srv.get("url", "")))
            targets.append((str(srv.get("url", "")), srv.get("extra_args", []) or []))

        try:
            console.print(f"\n[bold cyan]Connecting to {len(targets)} MCP servers...[/bold cyan]")
            for (server_input, session_args) in targets:
                client = MCPClient(llm_config=llm_profile, instructions=instruction_text)
                await client.connect_to_server(server_input, extra_args=session_args)
                clients.append(client)
                histories.append([])

            active = 0
            console.print("\n[bold yellow]Chat (multi-server)[/bold yellow]")
            console.print("[dim]Commands: servers | use <n> | quit/exit | refresh[/dim]")

            while True:
                try:
                    query = input(f"\n[{active+1}:{labels[active]}] Query: ").strip()
                except (KeyboardInterrupt, EOFError):
                    print("\nExiting chat...")
                    break

                if not query:
                    continue
                ql = query.lower()
                if ql in {"quit", "exit"}:
                    break
                if ql == "servers":
                    console.print("\n[bold yellow]Selected MCP servers:[/bold yellow]")
                    for i, label in enumerate(labels, 1):
                        marker = "*" if (i - 1) == active else " "
                        console.print(f"{marker} {i}. {label}")
                    continue
                if ql.startswith("use "):
                    raw = query[4:].strip()
                    try:
                        idx = int(raw) - 1
                        if 0 <= idx < len(clients):
                            active = idx
                        else:
                            console.print("[red]Index out of range.[/red]")
                    except Exception:
                        console.print("[red]Usage: use <n>[/red]")
                    continue
                if ql == "refresh":
                    histories[active] = []
                    continue

                try:
                    response, new_history = await clients[active].process_query(query=query, previous_messages=histories[active])
                    histories[active] = new_history
                    print(f"\nResponse: {response}")
                except Exception as e:
                    console.print(f"[bold red]Error: {e}[/bold red]")
        finally:
            for c in clients:
                try:
                    await c.cleanup()
                except Exception:
                    pass

    # CLI mode: user explicitly picked a server by passing args.
    if server_arg:
        server_input = server_arg
        session_args = extra_args or []
        console.print(f"[bold yellow]Using server from CLI:[/bold yellow] {server_input}")
        llm_profile = require_llm_selection()
        if not llm_profile:
            console.print("[bold red]No LLM selected; exiting.[/bold red]")
            console.print("\n[bold cyan]MCP Client closed![/bold cyan]")
            return
        await run_chat_session(server_input, session_args, llm_profile, instruction_text)
        console.print("\n[bold cyan]MCP Client closed![/bold cyan]")
        return

    # Interactive mode: separate management vs chat, and always select a server before chat.
    while True:
        console.print("\n[bold yellow]Available Options[/bold yellow]")
        line = Text(); line.append("c", style="bold"); line.append("  Chat — [select an LLM and an MCP server, then start chatting]")
        console.print(line)
        line = Text(); line.append("m", style="bold"); line.append("  Manage MCP servers — [add/edit/delete saved MCP server connections]")
        console.print(line)
        line = Text(); line.append("l", style="bold"); line.append("  Manage LLM profiles — [add/edit/delete your LLM endpoint + model settings]")
        console.print(line)
        line = Text(); line.append("i", style="bold"); line.append("  Manage instruction files — [save reusable markdown prompts for chat sessions]")
        console.print(line)
        line = Text(); line.append("q", style="bold"); line.append("  Quit — [close the app (you can also type 'quit' or 'exit')]")
        console.print(line)
        choice = Prompt.ask("Choose option", default="c").lower().strip()

        if _is_quit_token(choice):
            break
        if choice == "m":
            try:
                await manage_servers_menu()
            except SystemExit:
                break
            continue
        if choice == "l":
            try:
                await manage_llms_menu()
            except SystemExit:
                break
            continue
        if choice == "i":
            try:
                await manage_instruction_files_menu()
            except SystemExit:
                break
            continue
        if choice == "c":
            llm_profile = require_llm_selection()
            if not llm_profile:
                continue

            instruction_text: str | None = None
            try:
                if Prompt.ask("Use instruction file for this session? (y/n)", default="n").lower().strip() == "y":
                    items = load_instruction_files()
                    if not items:
                        console.print("[yellow]No saved instruction files. Add one under Manage instruction files.[/yellow]")
                    else:
                        inst = select_instruction_file_interactive(items, message="Select instruction file")
                        if inst:
                            instruction_text = _read_instruction_text(str(inst.get("path", "")))
            except (KeyboardInterrupt, EOFError):
                instruction_text = None
            except Exception as e:
                console.print(f"[yellow]Could not load instruction file: {e}[/yellow]")

            try:
                selected = choose_server_for_chat()
            except SystemExit:
                break
            if not selected:
                continue

            picked_servers = getattr(choose_server_for_chat, "_multi_selected", None)
            if picked_servers:
                delattr(choose_server_for_chat, "_multi_selected")
                await run_multi_server_chat(picked_servers, llm_profile, instruction_text)
                continue

            server_input, session_args = selected
            await run_chat_session(server_input, session_args, llm_profile, instruction_text)
            continue

        console.print("[red]Invalid option; try again.[/red]")

    console.print("\n[bold cyan]MCP Client closed![/bold cyan]")

def cli_main():
    parser = argparse.ArgumentParser(
        prog="mcp-client",
        description="Universal MCP client supporting stdio, SSE, and HTTP transports.",
    )
    parser.add_argument(
        "server",
        nargs="?",
        help="MCP server URL/path or npm package name (e.g., https://.../mcp, ./server.py, @azure-devops/mcp)",
    )
    parser.add_argument(
        "extra_args",
        nargs=argparse.REMAINDER,
        help="Extra arguments passed through to the server (stdio only)",
    )
    parser.add_argument(
        "-m",
        "--manage-mcp-servers",
        action="store_true",
        help="Open the MCP server management menu and exit",
    )
    parser.add_argument(
        "-l",
        "--manage-llm-profiles",
        dest="manage_llms",
        action="store_true",
        help="Open the LLM profile management menu and exit",
    )
    parser.add_argument(
        "-c",
        "--chat",
        "--chat-with-server",
        action="store_true",
        help="Go directly to server selection, then start chat",
    )
    parser.add_argument(
        "-i",
        "--add-instruction-file",
        nargs="?",
        const="__PROMPT__",
        default=None,
        metavar="PATH",
        help=(
            "Instruction file helper. "
            "If used with -c (or a positional server), applies the markdown for this run only. "
            "If used alone, saves the file path into instruction_files.json. "
            "If PATH is omitted, you will be prompted."
        ),
    )

    args = parser.parse_args()

    if args.add_instruction_file is not None and (args.manage_mcp_servers or args.manage_llms):
        parser.error("-i/--add-instruction-file cannot be combined with management menus")

    if args.manage_mcp_servers:
        async def manage_only():
            try:
                await manage_servers_menu()
            except SystemExit:
                return

        asyncio.run(manage_only())
        return

    if args.manage_llms:
        async def manage_llms_only():
            try:
                await manage_llms_menu()
            except SystemExit:
                return

        asyncio.run(manage_llms_only())
        return

    if args.chat and args.server:
        parser.error("--chat cannot be used together with a positional server argument")

    if args.chat:
        async def chat_only():
            print_banner()

            # Select LLM first (then MCP server selection), to match the interactive chat flow.
            llms = load_llms()
            if not llms:
                console.print("[yellow]No LLM profiles found. Add one under Manage LLM profiles.[/yellow]")
                return

            llm_profile = select_llm_interactive(llms, message="Select desired LLM profile")
            if not llm_profile:
                console.print("[yellow]No LLM selected; exiting.[/yellow]")
                return

            instruction_text: str | None = None
            if args.add_instruction_file is not None:
                try:
                    if args.add_instruction_file == "__PROMPT__":
                        raw_path = Prompt.ask(
                            "Instruction file path (.md)",
                            default="InstructionFiles/copilot-instructions.md",
                        ).strip()
                        instruction_text = _read_instruction_text(raw_path)
                    else:
                        instruction_text = _read_instruction_text(str(args.add_instruction_file))
                except (KeyboardInterrupt, EOFError):
                    instruction_text = None
                except Exception as e:
                    console.print(f"[yellow]Could not load instruction file: {e}[/yellow]")
                    instruction_text = None
            else:
                try:
                    if Prompt.ask("Use instruction file for this session? (y/n)", default="n").lower().strip() == "y":
                        items = load_instruction_files()
                        if not items:
                            console.print("[yellow]No saved instruction files. Add one under Manage instruction files.[/yellow]")
                        else:
                            inst = select_instruction_file_interactive(items, message="Select instruction file")
                            if inst:
                                instruction_text = _read_instruction_text(str(inst.get("path", "")))
                except (KeyboardInterrupt, EOFError):
                    instruction_text = None
                except Exception as e:
                    console.print(f"[yellow]Could not load instruction file: {e}[/yellow]")

            try:
                selected = choose_server_for_chat()
            except SystemExit:
                return
            if not selected:
                return

            async def run_chat_session(server_input: str, session_args: list[str]):
                client = MCPClient(llm_config=llm_profile, instructions=instruction_text)
                try:
                    console.print(f"\n[bold cyan]Connecting to {server_input}...[/bold cyan]")
                    await client.connect_to_server(server_input, extra_args=session_args)
                    console.print("\n[bold yellow]Chat[/bold yellow]")
                    console.print("[dim]Type 'quit' to exit or 'refresh' to clear history[/dim]\n")
                    await client.chat_loop()
                except Exception as e:
                    console.print(f"[bold red]Error: {e}[/bold red]")
                finally:
                    await client.cleanup()

            async def run_multi_server_chat(picked_servers: list[dict[str, Any]]):
                clients: list[MCPClient] = []
                histories: list[list] = []
                labels: list[str] = []
                targets: list[tuple[str, list[str]]] = []

                for srv in picked_servers:
                    labels.append(str(srv.get("name", "")) or str(srv.get("url", "")))
                    targets.append((str(srv.get("url", "")), srv.get("extra_args", []) or []))

                try:
                    console.print(f"\n[bold cyan]Connecting to {len(targets)} MCP servers...[/bold cyan]")
                    for (server_input, session_args) in targets:
                        client = MCPClient(llm_config=llm_profile, instructions=instruction_text)
                        await client.connect_to_server(server_input, extra_args=session_args)
                        clients.append(client)
                        histories.append([])

                    active = 0
                    console.print("\n[bold yellow]Chat (multi-server)[/bold yellow]")
                    console.print("[dim]Commands: servers | use <n> | quit/exit | refresh[/dim]")

                    while True:
                        try:
                            query = input(f"\n[{active+1}:{labels[active]}] Query: ").strip()
                        except (KeyboardInterrupt, EOFError):
                            print("\nExiting chat...")
                            break

                        if not query:
                            continue
                        ql = query.lower()
                        if ql in {"quit", "exit"}:
                            break
                        if ql == "servers":
                            console.print("\n[bold yellow]Selected MCP servers:[/bold yellow]")
                            for i, label in enumerate(labels, 1):
                                marker = "*" if (i - 1) == active else " "
                                console.print(f"{marker} {i}. {label}")
                            continue
                        if ql.startswith("use "):
                            raw = query[4:].strip()
                            try:
                                idx = int(raw) - 1
                                if 0 <= idx < len(clients):
                                    active = idx
                                else:
                                    console.print("[red]Index out of range.[/red]")
                            except Exception:
                                console.print("[red]Usage: use <n>[/red]")
                            continue
                        if ql == "refresh":
                            histories[active] = []
                            continue

                        try:
                            response, new_history = await clients[active].process_query(query=query, previous_messages=histories[active])
                            histories[active] = new_history
                            print(f"\nResponse: {response}")
                        except Exception as e:
                            console.print(f"[bold red]Error: {e}[/bold red]")
                finally:
                    for c in clients:
                        try:
                            await c.cleanup()
                        except Exception:
                            pass

            picked_servers = getattr(choose_server_for_chat, "_multi_selected", None)
            if picked_servers:
                delattr(choose_server_for_chat, "_multi_selected")
                await run_multi_server_chat(picked_servers)
                return

            server_input, session_args = selected
            await run_chat_session(server_input, session_args)

        asyncio.run(chat_only())
        return

    server_arg = args.server
    extra_args = args.extra_args if args.extra_args else None

    # Handle -i behavior when not using -c.
    # - If a positional server is present, treat -i as an instruction file for this run.
    # - If no server is present, treat -i as a request to save/register an instruction file.
    instr_text: str | None = None
    if args.add_instruction_file is not None:
        if server_arg:
            try:
                if args.add_instruction_file == "__PROMPT__":
                    raw_path = Prompt.ask(
                        "Instruction file path (.md)",
                        default="InstructionFiles/copilot-instructions.md",
                    ).strip()
                    instr_text = _read_instruction_text(raw_path)
                else:
                    instr_text = _read_instruction_text(str(args.add_instruction_file))
            except (KeyboardInterrupt, EOFError):
                instr_text = None
            except Exception as e:
                console.print(f"[yellow]Could not load instruction file: {e}[/yellow]")
                instr_text = None
        else:
            try:
                if args.add_instruction_file == "__PROMPT__":
                    raw_path = Prompt.ask(
                        "Instruction file path (.md)",
                        default="InstructionFiles/copilot-instructions.md",
                    ).strip()
                else:
                    raw_path = str(args.add_instruction_file)

                items = load_instruction_files()
                add_instruction_file_by_path(items, raw_path=raw_path, name=None)
            except (KeyboardInterrupt, EOFError):
                return
            return

    asyncio.run(main(server_arg, extra_args, instr_text))


# async def main():
#     # console.print("[bold cyan]Welcome to MCP Client[/bold cyan]\n")
#     # if len(sys.argv) < 2:
#     #     print("Usage: python -m client <server_script_path_or_url>")
#     #     print("Examples: ")
#     #     print("  - stdio MCP server (npm):")
#     #     print("      python -m client @playwright/mcp@latest")
#     #     print("  - stdio MCP server (Azure DevOps):")
#     #     print("      python -m client @azure-devops/mcp contoso -d core work work-items")
#     #     print("  - stdio MCP server (python):")
#     #     print("      python -m client ./weather.py")
#     #     print("  - SSE MCP server:")
#     #     print("      python -m client http://localhost:3000/mcp")
#     #     print("  - HTTP MCP server:")
#     #     print("      python -m client http://localhost:3000/mcp")
#     #     sys.exit(1)
    
#     # server = sys.argv[1]
#     # extra_args = sys.argv[2:]

#     # client = MCPClient()
#     # try:
#     #     await client.connect_to_server(server, extra_args=extra_args)
#     #     await client.chat_loop()
#     # finally:
#     #     await client.cleanup()
#     #     print("\nMCP Client closed!")


# def cli_main():
#     """Synchronous entry point for console script."""
#     asyncio.run(main())

if __name__ == "__main__":
    cli_main()

