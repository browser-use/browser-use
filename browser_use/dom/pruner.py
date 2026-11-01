from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from browser_use.browser.session import CDPSession


class DOMPruner:
	@staticmethod
	async def prune_dom(cdp_session: CDPSession) -> str | None:
		"""Return a pruned HTML snapshot without modifying the live document."""
		js_code = """
        () => {
            const blacklistTags = ['script', 'style', 'noscript', 'meta', 'link', 'svg', 'path', 'iframe', 'head'];

            function cleanNode(sourceNode, clonedNode) {
                if (!sourceNode || !clonedNode || sourceNode.nodeType !== Node.ELEMENT_NODE) return;
                const tagName = sourceNode.tagName.toLowerCase();

                if (blacklistTags.includes(tagName)) {
                    clonedNode.remove();
                    return;
                }

                const style = window.getComputedStyle(sourceNode);
                const isHidden = (
                    style.display === 'none' ||
                    style.visibility === 'hidden' ||
                    style.opacity === '0'
                );
                const hasNoDimensions = sourceNode.offsetWidth === 0 && sourceNode.offsetHeight === 0;

                if ((isHidden || hasNoDimensions) && tagName !== 'body' && tagName !== 'html') {
                    clonedNode.remove();
                    return;
                }

                const allowedAttributes = ['id', 'name', 'value', 'placeholder', 'aria-label', 'role', 'type', 'href'];
                Array.from(clonedNode.attributes).forEach(attr => {
                    if (!allowedAttributes.includes(attr.name)) {
                        clonedNode.removeAttribute(attr.name);
                    }
                });

                for (let index = sourceNode.children.length - 1; index >= 0; index--) {
                    cleanNode(sourceNode.children[index], clonedNode.children[index]);
                }

                if (['div', 'span', 'section', 'article'].includes(tagName)) {
                    const hasText = clonedNode.textContent && clonedNode.textContent.trim().length > 0;
                    const hasChildren = clonedNode.children && clonedNode.children.length > 0;
                    if (!hasText && !hasChildren) {
                        clonedNode.remove();
                    }
                }
            }

            if (!document.body) return '';

            const clonedBody = document.body.cloneNode(true);
            cleanNode(document.body, clonedBody);
            return clonedBody.outerHTML;
        }
        """

		try:
			result = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={'expression': f'({js_code})()', 'returnByValue': True},
				session_id=cdp_session.session_id,
			)
			return result.get('result', {}).get('value')
		except Exception:
			return None  # Best effort when the page is closing or the CDP session is unavailable.
