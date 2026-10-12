/*
 * Shared, behaviour-preserving UI helpers (code-quality audit A-5).
 *
 * Loaded as a classic <script> BEFORE each page's inline script, so the
 * window.WFS globals below are defined before any call site runs. Each page
 * keeps its own local escapeHtml wrapper and delegates here, reproducing its
 * previous output byte-for-byte via the per-call options. That collapses the
 * duplicated XSS guard into a single source of truth without changing any
 * page's contract.
 */
(function () {
  "use strict";
  var WFS = (window.WFS = window.WFS || {});

  /*
   * Escape a value for safe interpolation into innerHTML.
   *
   * Options (both default off, so behaviour matches the caller that passes
   * them explicitly):
   *   nullToEmpty       — map null/undefined to "" (risk_panel contract);
   *                       when false the raw String(value) is used, so null
   *                       becomes "null" (operator_map contract).
   *   escapeApostrophe  — also replace ' with &#39; (operator_map escaped the
   *                       apostrophe; risk_panel did not).
   */
  WFS.escapeHtml = function (value, options) {
    var opts = options || {};
    var text;
    if (value == null) {
      text = opts.nullToEmpty ? "" : String(value);
    } else {
      text = String(value);
    }
    var out = text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
    if (opts.escapeApostrophe) {
      out = out.replace(/'/g, "&#39;");
    }
    return out;
  };
})();
