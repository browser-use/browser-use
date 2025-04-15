import hashlib

from browser_use.dom.views import DOMElementNode


class ClickableElementProcessor:
	@staticmethod
	def get_clickable_elements_hashes(dom_element: DOMElementNode) -> set[str]:
		"""Get all clickable elements in the DOM tree"""
		clickable_elements = ClickableElementProcessor.get_clickable_elements(dom_element)
		return {ClickableElementProcessor.hash_dom_element(element) for element in clickable_elements}

	@staticmethod
	def get_clickable_elements(dom_element: DOMElementNode) -> list[DOMElementNode]:
		"""Get all clickable elements in the DOM tree"""
		clickable_elements = list()
		for child in dom_element.children:
			if isinstance(child, DOMElementNode):
				if child.highlight_index:
					clickable_elements.append(child)

				clickable_elements.extend(ClickableElementProcessor.get_clickable_elements(child))

		return list(clickable_elements)

	@staticmethod
	def hash_dom_element(dom_element: DOMElementNode) -> str:
		parent_branch_path = ClickableElementProcessor._get_parent_branch_path(dom_element)
		branch_path_hash = ClickableElementProcessor._parent_branch_path_hash(parent_branch_path)
		attributes_hash = ClickableElementProcessor._attributes_hash(dom_element.attributes)
		xpath_hash = ClickableElementProcessor._xpath_hash(dom_element.xpath)
		# text_hash = DomTreeProcessor._text_hash(dom_element)

		return ClickableElementProcessor._hash_string(f'{branch_path_hash}-{attributes_hash}-{xpath_hash}')

	@staticmethod
	def _get_parent_branch_path(dom_element: DOMElementNode) -> list[str]:
		parents: list[DOMElementNode] = []
		current_element: DOMElementNode = dom_element
		while current_element.parent is not None:
			parents.append(current_element)
			current_element = current_element.parent

		parents.reverse()

		return [parent.tag_name for parent in parents]

	@staticmethod
	def _parent_branch_path_hash(parent_branch_path: list[str]) -> str:
		parent_branch_path_string = '/'.join(parent_branch_path)
		return hashlib.sha256(parent_branch_path_string.encode()).hexdigest()

	@staticmethod
	def _attributes_hash(attributes: dict[str, str]) -> str:
		attributes_string = ''.join(f'{key}={value}' for key, value in attributes.items())
		return ClickableElementProcessor._hash_string(attributes_string)

	@staticmethod
	def _xpath_hash(xpath: str) -> str:
		return ClickableElementProcessor._hash_string(xpath)

	@staticmethod
	def _text_hash(dom_element: DOMElementNode) -> str:
		""" """
		text_string = dom_element.get_all_text_till_next_clickable_element()
		return ClickableElementProcessor._hash_string(text_string)

	@staticmethod
	def _hash_string(string: str) -> str:
		return hashlib.sha256(string.encode()).hexdigest()
