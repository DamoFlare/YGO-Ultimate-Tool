"""
Main Textual Application for Yu-Gi-Oh! TCG Valuer.
"""
from typing import List
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, TabbedContent, TabPane, Input, Button, OptionList, DataTable, Static
from textual.widgets.option_list import Option
from services.ygoprodeck_api import YGOProDeckAPI
from services.storage import StorageService
from models import CollectionItem, CardSearchResult, CardSetInfo
from ui.views.collection_view import CollectionView
from ui.views.add_card_view import AddCardView
from ui.views.bulk_add_view import BulkAddView
from ui.views.scanner_view import ScannerView


CSS = """
Screen {
    background: $surface;
}

#metrics_bar {
    height: 3;
    margin: 1 0;
}

.metric_card {
    border: solid $primary;
    padding: 0 1;
    margin-right: 1;
    content-align: center middle;
}

.metric_card_highlight {
    border: double $success;
    background: $success 10%;
    padding: 0 1;
    content-align: center middle;
    text-style: bold;
}

#condition_bar {
    height: 3;
    margin-bottom: 1;
}

.cond_badge {
    border: round $secondary;
    padding: 0 1;
    margin-right: 1;
    content-align: center middle;
}

#action_bar {
    height: 3;
    margin-bottom: 1;
}

#filter_input {
    width: 2fr;
    margin-right: 1;
}

#min_price_input {
    width: 1fr;
    margin-right: 1;
}

#btn_refresh_prices, #btn_export_csv, #btn_delete_card {
    margin-right: 1;
}

#search_bar {
    height: 3;
    margin: 1 0;
}

#card_search_input {
    width: 3fr;
    margin-right: 1;
}

#search_results_container {
    height: 15;
    margin-bottom: 1;
}

.box_panel {
    border: solid $accent;
    padding: 1;
    margin: 0 1 1 0;
}

#cards_list_box {
    width: 1fr;
}

#sets_list_box {
    width: 1fr;
}

#card_add_form {
    height: 8;
}

#add_controls {
    height: 3;
    margin-top: 1;
}

#bulk_input_area {
    height: 6;
    margin: 1 0;
}

#bulk_process_section {
    height: 25;
}

#bulk_selector_container {
    height: 15;
    margin: 1 0;
}

#queue_list_box {
    width: 1fr;
    margin-right: 1;
}

#bulk_set_picker_box {
    width: 2fr;
}

#bulk_actions {
    height: 3;
}

#input_quantity {
    width: 10;
    margin: 0 1;
}

#scanner_inputs {
    height: 3;
    margin: 1 0;
}

#input_image_path {
    width: 3fr;
    margin-right: 1;
}

#scanner_output_result {
    margin-top: 1;
    padding: 1;
    border: dashed $warning;
}
"""


