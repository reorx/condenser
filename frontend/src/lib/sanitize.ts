import DOMPurify from 'dompurify';

import { previewImageUrl } from '@/lib/api';

// Third-party HTML (HN self-post text) is rendered via dangerouslySetInnerHTML;
// force every surviving link to open in a new tab without a referrer.
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank');
    node.setAttribute('rel', 'noreferrer');
  }
});

/** Sanitize untrusted HTML for inline rendering (scripts/handlers/js: URLs dropped). */
export function sanitizeHtml(html: string): string {
  return DOMPurify.sanitize(html);
}

/** Route every absolute http(s) `<img>` through `/api/preview/image`, so rendering
 *  a body never makes the reader's browser contact the image host (an X article's
 *  images are on pbs.twimg.com — the promise `XMediaThumb` keeps for tweet media).
 *
 *  Parsed in a `<template>`, whose content is inert: an `<img>` there loads
 *  nothing, where a detached `<div>`'s innerHTML would start fetching every original
 *  before the rewrite. Run it on already-sanitized HTML. */
export function proxyImages(html: string): string {
  const template = document.createElement('template');
  template.innerHTML = html;
  template.content.querySelectorAll('img[src]').forEach((img) => {
    const src = img.getAttribute('src')!;
    if (/^https?:\/\//i.test(src)) img.setAttribute('src', previewImageUrl(src));
  });
  return template.innerHTML;
}
