"""
Bulk Add View Tab Component for Textual TUI.
"""
from typing import List, Optional, Dict
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Static, Button, Input, Label, OptionList, TextArea
from textual.widgets.option_list import Option
from models import CardSearchResult, CardSetInfo, CollectionItem
from services.ygoprodeck_api import YGOProDeckAPI


class BulkAddView(Container):
    """
    View for adding multiple cards at once by set code.
    Steps:
    1. Paste set codes (separated by spaces or newlines).
    2. App fetches possible printings for each.
    3. User picks the correct set/printing for each found card.
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[bold cyan]🚀 Aggiunta Bulk (per Codice Set)[/bold cyan]")
            yield Label("Inserisci i codici set separati da spazio o invio (es: RA01-IT001 LOB-EN001):")
            
            # Input Area
            yield TextArea(id="bulk_input_area", show_line_numbers=True)
            yield Button("🔍 Carica Carte", id="btn_bulk_load", variant="primary")

            # Processing section (hidden until load)
            with Vertical(id="bulk_process_section", classes="box_panel"):
                yield Label("[bold yellow]⚖️ Configura le carte trovate:[/bold yellow]")
                yield Static("Nessuna coda attiva.", id="bulk_status_label")
                
                with Horizontal(id="bulk_selector_container"):
                    with Vertical(id="queue_list_box"):
                        yield Label("Coda:")
                        yield OptionList(id="bulk_queue_option_list")
                    
                    with Vertical(id="bulk_set_picker_box"):
                        yield Label("Seleziona Versione/Rarità Corretta:")
                        yield OptionList(id="bulk_set_option_list")

                with Horizontal(id="bulk_actions"):
                    yield Button("✅ Aggiungi Selezionata", id="btn_bulk_add_current", variant="success", disabled=True)
                    yield Button("⏭️ Salta", id="btn_bulk_skip", variant="warning", disabled=True)
                    yield Button("💾 Salva Collezione", id="btn_bulk_save_all", variant="primary")

    def on_mount(self) -> None:
        self.queue: List[Dict] = []  # List of {query: str, results: List[CardSearchResult]}
        self.current_index: int = -1

    def start_processing(self, queue: List[Dict]) -> None:
        """Initialize the processing queue UI."""
        self.queue = queue
        self.current_index = 0
        self.update_queue_list()
        self.show_current_item()

    def update_queue_list(self) -> None:
        queue_list = self.query_one("#bulk_queue_option_list", OptionList)
        queue_list.clear_options()
        for i, item in enumerate(self.queue):
            status = "✅" if item.get("added") else ("⏭️" if item.get("skipped") else "⏳")
            query = item["query"]
            queue_list.add_option(Option(f"{status} {query}", id=str(i)))

    def show_current_item(self) -> None:
        status_label = self.query_one("#bulk_status_label", Static)
        set_list = self.query_one("#bulk_set_option_list", OptionList)
        btn_add = self.query_one("#btn_bulk_add_current", Button)
        btn_skip = self.query_one("#btn_bulk_skip", Button)
        
        set_list.clear_options()

        if 0 <= self.current_index < len(self.queue):
            item = self.queue[self.current_index]
            query = item["query"]
            results = item["results"]
            
            if not results:
                status_label.update(f"Nessun risultato per: [bold red]{query}[/bold red]")
                set_list.add_option(Option("Nessun set trovato per questo codice", id="none"))
                btn_add.disabled = True
            else:
                card = results[0] # Usually one card per specific set code
                status_label.update(f"Configurazione: [bold cyan]{card.name}[/bold cyan] ({query})")
                
                # Filter sets to match the query code or just show all if ambiguity
                for idx, cset in enumerate(card.card_sets):
                    price_str = f"€{cset.set_price}" if cset.set_price else "N/A"
                    label = f"{cset.set_code} - {cset.set_rarity} - {cset.set_name} ({price_str})"
                    set_list.add_option(Option(label, id=str(idx)))
                
                btn_add.disabled = False
            
            btn_skip.disabled = False
        else:
            status_label.update("Tutte le carte processate.")
            btn_add.disabled = True
            btn_skip.disabled = True
