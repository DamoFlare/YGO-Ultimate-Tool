"""
Scan View Tab Component for Textual TUI (Vision / OCR Placeholder).
"""
from pathlib import Path
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Static, Button, Input, Label
from services.scanner import CardScannerService


class ScannerView(Container):
    """View presenting the Image Scanner / OCR Multimodal Vision integration placeholder."""

    def compose(self) -> ComposeResult:
        with Vertical(classes="box_panel"):
            yield Label("[bold magenta]📷 Modulo Vision / OCR Card Scanner (WIP / Ready)[/bold magenta]")
            yield Static(
                "Questa funzionalità permette di caricare un'immagine di una carta Yu-Gi-Oh!\n"
                "ed estrarre automaticamente **Nome** e **Codice Set** tramite Vision AI (es. GPT-4o / Gemini Flash / Claude Vision) "
                "o OCR locale (`easyocr` / `pytesseract`).\n\n"
                "**Specifica Architetturale:**\n"
                "1. L'immagine viene analizzata ritagliando il Box del Codice Set (in basso a destra sotto l'artwork) o inviata via API Multimodale.\n"
                "2. I dati estratti (`set_code`, `name`, `passcode`) vengono inoltrati automaticamente al Modulo 1 (YGOPRODeck API) per la ricerca esatta.",
                id="scanner_description"
            )

            with Horizontal(id="scanner_inputs"):
                yield Input(placeholder="Inserisci il percorso dell'immagine (es. C:\\carte\\dark_magician.jpg)...", id="input_image_path")
                yield Button("🔍 Analizza Immagine", id="btn_scan_image", variant="primary")

            yield Static("", id="scanner_output_result")

    async def run_scan(self, image_path_str: str) -> None:
        """Run simulated scan process using CardScannerService."""
        output = self.query_one("#scanner_output_result", Static)
        if not image_path_str.strip():
            output.update("[bold red]❌ Per favore inserisci un percorso file valido.[/bold red]")
            return

        scanner = CardScannerService()
        result = await scanner.scan_card_image(Path(image_path_str))

        if result.get("success"):
            data = result["extracted_data"]
            output.update(
                f"[bold green]✅ Analisi completata ({result['status']}):[/bold green]\n"
                f"- **Nome estratto**: {data['name']}\n"
                f"- **Set Code estratto**: {data['set_code']}\n"
                f"- **Passcode estratto**: {data['passcode']}\n\n"
                f"ℹ️ {result['message']}"
            )
        else:
            output.update(f"[bold red]❌ Errore: {result.get('error')}[/bold red]")
