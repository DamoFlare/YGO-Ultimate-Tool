"""
Modal screen for browsing the local filesystem and picking an image file. Used by the Grading
tab's "Browse" button as an alternative to typing the image path manually.
"""
from pathlib import Path
from typing import Iterable, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Label, Static

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff"}


class ImageDirectoryTree(DirectoryTree):
    """DirectoryTree filtered to show only directories and common image file types."""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [p for p in paths if p.is_dir() or p.suffix.lower() in IMAGE_EXTENSIONS]


class ImagePickerScreen(ModalScreen[Optional[str]]):
    """Lets the user browse the filesystem and pick an image file.

    Dismisses with the chosen path as a string, or None if cancelled.
    """

    CSS = """
    ImagePickerScreen {
        align: center middle;
    }

    #picker_dialog {
        width: 80%;
        height: 80%;
        border: thick $accent;
        background: $surface;
        padding: 1;
    }

    #picker_tree {
        height: 1fr;
    }

    #picker_selected_path {
        height: 3;
        border: solid $primary;
        padding: 0 1;
        margin-top: 1;
    }

    #picker_actions {
        height: 3;
        margin-top: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Annulla")]

    def __init__(self, start_path: Optional[Path] = None):
        super().__init__()
        self.start_path = start_path or Path.home()
        self.selected_path: Optional[Path] = None

    def compose(self) -> ComposeResult:
        with Vertical(id="picker_dialog"):
            yield Label("[bold]📂 Seleziona un'immagine[/bold]")
            yield ImageDirectoryTree(str(self.start_path), id="picker_tree")
            yield Static("Nessun file selezionato.", id="picker_selected_path")
            with Horizontal(id="picker_actions"):
                yield Button("✅ Seleziona", id="btn_picker_confirm", variant="success", disabled=True)
                yield Button("❌ Annulla", id="btn_picker_cancel", variant="error")

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        self.selected_path = event.path
        self.query_one("#picker_selected_path", Static).update(str(self.selected_path))
        self.query_one("#btn_picker_confirm", Button).disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn_picker_confirm" and self.selected_path:
            self.dismiss(str(self.selected_path))
        elif event.button.id == "btn_picker_cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
