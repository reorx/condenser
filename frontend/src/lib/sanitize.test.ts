import { describe, expect, it } from 'vitest';

import { sanitizeHtml } from './sanitize';

describe('sanitizeHtml', () => {
  it('keeps HN-style markup', () => {
    const out = sanitizeHtml('<p>Hello <i>world</i></p><pre><code>x = 1</code></pre>');
    expect(out).toContain('<i>world</i>');
    expect(out).toContain('<code>x = 1</code>');
  });

  it('strips scripts and event handlers', () => {
    const out = sanitizeHtml('<p onmouseover="alert(1)">hi</p><script>alert(2)</script><img src=x onerror=alert(3)>');
    expect(out).not.toContain('script');
    expect(out).not.toContain('onmouseover');
    expect(out).not.toContain('onerror');
  });

  it('forces links to open in a new tab', () => {
    const out = sanitizeHtml('<a href="https://example.com">x</a>');
    expect(out).toContain('target="_blank"');
    expect(out).toContain('rel="noreferrer"');
    expect(out).toContain('href="https://example.com"');
  });

  it('drops javascript: URLs', () => {
    expect(sanitizeHtml('<a href="javascript:alert(1)">x</a>')).not.toContain('javascript:');
  });
});
