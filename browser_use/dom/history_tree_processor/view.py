from dataclasses import dataclass
from typing import Optional


@dataclass
class HashedDomElement:
	"""
	Hash of the dom element to be used as a unique identifier
	"""

	branch_path_hash: str
	attributes_hash: str
	# text_hash: str

@dataclass(frozen=False)
class Position:
    top: int
    left: int
    width: int
    height: int

@dataclass
class DOMHistoryElement:
	tag_name: str
	xpath: str
	highlight_index: Optional[int]
	entire_parent_branch_path: list[str]
	attributes: dict[str, str]
	shadow_root: bool = False
	position: Optional[Position] = None

	def to_dict(self) -> dict:
		return {
			'tag_name': self.tag_name,
			'xpath': self.xpath,
			'highlight_index': self.highlight_index,
			'entire_parent_branch_path': self.entire_parent_branch_path,
			'attributes': self.attributes,
			'shadow_root': self.shadow_root,
		}
