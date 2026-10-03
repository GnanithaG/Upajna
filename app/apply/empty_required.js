// Runs inside the page: return the keys of required fields that are still empty.
(keys) => {
  const missing = [];
  for (const key of keys) {
    const els = [...document.querySelectorAll(`[data-od-key="${key}"]`)];
    if (!els.length) continue;
    const el = els[0];
    const t = (el.getAttribute("type") || "").toLowerCase();
    let filled;
    if (t === "radio" || t === "checkbox") filled = els.some((e) => e.checked);
    else if (t === "file") filled = el.files && el.files.length > 0;
    else if (el.getAttribute("role") === "combobox") {
      const box = el.closest("[class*='select'], [class*='Select'], div");
      filled = !!(el.value || box?.querySelector("[class*='single-value'], [class*='singleValue'], [class*='multi-value']"));
    } else filled = !!String(el.value || "").trim();
    if (!filled) missing.push(key);
  }
  return missing;
}
