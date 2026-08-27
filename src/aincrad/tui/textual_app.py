from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar, cast

from textual.app import App, ComposeResult
from textual.containers import Container, VerticalScroll
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, Label, ListItem, ListView, Static

from aincrad.tui.renderer import sanitize_terminal_text

T = TypeVar("T")
Session = Callable[["TextualInteraction"], int]
Validator = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class MenuOption(Generic[T]):
    label: str
    description: str
    value: T


class MenuScreen(ModalScreen[int | None]):
    BINDINGS = [
        ("w", "cursor_up", "위"),
        ("s", "cursor_down", "아래"),
    ]

    def __init__(
        self,
        title: str,
        options: Sequence[MenuOption[object]],
        *,
        subtitle: str = "",
        context: Sequence[str] = (),
        allow_back: bool = False,
    ) -> None:
        super().__init__()
        self._title = sanitize_terminal_text(title)
        self._options = tuple(
            MenuOption(
                sanitize_terminal_text(option.label),
                sanitize_terminal_text(option.description),
                option.value,
            )
            for option in options
        )
        self._subtitle = sanitize_terminal_text(subtitle)
        self._context_lines = tuple(sanitize_terminal_text(item) for item in context)
        self._allow_back = allow_back

    @property
    def snapshot_text(self) -> str:
        return "\n".join(
            (
                "◆ THE GLASS FRONTIER",
                self._title,
                self._subtitle,
                *self._context_lines,
                *(option.label for option in self._options),
            )
        )

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Static("◆ THE GLASS FRONTIER", id="brand", markup=False)
            yield Static(self._title, id="screen-title", markup=False)
            if self._subtitle:
                yield Static(self._subtitle, id="subtitle", markup=False)
            if self._context_lines:
                yield Static("\n".join(self._context_lines), id="context", markup=False)
            yield ListView(
                *(
                    ListItem(
                        Static(
                            option.label
                            + (f"\n{option.description}" if option.description else ""),
                            markup=False,
                        ),
                        id=f"option-{index}",
                    )
                    for index, option in enumerate(self._options)
                ),
                id="menu",
            )
            hint = "↑↓ / W S 이동 · Enter 선택"
            if self._allow_back:
                hint += " · Esc 뒤로"
            yield Static(hint, id="hint", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#menu", ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        index = self.query_one("#menu", ListView).index
        if index is not None:
            self.dismiss(index)

    def action_cursor_up(self) -> None:
        self.query_one("#menu", ListView).action_cursor_up()

    def action_cursor_down(self) -> None:
        self.query_one("#menu", ListView).action_cursor_down()

    def action_cancel(self) -> None:
        if self._allow_back:
            self.dismiss(None)

    def on_key(self, event: Key) -> None:
        if self._allow_back and event.key in {"escape", "q"}:
            event.stop()
            self.dismiss(None)


class SafeInput(Input):
    """Input that neutralizes terminal controls before they enter live widget state."""

    def replace(self, text: str, start: int, end: int) -> None:
        super().replace(sanitize_terminal_text(text), start, end)


class NameScreen(ModalScreen[str | None]):
    BINDINGS = [("escape", "cancel", "뒤로")]

    def __init__(self, title: str, *, subtitle: str, validate: Validator) -> None:
        super().__init__()
        self._title = sanitize_terminal_text(title)
        self._subtitle = sanitize_terminal_text(subtitle)
        self._validate = validate

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Static("◆ THE GLASS FRONTIER", id="brand", markup=False)
            yield Static(self._title, id="screen-title", markup=False)
            yield Static(self._subtitle, id="subtitle", markup=False)
            yield SafeInput(placeholder="이름을 입력하세요", id="name")
            yield Label("한글·영문 최대 24칸 · Enter 확정 · Esc 뒤로", id="hint")
            yield Label("", id="error")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#name", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        try:
            value = self._validate(event.value)
        except (TypeError, ValueError) as error:
            self.query_one("#error", Label).update(sanitize_terminal_text(str(error)))
            return
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class TextScreen(ModalScreen[None]):
    BINDINGS = [
        ("w", "scroll_up", "위"),
        ("s", "scroll_down", "아래"),
        ("enter", "close", "뒤로"),
        ("escape", "close", "뒤로"),
        ("q", "close", "뒤로"),
    ]

    def __init__(self, title: str, body_lines: Sequence[str]) -> None:
        super().__init__()
        self._title = sanitize_terminal_text(title)
        self._body = tuple(sanitize_terminal_text(line) for line in body_lines)

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Static("◆ THE GLASS FRONTIER", id="brand", markup=False)
            yield Static(self._title, id="screen-title", markup=False)
            with VerticalScroll(id="text-scroll"):
                yield Static("\n".join(self._body), markup=False)
            yield Static("W/S 스크롤 · Enter 뒤로", id="hint", markup=False)
        yield Footer()

    def action_close(self) -> None:
        self.dismiss(None)

    def action_scroll_up(self) -> None:
        self.query_one("#text-scroll", VerticalScroll).action_scroll_up()

    def action_scroll_down(self) -> None:
        self.query_one("#text-scroll", VerticalScroll).action_scroll_down()


class TextualInteraction:
    def __init__(self, app: AincradTextualApp) -> None:
        self._app = app
        self._closed = threading.Event()

    def close(self) -> None:
        self._closed.set()

    def _show(self, screen: ModalScreen[T]) -> T:
        completed = threading.Event()
        result: list[T] = []

        def receive(value: T) -> None:
            result.append(value)
            completed.set()

        self._app.call_from_thread(self._app.push_screen, screen, receive)
        while not completed.wait(0.05):
            if self._closed.is_set():
                raise EOFError("interactive terminal closed")
        return result[0]

    def choose(
        self,
        title: str,
        options: Sequence[MenuOption[T]],
        *,
        subtitle: str = "",
        context: Sequence[str] = (),
        allow_back: bool = False,
    ) -> T | None:
        index = self._show(
            MenuScreen(
                title,
                cast(Sequence[MenuOption[object]], options),
                subtitle=subtitle,
                context=context,
                allow_back=allow_back,
            )
        )
        return None if index is None else options[index].value

    def input_text(
        self,
        title: str,
        *,
        subtitle: str,
        validate: Validator,
    ) -> str | None:
        return self._show(NameScreen(title, subtitle=subtitle, validate=validate))

    def show_text(self, title: str, body_lines: Sequence[str]) -> None:
        self._show(TextScreen(title, body_lines))


class AincradTextualApp(App[int]):
    CSS = """
    Screen {
        align: center middle;
        background: #0b1118;
        color: #d8d2c4;
    }
    #dialog {
        width: 90%;
        max-width: 84;
        height: 90%;
        max-height: 30;
        border: round #d49a4a;
        background: #101923;
        padding: 1 2;
    }
    #brand {
        height: 1;
        color: #f0bd69;
        text-style: bold;
        margin-bottom: 1;
    }
    #screen-title {
        height: auto;
        color: #fff3d6;
        text-style: bold;
    }
    #subtitle, #context {
        height: auto;
        color: #9ea8b3;
        margin-bottom: 1;
    }
    ListView {
        height: 1fr;
        scrollbar-color: #d49a4a;
        scrollbar-background: #172432;
    }
    ListItem {
        height: auto;
        padding: 0 2;
        color: #c7c0b2;
    }
    ListView:focus > ListItem.-highlight {
        background: #694c2b;
        color: #fff3d6;
        text-style: bold;
    }
    #hint {
        height: auto;
        color: #9ea8b3;
        margin-top: 1;
    }
    #error {
        height: auto;
        color: #ff8f80;
    }
    Input {
        margin-top: 1;
        border: tall #6e7884;
    }
    Input:focus {
        border: tall #f0bd69;
    }
    #text-scroll {
        height: 1fr;
        margin-top: 1;
        padding-right: 2;
        scrollbar-color: #d49a4a;
        scrollbar-background: #172432;
    }
    Footer {
        background: #101923;
        color: #9ea8b3;
    }
    """

    def __init__(self, session: Session) -> None:
        super().__init__()
        self._session = session
        self._interaction = TextualInteraction(self)

    def on_mount(self) -> None:
        self.run_worker(self._run_session, thread=True, exclusive=True)

    def _run_session(self) -> None:
        try:
            exit_code = self._session(self._interaction)
        except EOFError:
            exit_code = 0
        except Exception as error:
            self.log.error(
                f"interactive session failed: {type(error).__name__}: "
                f"{sanitize_terminal_text(str(error))}"
            )
            exit_code = 1
        self.call_from_thread(self.exit, exit_code)

    def on_unmount(self) -> None:
        self._interaction.close()