class YGOValuerApp(App):
    """Yu-Gi-Oh! TCG Valuer & Collection Tracker TUI Application."""

    CSS = CSS
    TITLE = "Yu-Gi-Oh! TCG Valuer & Collection Tracker"
    SUB_TITLE = "YGOPRODeck & Cardmarket Price Engine"

    def __init__(self):
        super().__init__()
        self.api = YGOProDeckAPI()
        self.storage = StorageService()
        self.collection: List[CollectionItem] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="tab_collection"):
            with TabPane("📋 Collezione & Valutazione", id="tab_collection"):
                yield CollectionView(id="collection_view")
            with TabPane("➕ Aggiungi Carta", id="tab_add"):
                yield AddCardView(id="add_card_view")
            with TabPane("🚀 Aggiunta Bulk", id="tab_bulk"):
                yield BulkAddView(id="bulk_add_view")
            with TabPane(" Scan da Immagine (OCR/Vision)", id="tab_scan"):
                yield ScannerView(id="scanner_view")
        yield Footer()

    def on_mount(self) -> None:
        """App initialization: load existing collection."""
        self.collection = self.storage.load_collection()
        collection_view = self.query_one("#collection_view", CollectionView)
        collection_view.update_table(self.collection)

    # --- EVENT HANDLERS: Collection View ---

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id in ("filter_input", "min_price_input"):
            collection_view = self.query_one("#collection_view", CollectionView)
            filter_text = self.query_one("#filter_input", Input).value

            min_price_str = self.query_one("#min_price_input", Input).value.strip()
            min_price = None
            if min_price_str:
                try:
                    min_price = float(min_price_str.replace(",", "."))
                except ValueError:
                    min_price = None

            collection_view.update_table(self.collection, filter_text=filter_text, min_price=min_price)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id

        if button_id == "btn_refresh_prices":
            await self.refresh_all_prices()

        elif button_id == "btn_export_csv":
            if self.storage.export_to_csv(self.collection):
                self.notify(f"Esportazione riuscita in '{self.storage.csv_path}'!", title="CSV Export", severity="information")
            else:
                self.notify("Errore durante l'esportazione CSV.", title="Errore Export", severity="error")

        elif button_id == "btn_delete_card":
            self.delete_selected_card()

        elif button_id == "btn_do_search":
            await self.perform_card_search()

        elif button_id == "btn_confirm_add":
            self.add_selected_card_to_collection()

        elif button_id == "btn_bulk_load":
            await self.perform_bulk_load()

        elif button_id == "btn_bulk_add_current":
            self.process_bulk_add_current()

        elif button_id == "btn_bulk_skip":
            self.process_bulk_skip()

        elif button_id == "btn_bulk_save_all":
            self.commit_bulk_collection()

        elif button_id == "btn_scan_image":
            image_path_str = self.query_one("#input_image_path", Input).value
            scanner_view = self.query_one("#scanner_view", ScannerView)
            await scanner_view.run_scan(image_path_str)

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        if event.data_table.id == "collection_table":
            collection_view = self.query_one("#collection_view", CollectionView)
            collection_view.sort_by_column(event.column_key)

    def delete_selected_card(self) -> None:
        """Delete currently selected row in collection table."""
        collection_view = self.query_one("#collection_view", CollectionView)
        table = collection_view.query_one("#collection_table", DataTable)
        try:
            row_key, _ = table.get_row_at(table.cursor_row)
            # row_key value string form: "id_setcode_rarity"
            key_str = str(row_key.value)
            parts = key_str.split("_")
            card_id = int(parts[0])
            set_code = parts[1] if len(parts) > 1 else ""

            self.collection = [
                item for item in self.collection
                if not (item.id == card_id and item.set_code == set_code)
            ]
            self.storage.save_collection(self.collection)
            collection_view.update_table(self.collection)
            self.notify("Carta rimossa dalla collezione.", title="Eliminata", severity="warning")
        except Exception as e:
            self.notify("Nessuna riga selezionata o errore nell'eliminazione.", title="Seleziona riga", severity="error")

    async def refresh_all_prices(self) -> None:
        """Re-query YGOPRODeck API for all unique cards in collection to update prices."""
        if not self.collection:
            self.notify("La collezione è vuota.", title="Aggiornamento Prezzi")
            return

        self.notify("Aggiornamento prezzi in corso da YGOPRODeck...", title="Aggiornamento API", severity="information")
        updated_count = 0
        for item in self.collection:
            results = await self.api.get_card_by_id(item.id)
            if results:
                card = results[0]
                # Find base price matching set or general cardmarket price
                new_price = 0.0
                for cset in card.card_sets:
                    if cset.set_code.upper() == item.set_code.upper() and cset.set_price:
                        try:
                            new_price = float(cset.set_price)
                            break
                        except ValueError:
                            pass
                if new_price == 0.0 and card.card_prices:
                    new_price = card.card_prices[0].cardmarket_price

                if new_price > 0.0:
                    item.base_price = new_price
                    updated_count += 1

        self.storage.save_collection(self.collection)
        collection_view = self.query_one("#collection_view", CollectionView)
        collection_view.update_table(self.collection)
        self.notify(f"Prezzi aggiornati per {updated_count} carte!", title="Completato", severity="information")

    # --- EVENT HANDLERS: Add Card View ---

    async def perform_card_search(self) -> None:
        search_input = self.query_one("#card_search_input", Input)
        query_text = search_input.value.strip()
        if not query_text:
            self.notify("Inserisci un termine di ricerca.", title="Campo vuoto", severity="warning")
            return

        self.notify(f"Ricerca API per '{query_text}'...", title="Ricerca in corso")
        results = await self.api.search_cards(query_text)

        add_view = self.query_one("#add_card_view", AddCardView)
        add_view.display_search_results(results)

        if not results:
            self.notify("Nessuna carta trovata con questo termine.", title="Esito Ricerca", severity="error")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_list_id = event.option_list.id
        add_view = self.query_one("#add_card_view", AddCardView)

        if option_list_id == "found_cards_option_list":
            opt_id = event.option.id
            if opt_id != "none" and opt_id.isdigit():
                idx = int(opt_id)
                if idx < len(add_view.found_cards):
                    selected_card = add_view.found_cards[idx]
                    add_view.display_sets_for_card(selected_card)

        elif option_list_id == "found_sets_option_list":
            opt_id = event.option.id
            if opt_id != "none" and opt_id.isdigit() and add_view.selected_card:
                idx = int(opt_id)
                if idx < len(add_view.selected_card.card_sets):
                    add_view.selected_set = add_view.selected_card.card_sets[idx]
                    add_view.update_add_form()

    def add_selected_card_to_collection(self) -> None:
        add_view = self.query_one("#add_card_view", AddCardView)
        if not add_view.selected_card:
            return

        qty_input = self.query_one("#input_quantity", Input)
        try:
            qty = int(qty_input.value)
            if qty <= 0:
                qty = 1
        except ValueError:
            qty = 1

        self.add_card_to_collection_logic(add_view.selected_card, add_view.selected_set, qty)
        self.storage.save_collection(self.collection)
        self.notify(f"Aggiunta '{add_view.selected_card.name}' x{qty} alla collezione!", title="Carta Salvata", severity="information")

    async def action_quit(self) -> None:
        """Close API client session on quit."""
        await self.api.close()
        self.exit()

    # --- BULK ADD LOGIC ---

    async def perform_bulk_load(self) -> None:
        bulk_view = self.query_one("#bulk_add_view", BulkAddView)
        input_area = self.query_one("#bulk_input_area")
        raw_text = input_area.text.strip()
        
        if not raw_text:
            self.notify("Inserisci almeno un codice set.", title="Input Vuoto", severity="warning")
            return

        # Split by whitespace or newline
        codes = [c.strip() for c in raw_text.replace("\n", " ").split(" ") if c.strip()]
        self.notify(f"Caricamento di {len(codes)} codici...", title="Bulk Load")
        
        queue = []
        for code in codes:
            results = await self.api.search_cards(code)
            queue.append({"query": code, "results": results, "added": False, "skipped": False})
        
        bulk_view.start_processing(queue)

    def process_bulk_add_current(self) -> None:
        bulk_view = self.query_one("#bulk_add_view", BulkAddView)
        idx = bulk_view.current_index
        if idx < 0 or idx >= len(bulk_view.queue):
            return

        item = bulk_view.queue[idx]
        set_list = self.query_one("#bulk_set_option_list", OptionList)
        
        selected_option = set_list.highlighted
        if selected_option is None:
            self.notify("Seleziona una versione/rarità prima di aggiungere.", title="Selezione Mancante", severity="warning")
            return

        card = item["results"][0]
        selected_set = card.card_sets[selected_option]
        
        # Reuse logic for adding to collection (staged in memory only, not yet saved to disk)
        self.add_card_to_collection_logic(card, selected_set)

        item["added"] = True
        self.advance_bulk_queue()

    def commit_bulk_collection(self) -> None:
        """Persist the in-memory collection to disk, confirming the bulk-add queue contents."""
        if self.storage.save_collection(self.collection):
            self.notify("Collezione salvata su collection.json!", title="Salvataggio Confermato", severity="information")
        else:
            self.notify("Errore durante il salvataggio della collezione.", title="Errore", severity="error")

    def process_bulk_skip(self) -> None:
        bulk_view = self.query_one("#bulk_add_view", BulkAddView)
        idx = bulk_view.current_index
        if idx < 0 or idx >= len(bulk_view.queue):
            return

        bulk_view.queue[idx]["skipped"] = True
        self.advance_bulk_queue()

    def advance_bulk_queue(self) -> None:
        bulk_view = self.query_one("#bulk_add_view", BulkAddView)
        bulk_view.current_index += 1
        bulk_view.update_queue_list()
        bulk_view.show_current_item()

    def add_card_to_collection_logic(self, card: CardSearchResult, selected_set: CardSetInfo, qty: int = 1) -> None:
        set_code = selected_set.set_code if selected_set else "PROMO"
        set_name = selected_set.set_name if selected_set else ""
        rarity = selected_set.set_rarity if selected_set else "Standard"

        base_price = 0.0
        if selected_set and selected_set.set_price:
            try:
                base_price = float(selected_set.set_price)
            except ValueError:
                base_price = 0.0

        if base_price == 0.0 and card.card_prices:
            base_price = card.card_prices[0].cardmarket_price

        existing_item = next(
            (item for item in self.collection if item.id == card.id and item.set_code == set_code and item.rarity == rarity),
            None
        )

        if existing_item:
            existing_item.quantity += qty
            existing_item.base_price = base_price
        else:
            new_item = CollectionItem(
                id=card.id,
                name=card.name,
                set_code=set_code,
                set_name=set_name,
                rarity=rarity,
                base_price=base_price,
                quantity=qty
            )
            self.collection.append(new_item)

        collection_view = self.query_one("#collection_view", CollectionView)
        collection_view.update_table(self.collection)
