#!/usr/bin/env node
/**
 * Read [{code, language}] JSON from stdin and emit Shiki-highlighted HTML.
 * Shiki is resolved from the cache root passed as argv[2], keeping the skill
 * archive lightweight while producing static HTML with no browser runtime.
 */
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const root = process.argv[2];
if (!root) {
  console.error('Shiki cache root is required.');
  process.exit(2);
}

const requireFromCache = createRequire(path.join(root, 'package.json'));
const shikiPath = requireFromCache.resolve('shiki');
const { createHighlighter } = await import(pathToFileURL(shikiPath).href);
const blocks = JSON.parse(fs.readFileSync(0, 'utf8'));
const kamiTheme = {
  name: 'kami',
  type: 'light',
  colors: {
    'editor.background': '#faf9f5',
    'editor.foreground': '#141413',
  },
  tokenColors: [
    { scope: ['comment', 'comment.line', 'comment.block'], settings: { foreground: '#6b6a64' } },
    { scope: ['keyword', 'storage', 'storage.type', 'keyword.control'], settings: { foreground: '#1B365D' } },
    { scope: ['string', 'string.quoted'], settings: { foreground: '#504e49' } },
    { scope: ['constant.numeric', 'constant.language', 'constant.character'], settings: { foreground: '#3d3d3a' } },
    { scope: ['entity.name.function', 'entity.name.class', 'support.function'], settings: { foreground: '#141413' } },
  ],
};
const highlighter = await createHighlighter({
  themes: [kamiTheme],
  langs: [],
});

const rendered = [];
for (const { code, language } of blocks) {
  try {
    // Load per block so an unsupported language stays monochrome without
    // preventing the rest of the document from receiving Shiki highlighting.
    await highlighter.loadLanguage(language);
    const html = highlighter.codeToHtml(code, {
      lang: language,
      theme: 'kami',
    });
    // Keep Kami's parchment code surface while retaining Shiki token colors.
    rendered.push(html.replace(
      /<pre class="shiki kami"([^>]*)>/,
      (_match, attributes) => (
        '<pre class="shiki shiki-rendered kami" '
        + 'style="background-color:var(--ivory);color:#393a34"'
        + attributes.replace(/\sstyle="[^"]*"/, '')
        + '>'
      ),
    ));
  } catch (_) {
    rendered.push(null);
  }
}

highlighter.dispose();
process.stdout.write(JSON.stringify(rendered));
