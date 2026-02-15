// Initialize KaTeX auto-render on Markdown containers.
// Delimiters: $...$, $$...$$, \(...\), \[...\]
function renderMathBlocks() {
  if (typeof renderMathInElement !== "function") return;
  document.querySelectorAll('[data-format="markdown"], [data-format="html"]').forEach((el) => {
    if (el.dataset.mathRendered === "1") return;
    renderMathInElement(el, {
      delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: "\\[", right: "\\]", display: true },
        { left: "$", right: "$", display: false },
        { left: "\\(", right: "\\)", display: false },
      ],
      ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code"],
      throwOnError: false,
    });
    el.dataset.mathRendered = "1";
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", renderMathBlocks);
} else {
  renderMathBlocks();
}

// Optional: re-render if new markdown content is injected dynamically.
const observer = new MutationObserver((mutations) => {
  for (const m of mutations) {
    if (m.addedNodes && m.addedNodes.length) {
      renderMathBlocks();
      break;
    }
  }
});
observer.observe(document.documentElement, { childList: true, subtree: true });
