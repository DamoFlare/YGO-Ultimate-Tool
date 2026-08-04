"""
Grading View Tab Component for Textual TUI.

Replaces the old OCR/Vision scanner placeholder with a real Hybrid Multi-Agent grading pipeline:
a deterministic OpenCV Geometric Agent (edge wear, centering) combined with a local VLM
Inspector Agent (scratches, creases) running on a self-hosted Ollama server. See
services/grading/ and .CLAUDE/07-grading.md for the full architecture and formula.
"""
from typing import List, Optional
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Static, Button, Input, Label, OptionList
from textual.widgets.option_list import Option
from models import CardSearchResult, CardSetInfo, GradingResult


class GradingView(Container):
    """View for grading a card photo (CV + local VLM) and optionally saving the result to the collection."""

    def compose(self) -> ComposeResult:
        with Vertical():
            with Vertical(classes="box_panel"):
                yield Label("[bold magenta]🩺 Grading Carta (Computer Vision + AI locale)[/bold magenta]")
                yield Static(
                    "Analizza una foto della carta fisica per stimare un grade oggettivo 1-10, stile PSA/BGS:\n"
                    "**Centering** ed **Edges** sono misurati in modo deterministico (OpenCV), **Surface** "
                    "(graffi/pieghe) da un modello Vision locale (Ollama + llava, nessun dato lascia il tuo PC).\n"
                    "⚠️ Limite noto: a differenza del PSA/BGS reale, non viene calcolato un sotto-voto separato "
                    "per i Corners (angoli).",
                    id="grading_description",
                )
                with Horizontal(id="grading_inputs"):
                    yield Input(placeholder="Percorso immagine della carta (es. /foto/carta.jpg)...", id="input_image_path")
                    yield Button("📂 Browse", id="btn_browse_image")
                    yield Button("🩺 Analizza Carta", id="btn_analyze_card", variant="primary")

                yield Static("", id="grading_output_result")

            with Vertical(id="grading_link_section", classes="box_panel"):
                yield Label("[bold green]🔗 Collega il grade a una carta della collezione:[/bold green]")
                with Horizontal(id="grading_search_bar"):
                    yield Input(placeholder="Cerca per nome, ID o codice set...", id="grading_search_input")
                    yield Button("🔎 Cerca", id="btn_grading_search", variant="primary")

                with Horizontal(id="grading_search_results_container"):
                    with Vertical(id="grading_cards_list_box", classes="box_panel"):
                        yield Label("[bold yellow]📋 Carte Trovate:[/bold yellow]")
                        yield OptionList(id="grading_found_cards_list")
                    with Vertical(id="grading_sets_list_box", classes="box_panel"):
                        yield Label("[bold yellow]🎴 Seleziona Set / Versione / Rarità:[/bold yellow]")
                        yield OptionList(id="grading_found_sets_list")

                yield Static("Analizza prima una foto per poter salvare un grade.", id="grading_save_summary")
                with Horizontal(id="grading_save_controls"):
                    yield Label("Quantità:")
                    yield Input(value="1", id="input_grading_quantity", restrict=r"[0-9]*")
                    yield Button("✅ Salva con Grade in Collezione", id="btn_grading_save", variant="success", disabled=True)

    def on_mount(self) -> None:
        self.last_result: Optional[GradingResult] = None
        self.found_cards: List[CardSearchResult] = []
        self.selected_card: Optional[CardSearchResult] = None
        self.selected_set: Optional[CardSetInfo] = None

    def display_grading_result(self, result: GradingResult) -> None:
        """Render the computed subgrades/final grade/condition after a successful analysis."""
        self.last_result = result
        output = self.query_one("#grading_output_result", Static)
        surface = result.surface_details

        output.update(
            f"[bold green]✅ Grade calcolato: {result.final_grade:.1f} / 10 → Condizione: "
            f"[b]{result.condition}[/b][/bold green]\n\n"
            f"- **Centering**: {result.centering_subgrade:.1f}/10 "
            f"(H {result.centering_ratio.get('horizontal', 50):.1f}/{100 - result.centering_ratio.get('horizontal', 50):.1f}, "
            f"V {result.centering_ratio.get('vertical', 50):.1f}/{100 - result.centering_ratio.get('vertical', 50):.1f})\n"
            f"- **Edges**: {result.edges_subgrade:.1f}/10 (usura bordo: {result.edge_wear_pct:.1f}%)\n"
            f"- **Surface**: {result.surface_subgrade:.1f}/10 "
            f"(graffi: {surface.get('scratch_severity', 'none')}, pieghe: {surface.get('crease_severity', 'none')})\n\n"
            f"ℹ️ {surface.get('details', '')}"
        )
        self.update_save_form()

    def display_analysis_error(self, message: str) -> None:
        self.last_result = None
        output = self.query_one("#grading_output_result", Static)
        output.update(f"[bold red]❌ {message}[/bold red]")
        self.update_save_form()

    def display_search_results(self, cards: List[CardSearchResult]) -> None:
        self.found_cards = cards
        cards_list = self.query_one("#grading_found_cards_list", OptionList)
        cards_list.clear_options()

        if not cards:
            cards_list.add_option(Option("Nessun risultato trovato", id="none"))
            self.clear_set_list()
            return

        for idx, card in enumerate(cards):
            cards_list.add_option(Option(f"{card.name} (ID: {card.id}) - {card.type}", id=str(idx)))
        cards_list.focus()

    def display_sets_for_card(self, card: CardSearchResult) -> None:
        self.selected_card = card
        self.selected_set = None
        sets_list = self.query_one("#grading_found_sets_list", OptionList)
        sets_list.clear_options()

        if not card.card_sets:
            sets_list.add_option(Option("Nessun set specifico disponibile per questa carta", id="none"))
            return

        for idx, cset in enumerate(card.card_sets):
            price_str = f"€{cset.set_price}" if cset.set_price else "N/A"
            sets_list.add_option(Option(f"{cset.set_code} - {cset.set_rarity} - {cset.set_name} ({price_str})", id=str(idx)))
        sets_list.focus()
        self.update_save_form()

    def clear_set_list(self) -> None:
        sets_list = self.query_one("#grading_found_sets_list", OptionList)
        sets_list.clear_options()
        self.selected_card = None
        self.selected_set = None
        self.update_save_form()

    def update_save_form(self) -> None:
        summary = self.query_one("#grading_save_summary", Static)
        btn_save = self.query_one("#btn_grading_save", Button)

        if not self.last_result:
            summary.update("Analizza prima una foto per poter salvare un grade.")
            btn_save.disabled = True
            return

        if not self.selected_card:
            summary.update("Grade pronto. Ora cerca e seleziona la carta a cui collegarlo.")
            btn_save.disabled = True
            return

        if not self.selected_set and self.selected_card.card_sets:
            summary.update(f"Selezionata: **{self.selected_card.name}**. Ora scegli una versione/set dall'elenco a destra.")
            btn_save.disabled = True
            return

        set_code = self.selected_set.set_code if self.selected_set else "PROMO"
        rarity = self.selected_set.set_rarity if self.selected_set else "Standard"
        summary.update(
            f"Carta: **{self.selected_card.name}** | Set: [b cyan]{set_code}[/b cyan] | Rarità: **{rarity}** | "
            f"Grade: **{self.last_result.final_grade:.1f}** ({self.last_result.condition})"
        )
        btn_save.disabled = False
