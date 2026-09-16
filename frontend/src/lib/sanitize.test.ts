import { describe, expect, it } from 'vitest';

import { proxyImages, sanitizeHtml } from './sanitize';

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

  it('keeps the figure markup and image sizes an X article arrives in', () => {
    const out = sanitizeHtml(
      '<figure><img src="https://pbs.twimg.com/media/A.jpg" width="2986" height="1648" alt="cap" /><figcaption>cap</figcaption></figure>',
    );
    expect(out).toContain('<figcaption>cap</figcaption>');
    expect(out).toContain('width="2986"');
    expect(out).toContain('height="1648"');
  });
});

describe('proxyImages', () => {
  it('routes every http(s) image through the preview proxy, sizes intact', () => {
    // "Reading a tweet never pings X from the reader's IP" covers an article's
    // images too.
    const out = proxyImages('<p>a</p><figure><img src="https://pbs.twimg.com/media/A.jpg?x=1&y=2" width="10" height="20" alt="c"></figure>');
    const img = new DOMParser().parseFromString(out, 'text/html').querySelector('img')!;
    expect(img.getAttribute('src')).toBe(
      `/api/preview/image?url=${encodeURIComponent('https://pbs.twimg.com/media/A.jpg?x=1&y=2')}`,
    );
    expect(img.getAttribute('width')).toBe('10');
    expect(img.getAttribute('height')).toBe('20');
    expect(out).toContain('<p>a</p>');
  });

  it('leaves anything that is not an absolute http(s) URL alone', () => {
    const out = proxyImages('<img src="/api/media/1"><img src="data:image/png;base64,AA">');
    expect(out).toContain('src="/api/media/1"');
    expect(out).toContain('src="data:image/png;base64,AA"');
  });
});
