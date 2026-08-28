from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar, cast

from textual.app import App, ComposeResult
from textual.containers import Container, VerticalScroll
from textual.events import Key, Resize
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
                        Static(option.label, classes="option-label", markup=False),
                        Static(
                            option.description,
                            classes="option-description",
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
        self._set_compact_descriptions(self.app.size.width < 50)

    def on_resize(self, event: Resize) -> None:
        self._set_compact_descriptions(event.size.width < 50)

    def _set_compact_descriptions(self, compact: bool) -> None:
        for description in self.query(".option-description"):
            description.display = not compact

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


class TextInputScreen(ModalScreen[str | None]):
    """Single-line natural text input with caller-defined copy and validation."""

    DEFAULT_PLACEHOLDER = "자유롭게 입력하세요"
    DEFAULT_HINT = "Enter 확정 · Esc 뒤로"
    BINDINGS = [("escape", "cancel", "뒤로")]

    def __init__(
        self,
        title: str,
        *,
        subtitle: str,
        validate: Validator,
        placeholder: str = "",
        hint: str = "",
    ) -> None:
        super().__init__()
        self._title = sanitize_terminal_text(title)
        self._subtitle = sanitize_terminal_text(subtitle)
        self._validate = validate
        self._placeholder = (
            sanitize_terminal_text(placeholder) if placeholder else self.DEFAULT_PLACEHOLDER
        )
        self._hint = sanitize_terminal_text(hint) if hint else self.DEFAULT_HINT

    def compose(self) -> ComposeResult:
        with Container(id="dialog"):
            yield Static("◆ THE GLASS FRONTIER", id="brand", markup=False)
            yield Static(self._title, id="screen-title", markup=False)
            yield Static(self._subtitle, id="subtitle", markup=False)
            yield SafeInput(placeholder=self._placeholder, id="text-input")
            yield Label(self._hint, id="hint")
            yield Label("", id="error")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#text-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        try:
            value = self._validate(event.value)
        except (TypeError, ValueError) as error:
            self.query_one("#error", Label).update(sanitize_terminal_text(str(error)))
            return
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)


NameScreen = TextInputScreen


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


