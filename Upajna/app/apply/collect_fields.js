// Runs inside the page: list every form field with its label, type, options and required flag.
(scopeSelector) => {
  const root = (scopeSelector && document.querySelector(scopeSelector)) || document;
  const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return (r.width > 0 || r.height > 0 || el.type === "file") && s.visibility !== "hidden" && s.display !== "none"; };
  const clean = (t) => String(t || "").replace(/\s+/g, " ").replace(/\*/g, "").trim().slice(0, 300);
  const labelOf = (el) => {
    if (el.getAttribute("aria-label")) return clean(el.getAttribute("aria-label"));
    const lb = el.getAttribute("aria-labelledby");
    if (lb) { const t = lb.split(" ").map((i) => document.getElementById(i)?.innerText || "").join(" "); if (clean(t)) return clean(t); }
    if (el.id) { const l = root.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return clean(l.innerText); }
    const wrap = el.closest("label"); if (wrap) return clean(wrap.innerText);
    const box = el.closest(".field, .application-question, .form-group, [class*='field'], [class*='Field'], li, fieldset, div");
    const l2 = box?.querySelector("label, legend, .text, [class*='label'], [class*='Label']");
    return clean(l2?.innerText || el.placeholder || el.name || el.id);
  };
  const out = []; const radios = {}; let n = 0;
  const els = root.querySelectorAll("input, textarea, select, [role='combobox']");
  for (const el of els) {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute("role") === "combobox" && tag !== "select" ? "combobox" : (el.getAttribute("type") || (tag === "select" ? "select" : tag === "textarea" ? "textarea" : "text"))).toLowerCase();
    if (["hidden", "submit", "button", "reset", "image", "search"].includes(type)) continue;
    if (type !== "file" && !visible(el)) continue;
    const key = `f${n++}`;
    el.setAttribute("data-od-key", key);
    const required = el.required || el.getAttribute("aria-required") === "true" || /\*/.test(el.closest("div, li, fieldset")?.querySelector("label, legend")?.innerText || "");
    if (type === "radio") {
      const group = el.name || key;
      const optLabel = clean(el.closest("label")?.innerText || root.querySelector(`label[for="${CSS.escape(el.id || "_")}"]`)?.innerText || el.value);
      if (!radios[group]) {
        const fs = el.closest("fieldset, [role='radiogroup'], .field, div");
        radios[group] = { key, group, type: "radio", label: clean(fs?.querySelector("legend, label, [class*='label']")?.innerText || group), required, options: [] };
        out.push(radios[group]);
      }
      radios[group].options.push(optLabel);
      el.setAttribute("data-od-key", radios[group].key);
      el.setAttribute("data-od-opt", optLabel);
      continue;
    }
    const f = { key, type, label: labelOf(el), required, name: el.name || el.id || "" };
    if (tag === "select") f.options = [...el.options].map((o) => clean(o.text)).filter((t) => t && !/^select|^--/i.test(t)).slice(0, 60);
    if (type === "file") f.accept = el.accept || "";
    out.push(f);
  }
  return out;
}
