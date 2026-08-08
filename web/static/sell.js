// Sell page: auto-fills the suggested price when a row's condition <select> changes.
// Uses event delegation on document.body (attached once) rather than binding to individual
// <select> elements, since #sell-page-content gets replaced wholesale by htmx (outerHTML) after
// every staging/confirm/resolve action — a per-element listener would need re-binding after each
// swap, delegation on a stable ancestor sidesteps that entirely.
document.body.addEventListener("change", function (event) {
  var select = event.target;
  if (!select.matches('select[name^="condition_"]')) return;

  var stagingId = select.name.slice("condition_".length);
  var priceInput = document.querySelector('input[name="price_' + stagingId + '"]');
  if (!priceInput) return;

  var prices;
  try {
    prices = JSON.parse(select.dataset.prices || "{}");
  } catch (e) {
    return;
  }

  var suggested = prices[select.value];
  if (suggested !== undefined && suggested !== null) {
    priceInput.value = suggested.toFixed(2);
  }
});