class StoryScreen(ModalScreen[None]):
    """Reveal one resolved hourly scene with readable typewriter cadence.

    The screen can be pushed before its content exists: pass ``body_lines=None``
    to mount a reader-friendly loading shell, then call :meth:`begin_story`
    (on the app thread) once the text is ready to start the typewriter.
    """

    CHARACTER_DELAY_SECONDS = 0.03
    PUNCTUATION_DELAY_SECONDS = 0.15
    PARAGRAPH_DELAY_SECONDS = 0.2
    LOADING_BODY = "이야기를 준비하는 중입니다…"
    LOADING_HINT = "장면을 준비하고 있습니다 · 잠시만 기다려 주세요"
    BINDINGS = [
        ("w", "scroll_up", "위"),
        ("s", "scroll_down", "아래"),
        ("enter", "advance", "전체 표시/계속"),
    ]

    def __init__(self, title: str, body_lines: Sequence[str] | None = None) -> None:
        super().__init__()
        self._title = sanitize_terminal_text(title)
        self._full_text: str | None = (
            None
            if body_lines is None
            else "\n".join(sanitize_terminal_text(line) for line in body_lines)
        )
        self._revealed_count = 0
        self._shell_visible = threading.Event()

    @property
    def is_loading(self) -> bool:
        return self._full_text is None

    @property
    def revealed_text(self) -> str:
        if self._full_text is None:
            return ""
        return self._full_text[: self._revealed_count]

    @property
    def is_complete(self) -> bool:
        return self._full_text is not None and self._revealed_count >= len(self._full_text)

    def wait_mounted(self, timeout: float) -> bool:
        """Block a worker thread until the screen is mounted and visible."""
        return self._shell_visible.wait(timeout)

    def compose(self) -> ComposeResult:
        loading = self.is_loading
        with Container(id="dialog"):
            yield Static("◆ THE GLASS FRONTIER", id="brand", markup=False)
            yield Static(self._title, id="screen-title", markup=False)
            with VerticalScroll(id="text-scroll"):
                yield Static(
                    self.LOADING_BODY if loading else "",
                    id="story-text",
                    markup=False,
                )
            yield Static(
                self.LOADING_HINT if loading else "한 글자씩 재생 중 · Enter 전체 표시",
                id="hint",
                markup=False,
            )
        yield Footer()

    def on_mount(self) -> None:
        if not self.is_loading:
            self.set_timer(self.CHARACTER_DELAY_SECONDS, self._reveal_next)
        self._shell_visible.set()

    def begin_story(self, body_lines: Sequence[str]) -> None:
        """Swap the loading shell for real content and start the typewriter."""
        self._full_text = "\n".join(sanitize_terminal_text(line) for line in body_lines)
        self._revealed_count = 0
        self.query_one("#story-text", Static).update("")
        self.query_one("#hint", Static).update("한 글자씩 재생 중 · Enter 전체 표시")
        self.set_timer(self.CHARACTER_DELAY_SECONDS, self._reveal_next)

    def _reveal_next(self) -> None:
        if self._full_text is None or self.is_complete:
            return
        self._revealed_count += 1
        self.query_one("#story-text", Static).update(self.revealed_text)
        self.query_one("#text-scroll", VerticalScroll).scroll_end(animate=False)
        if self.is_complete:
            self._show_continue_hint()
            return
        character = self.revealed_text[-1]
        delay = (
            self.PARAGRAPH_DELAY_SECONDS
            if character == "\n"
            else self.PUNCTUATION_DELAY_SECONDS
            if character in ".!?。！？…"
            else self.CHARACTER_DELAY_SECONDS
        )
        self.set_timer(delay, self._reveal_next)

    def _show_continue_hint(self) -> None:
        self.query_one("#hint", Static).update("W/S 스크롤 · Enter 계속")

    def action_advance(self) -> None:
        if self.is_loading:
            return
        if not self.is_complete:
            self._revealed_count = len(self._full_text or "")
            self.query_one("#story-text", Static).update(self.revealed_text)
            self.query_one("#text-scroll", VerticalScroll).scroll_end(animate=False)
            self._show_continue_hint()
            return
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
        placeholder: str = "",
        hint: str = "",
    ) -> str | None:
        return self._show(
            TextInputScreen(
                title,
                subtitle=subtitle,
                validate=validate,
                placeholder=placeholder,
                hint=hint,
            )
        )

    def show_text(self, title: str, body_lines: Sequence[str]) -> None:
        self._show(TextScreen(title, body_lines))

    def show_story(self, title: str, body_lines: Sequence[str]) -> None:
        self._show(StoryScreen(title, body_lines))

    def show_story_from(
        self,
        title: str,
        producer: Callable[[], Sequence[str]],
    ) -> None:
        """Push a visible loading story shell, then reveal producer's text.

        The StoryScreen is pushed and mounted BEFORE ``producer`` runs, so a
        slow provider never leaves the previous screen looking frozen. The
        producer executes on the calling session worker thread; the mounted
        screen is updated via the Textual app thread. If ``producer`` raises,
        the loading screen is dismissed and the exception propagates to the
        caller, which may then fall back to :meth:`show_story`.
        """
        screen = StoryScreen(title, None)
        completed = threading.Event()

        def receive(_value: None) -> None:
            completed.set()

        self._app.call_from_thread(self._app.push_screen, screen, receive)
        while not screen.wait_mounted(0.05):
            if self._closed.is_set():
                raise EOFError("interactive terminal closed")
        try:
            body_lines = tuple(producer())
        except BaseException:
            self._app.call_from_thread(screen.dismiss, None)
            completed.wait(2.0)
            raise
        self._app.call_from_thread(screen.begin_story, body_lines)
        while not completed.wait(0.05):
            if self._closed.is_set():
                raise EOFError("interactive terminal closed")


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
        margin-bottom: 1;
        color: #c7c0b2;
    }
    ListItem:last-of-type {
        margin-bottom: 0;
    }
    .option-label, .option-description {
        height: auto;
    }
    .option-description {
        color: #9ea8b3;
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
