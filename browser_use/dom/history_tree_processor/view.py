from dataclasses import dataclass

from pydantic import BaseModel


@dataclass
class HashedDomElement:
	"""
	Hash of the dom element to be used as a unique identifier
	"""

	branch_path_hash: str
	attributes_hash: str
	xpath_hash: str
	# text_hash: str


class Coordinates(BaseModel):
	x: int
	y: int


class CoordinateSet(BaseModel):
	top_left: Coordinates
	top_right: Coordinates
	bottom_left: Coordinates
	bottom_right: Coordinates
	center: Coordinates
	width: int
	height: int


class ViewportInfo(BaseModel):
	scroll_x: int | None = None
	scroll_y: int | None = None
	width: int
	height: int


@dataclass
class DOMHistoryElement:
	tag_name: str
	xpath: str
	highlight_index: int | None
	entire_parent_branch_path: list[str]
	attributes: dict[str, str]
	shadow_root: bool = False
	css_selector: str | None = None
	page_coordinates: CoordinateSet | None = None
	viewport_coordinates: CoordinateSet | None = None
	viewport_info: ViewportInfo | None = None

	def to_dict(self) -> dict:
		page_coordinates = self.page_coordinates.model_dump() if self.page_coordinates else None
		viewport_coordinates = self.viewport_coordinates.model_dump() if self.viewport_coordinates else None
		viewport_info = self.viewport_info.model_dump() if self.viewport_info else None

		return {
			'tag_name': self.tag_name,
			'xpath': self.xpath,
			'highlight_index': self.highlight_index,
			'entire_parent_branch_path': self.entire_parent_branch_path,
			'attributes': self.attributes,
			'shadow_root': self.shadow_root,
			'css_selector': self.css_selector,
			'page_coordinates': page_coordinates,
			'viewport_coordinates': viewport_coordinates,
			'viewport_info': viewport_info,
		}
