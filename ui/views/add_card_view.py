"""
Add Card View Tab Component for Textual TUI.
"""
from typing import List, Optional
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import DataTable, Static, Button, Input, Label, OptionList, Select
from textual.widgets.option_list import Option
from models import CardSearchResult, CardSetInfo, CollectionItem


class AddCardView(Container):
    """View for searching cards via API, selecting exact set/printing, and adding to collection."""

    def compose(self) -> ComposeResult:
        with Vertical():
            # Search Input Bar
            yield Label("[bold cyan]🔍 Cerca Carta Yu-Gi-Oh![/bold cyan] (Nome IT/EN, Passcode ID o Codice Set es. 'RA01-EN001' o 'Mago Nero'):")
            with Horizontal(id="search_bar"):
                yield Input(placeholder="Inserisci nome, ID o codice set...", id="card_search_input")
                yield Button("🔎 Cerca", id="btn_do_search", variant="primary")

            # Search Results Dropdown/List & Set Picker Section
            with Horizontal(id="search_results_container"):
                with Vertical(id="cards_list_box", classes="box_panel"):
                    yield Label("[bold yellow]📋 Carte Trovate:[/bold yellow]")
                    yield OptionList(id="found_cards_option_list")

                with Vertical(id="sets_list_box", classes="box_panel"):
                    yield Label("[bold yellow]🎴 Seleziona Set / Versione / Rarità:[/bold yellow]")
                    yield OptionList(id="found_sets_option_list")

            # Card Details & Add Form
            with Vertical(id="card_add_form", classes="box_panel"):
                yield Label("[bold green]➕ Aggiungi alla Collezione:[/bold green]")
                yield Static("Nessuna carta/set selezionato.", id="selected_card_summary")
                with Horizontal(id="add_controls"):
                    yield Label("Quantità:")
                    yield Input(value="1", id="input_quantity", restrict=r"[0-9]*")
                    yield Button("✅ Aggiungi alla Collezione", id="btn_confirm_add", variant="success", disabled=True)

    def on_mount(self) -> None:
        self.found_cards: List[CardSearchResult] = []
        self.selected_card: Optional[CardSearchResult] = None
        self.selected_set: Optional[CardSetInfo] = None

    def display_search_results(self, cards: List[CardSearchResult]) -> None:
        """Populate found cards option list."""
        self.found_cards = cards
        cards_list = self.query_one("#found_cards_option_list", OptionList)
        cards_list.clear_options()

        if not cards:
            cards_list.add_option(Option("Nessun risultato trovato", id="none"))
            self.clear_set_list()
            return

        for idx, card in enumerate(cards):
            label_text = f"{card.name} (ID: {card.id}) - {card.type}"
            cards_list.add_option(Option(label_text, id=str(idx)))

        cards_list.focus()

    def display_sets_for_card(self, card: CardSearchResult) -> None:
        """Populate sets list for the chosen card."""
        self.selected_card = card
        self.selected_set = None
        sets_list = self.query_one("#found_sets_option_list", OptionList)
        sets_list.clear_options()

        if not card.card_sets:
            sets_list.add_option(Option("Nessun set specifico disponibile per questa carta", id="none"))
            return

        for idx, cset in enumerate(card.card_sets):
            # Mostra il codice set in modo molto visibile (es: SDMM-IT014). Niente prezzo qui:
            # il prezzo reale viene da CardTrader solo al momento del salvataggio (vedi
            # update_add_form), non dal set_price di YGOPRODeck.
            label_text = f"{cset.set_code} - {cset.set_rarity} - {cset.set_name}"
            sets_list.add_option(Option(label_text, id=str(idx)))

        sets_list.focus()
        self.update_add_form()

    def clear_set_list(self) -> None:
        sets_list = self.query_one("#found_sets_option_list", OptionList)
        sets_list.clear_options()
        self.selected_card = None
        self.selected_set = None
        self.update_add_form()

    def update_add_form(self) -> None:
        summary = self.query_one("#selected_card_summary", Static)
        btn_add = self.query_one("#btn_confirm_add", Button)

        if not self.selected_card:
            summary.update("Seleziona una carta e una versione/set per procedere.")
            btn_add.disabled = True
            return

        if not self.selected_set and self.selected_card.card_sets:
            summary.update(f"Selezionata: **{self.selected_card.name}**. Ora seleziona una versione/set dall'elenco a destra.")
            btn_add.disabled = True
            return

        set_code = self.selected_set.set_code if self.selected_set else "PROMO"
        rarity = self.selected_set.set_rarity if self.selected_set else "Standard"

        # Il prezzo reale (CardTrader) viene cercato solo al momento del salvataggio in
        # add_card_to_collection_logic — qui non mostriamo alcuna stima YGOPRODeck.
        summary.update(
            f"Carta: **{self.selected_card.name}** | Codice Set: [b cyan]{set_code}[/b cyan] | Rarità: **{rarity}** | "
            f"Prezzo: verrà recuperato da CardTrader al salvataggio"
        )
        btn_add.disabled = False
