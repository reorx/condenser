import DOMPurify from 'dompurify';

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
