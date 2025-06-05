import shutil
from pathlib import Path


class FileSystem:
	def __init__(self, dir_path: str):
		self.dir = Path(dir_path)
		self.dir.mkdir(parents=True, exist_ok=True)
		self.results_file = self.dir / 'results.txt'
		self.results_file.touch(exist_ok=True)

	def read_file(self, file_name: str) -> str:
		path = self.dir / file_name
		if not path.exists():
			return f"File '{file_name}' not found."
		return path.read_text()

	def write_file(self, file_name: str, content: str) -> None:
		path = self.dir / file_name
		path.write_text(content)

	def append_file(self, file_name: str, content: str) -> str:
		path = self.dir / file_name
		if not path.exists():
			return f"File '{file_name}' not found."
		with path.open('a') as f:
			f.write(content + '\n')
		return 'Append successful.'

	def delete_folder(self) -> None:
		if self.dir.exists():
			shutil.rmtree(self.dir)

	def __str__(self) -> str:
		description = 'Files and their contents in your file system:\n'
		for f in self.dir.iterdir():
			if f.is_file():
				description += f'File Name: {f.name}\nFile Content:\n{f.read_text()}\n'
		return description
