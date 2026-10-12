from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from browser_use.browser.session import CDPSession


class DOMPruner:
	@staticmethod
	async def prune_dom(cdp_session: CDPSession) -> None:
		"""
		Prune invisible DOM elements and unnecessary attributes through CDP.
		"""
		js_code = """
        () => {
            const blacklistTags = ['script', 'style', 'noscript', 'meta', 'link', 'svg', 'path', 'iframe', 'head'];

            function cleanNode(node) {
                if (!node || node.nodeType !== Node.ELEMENT_NODE) return;
                const tagName = node.tagName.toLowerCase();

                if (blacklistTags.includes(tagName)) {
                    node.remove();
                    return;
                }

                const style = window.getComputedStyle(node);
                const isHidden = (
                    style.display === 'none' ||
                    style.visibility === 'hidden' ||
                    style.opacity === '0'
                );

                const hasNoDimensions = (node.offsetWidth === 0 && node.offsetHeight === 0);

                if ((isHidden || hasNoDimensions) && tagName !== 'body' && tagName !== 'html') {
                    node.remove();
                    return;
                }

                const allowedAttributes = ['id', 'name', 'value', 'placeholder', 'aria-label', 'role', 'type', 'href'];
                Array.from(node.attributes).forEach(attr => {
                    if (!allowedAttributes.includes(attr.name)) {
                        node.removeAttribute(attr.name);
                    }
                });

                Array.from(node.children).forEach(child => cleanNode(child));

                if (['div', 'span', 'section', 'article'].includes(tagName)) {
                    const hasText = node.textContent && node.textContent.trim().length > 0;
                    const hasChildren = node.children && node.children.length > 0;
                    if (!hasText && !hasChildren) {
                        node.remove();
                    }
                }
            }
            if (document.body) {
                cleanNode(document.body);
            }
        }
        """

		# Εκτέλεση της JavaScript μέσω CDP Runtime domain
		try:
			await cdp_session.cdp_client.send.Runtime.evaluate(params={'expression': f'({js_code})()'})
		except Exception:
			pass  # Ασφαλής αποφυγή σφαλμάτων σε edge cases lifecycle του browser
