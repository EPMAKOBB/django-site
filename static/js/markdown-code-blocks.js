(function () {
  const getCodeBlocks = () =>
    document.querySelectorAll('[data-format="markdown"] pre > code');

  const iconCopy =
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M16 1H4a2 2 0 0 0-2 2v14h2V3h12V1zm3 4H8a2 2 0 0 0-2 2v16h13a2 2 0 0 0 2-2V5zm0 16H8V7h11v14z"/></svg>';

  const fallbackCopy = (text) =>
    new Promise((resolve, reject) => {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.top = '-1000px';
      textarea.setAttribute('readonly', true);
      document.body.appendChild(textarea);
      textarea.select();
      try {
        document.execCommand('copy');
        resolve();
      } catch (err) {
        reject(err);
      } finally {
        document.body.removeChild(textarea);
      }
    });

  const copyToClipboard = async (text) => {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      await fallbackCopy(text);
    }
  };

  const enhanceBlock = (codeEl) => {
    const pre = codeEl.parentElement;
    if (!pre || pre.dataset.codeEnhanced === 'true') {
      return;
    }

    pre.dataset.codeEnhanced = 'true';
    pre.classList.add('markdown-code-block');

    const langClass =
      Array.from(codeEl.classList).find((cls) => cls.startsWith('language-')) ||
      '';
    const langLabel = langClass.replace('language-', '').toUpperCase() || 'CODE';
    pre.dataset.lang = langLabel;

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'markdown-code-copy';
    button.innerHTML = `${iconCopy}<span>Copy</span>`;
    button.setAttribute('aria-label', 'Copy code block');

    button.addEventListener('click', async () => {
      const text = codeEl.textContent;
      try {
        await copyToClipboard(text);
        button.classList.add('copied');
        button.querySelector('span').textContent = 'Copied!';
        setTimeout(() => {
          button.classList.remove('copied');
          button.querySelector('span').textContent = 'Copy';
        }, 2300);
      } catch (err) {
        console.error('Failed to copy code', err);
        button.classList.add('copied');
        button.querySelector('span').textContent = 'Error';
        setTimeout(() => {
          button.classList.remove('copied');
          button.querySelector('span').textContent = 'Copy';
        }, 2300);
      }
    });

    pre.appendChild(button);
  };

  const applyHighlight = (codeBlocks) => {
    if (!window.hljs) {
      return;
    }
    codeBlocks.forEach((block) => {
      window.hljs.highlightElement(block);
    });
  };

  const init = () => {
    const codeBlocks = Array.from(getCodeBlocks());
    if (!codeBlocks.length) {
      return;
    }

    applyHighlight(codeBlocks);
    codeBlocks.forEach(enhanceBlock);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
