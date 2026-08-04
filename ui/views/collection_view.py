"""
Collection View Tab Component for Textual TUI.
"""
from typing import List
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import DataTable, Static, Button, Input, Label, Header, Footer
from textual.reactive import reactive
from models import CollectionItem
from config import CONDITION_MULTIPLIERS


class CollectionView(Container):
    """View displaying collection list, portfolio totals, search filter, and export options."""

    def compose(self) -> ComposeResult:
        with Vertical():
            # Summary Metrics Bar
            with Horizontal(id="metrics_bar"):
                yield Static("📊 **Collezione Totale**", id="metric_title", classes="metric_card")
                yield Static("Carte Uniche: **0**", id="metric_count", classes="metric_card")
                yield Static("Totale Pezzi: **0**", id="metric_qty", classes="metric_card")
                yield Static("Valore NM Totale: **€0.00**", id="metric_val_nm", classes="metric_card_highlight")

            # Condition Breakdown Bar
            with Horizontal(id="condition_bar"):
                yield Static("Stima EX: €0.00", id="cond_ex", classes="cond_badge")
                yield Static("Stima GD: €0.00", id="cond_gd", classes="cond_badge")
                yield Static("Stima LP: €0.00", id="cond_lp", classes="cond_badge")
                yield Static("Stima PO: €0.00", id="cond_po", classes="cond_badge")

            # Action Controls
            with Horizontal(id="action_bar"):
                yield Input(placeholder="🔍 Filtra collezione per nome o set code...", id="filter_input")
                yield Input(placeholder="💰 Prezzo minimo (€)...", id="min_price_input")
                yield Button("🔄 Aggiorna Prezzi", id="btn_refresh_prices", variant="primary")
                yield Button("📥 Esporta CSV", id="btn_export_csv", variant="success")
                yield Button("🗑️ Elimina Selezionata", id="btn_delete_card", variant="error")

            # Main Collection Data Table
            yield DataTable(id="collection_table")

    def on_mount(self) -> None:
        table = self.query_one("#collection_table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        column_keys = table.add_columns(
            "ID / Passcode",
            "Nome (EN)",
            "Set Code",
            "Rarità",
            "Qtà",
            "Base NM (€)",
            "EX (€)",
            "GD (€)",
            "LP (€)",
            "PO (€)",
            "Totale (€)"
        )
        (col_id, col_name, col_set, col_rarity, col_qty,
         col_base, col_ex, col_gd, col_lp, col_po, col_total) = column_keys

        # Maps each column key to the CollectionItem attribute used to sort it.
        self._sort_extractors = {
            col_id: lambda item: item.id,
            col_name: lambda item: item.name.lower(),
            col_set: lambda item: item.set_code.lower(),
            col_rarity: lambda item: (item.rarity or "Standard").lower(),
            col_qty: lambda item: item.quantity,
            col_base: lambda item: item.base_price,
            col_ex: lambda item: item.get_price_for_condition("EX"),
            col_gd: lambda item: item.get_price_for_condition("GD"),
            col_lp: lambda item: item.get_price_for_condition("LP"),
            col_po: lambda item: item.get_price_for_condition("PO"),
            col_total: lambda item: item.total_nm_price,
        }
        self._sort_column = None
        self._sort_reverse = False
        self._last_items: List[CollectionItem] = []
        self._last_filter_text = ""
        self._last_min_price = None

    def sort_by_column(self, column_key) -> None:
        """Sort the table by the clicked column, toggling direction on repeated clicks."""
        if column_key not in self._sort_extractors:
            return
        if self._sort_column == column_key:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column_key
            self._sort_reverse = False
        self.update_table(self._last_items, self._last_filter_text, self._last_min_price)

    def update_table(self, items: List[CollectionItem], filter_text: str = "", min_price: float = None) -> None:
        """Populate or refresh table rows and summary metrics."""
        table = self.query_one("#collection_table", DataTable)
        table.clear()

        self._last_items = items
        self._last_filter_text = filter_text
        self._last_min_price = min_price

        filter_text = filter_text.strip().lower()

        filtered_items = [
            item for item in items
            if (not filter_text or filter_text in item.name.lower() or filter_text in item.set_code.lower())
            and (min_price is None or item.base_price >= min_price)
        ]

        if self._sort_column is not None:
            filtered_items = sorted(
                filtered_items,
                key=self._sort_extractors[self._sort_column],
                reverse=self._sort_reverse
            )

        total_unique = len(items)
        total_pieces = sum(item.quantity for item in items)
        total_nm_val = sum(item.total_nm_price for item in items)

        # Condition totals
        total_ex_val = sum(item.base_price * item.quantity * CONDITION_MULTIPLIERS["EX"] for item in items)
        total_gd_val = sum(item.base_price * item.quantity * CONDITION_MULTIPLIERS["GD"] for item in items)
        total_lp_val = sum(item.base_price * item.quantity * CONDITION_MULTIPLIERS["LP"] for item in items)
        total_po_val = sum(item.base_price * item.quantity * CONDITION_MULTIPLIERS["PO"] for item in items)

        # Update metrics
        self.query_one("#metric_count", Static).update(f"Carte Uniche: **{total_unique}**")
        self.query_one("#metric_qty", Static).update(f"Totale Pezzi: **{total_pieces}**")
        self.query_one("#metric_val_nm", Static).update(f"Valore NM Totale: **€{total_nm_val:.2f}**")

        self.query_one("#cond_ex", Static).update(f"Stima EX: **€{total_ex_val:.2f}**")
        self.query_one("#cond_gd", Static).update(f"Stima GD: **€{total_gd_val:.2f}**")
        self.query_one("#cond_lp", Static).update(f"Stima LP: **€{total_lp_val:.2f}**")
        self.query_one("#cond_po", Static).update(f"Stima PO: **€{total_po_val:.2f}**")

        for item in filtered_items:
            table.add_row(
                str(item.id),
                item.name,
                item.set_code,
                item.rarity or "Standard",
                str(item.quantity),
                f"€{item.base_price:.2f}",
                f"€{item.get_price_for_condition('EX'):.2f}",
                f"€{item.get_price_for_condition('GD'):.2f}",
                f"€{item.get_price_for_condition('LP'):.2f}",
                f"€{item.get_price_for_condition('PO'):.2f}",
                f"€{item.total_nm_price:.2f}",
                key=f"{item.id}_{item.set_code}_{item.rarity}"
            )
