"""
Entry point for Yu-Gi-Oh! TCG Valuer & Collection Tracker CLI Application.
"""
from ui.app import YGOValuerApp


def main():
    """Launch the Textual TUI Application."""
    app = YGOValuerApp()
    app.run()


if __name__ == "__main__":
    main()
