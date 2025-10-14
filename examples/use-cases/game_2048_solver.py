"""
Expectimax-based 2048 solver.

This implements an Expectimax algorithm for 2048:
- Player nodes: maximize score (choose best move)
- Chance nodes: expectation over random tile spawns (90% chance of 2, 10% chance of 4)
- Search depth: configurable (default 4 moves deep)
- Heuristics: monotonicity, smoothness, free tiles, max in corner

Expectimax achieves ~90% win rate for 2048 tile with depth 4-5.

Usage:
	board = [
		[2, 4, 8, 16],
		[0, 0, 0, 32],
		[0, 0, 0, 64],
		[0, 0, 0, 128]
	]
	solver = Game2048Solver(search_depth=4)
	best_move = solver.get_best_move(board)  # Returns 'ArrowLeft', 'ArrowRight', etc.
"""

import math
from typing import Literal


class Game2048Solver:
	"""Expectimax-based 2048 solver with heuristic evaluation."""

	def __init__(self, search_depth: int = 4):
		"""
		Initialize the solver.

		Args:
			search_depth: How many moves to search ahead (3-5 recommended, higher = slower but better)
		"""
		self.search_depth = search_depth
		self.directions = ['up', 'right', 'down', 'left']

	def get_best_move(self, board: list[list[int]]) -> Literal['ArrowUp', 'ArrowRight', 'ArrowDown', 'ArrowLeft']:
		"""
		Get the best move using Expectimax search.

		Args:
			board: 4x4 grid where 0 = empty, other values are tile values

		Returns:
			Best move direction as arrow key string
		"""
		best_score = -float('inf')
		best_move_idx = 0

		# Try all 4 directions
		for move_idx in range(4):
			# Simulate the move
			new_board = self._simulate_move(board, move_idx)

			# If move didn't change board, skip it
			if self._boards_equal(new_board, board):
				continue

			# Use Expectimax to score this move
			score = self._expectimax(new_board, depth=self.search_depth - 1, is_player=False)

			if score > best_score:
				best_score = score
				best_move_idx = move_idx

		# Map to arrow key names - explicitly typed to satisfy type checker
		if best_move_idx == 0:
			return 'ArrowUp'
		elif best_move_idx == 1:
			return 'ArrowRight'
		elif best_move_idx == 2:
			return 'ArrowDown'
		else:
			return 'ArrowLeft'

	def _expectimax(self, board: list[list[int]], depth: int, is_player: bool) -> float:
		"""
		Expectimax algorithm: alternates between player (max) and chance (expectation) nodes.

		Args:
			board: Current board state
			depth: Remaining search depth
			is_player: True if player's turn (max node), False if chance node

		Returns:
			Expected score of this board state
		"""
		# Base case: reached max depth
		if depth == 0:
			return self._evaluate_board(board)

		if is_player:
			# Player's turn: maximize over all possible moves
			max_score = -float('inf')

			for move_idx in range(4):
				new_board = self._simulate_move(board, move_idx)

				# Skip if move doesn't change board
				if self._boards_equal(new_board, board):
					continue

				# Recurse into chance node
				score = self._expectimax(new_board, depth - 1, is_player=False)
				max_score = max(max_score, score)

			# If no valid moves, return current board evaluation
			if max_score == -float('inf'):
				return self._evaluate_board(board)

			return max_score
		else:
			# Chance node: expectation over all possible tile spawns
			empty_cells = [(r, c) for r in range(4) for c in range(4) if board[r][c] == 0]

			if not empty_cells:
				# No empty cells, game over or next move is player's
				return self._evaluate_board(board)

			expected_score = 0.0
			num_empty = len(empty_cells)

			# For each empty cell, calculate expected value
			# 90% chance of 2, 10% chance of 4
			for row, col in empty_cells:
				# Try spawning a 2 (90% probability)
				board[row][col] = 2
				score_2 = self._expectimax(board, depth - 1, is_player=True)
				expected_score += (0.9 / num_empty) * score_2

				# Try spawning a 4 (10% probability)
				board[row][col] = 4
				score_4 = self._expectimax(board, depth - 1, is_player=True)
				expected_score += (0.1 / num_empty) * score_4

				# Reset cell
				board[row][col] = 0

			return expected_score

	def _boards_equal(self, board1: list[list[int]], board2: list[list[int]]) -> bool:
		"""Check if two boards are equal."""
		for r in range(4):
			for c in range(4):
				if board1[r][c] != board2[r][c]:
					return False
		return True

	def _simulate_move(self, board: list[list[int]], direction: int) -> list[list[int]]:
		"""Simulate a move without actually changing the board."""
		# Deep copy board
		new_board = [row[:] for row in board]

		if direction == 0:  # Up
			for col in range(4):
				new_board = self._move_column_up(new_board, col)
		elif direction == 1:  # Right
			for row in range(4):
				new_board = self._move_row_right(new_board, row)
		elif direction == 2:  # Down
			for col in range(4):
				new_board = self._move_column_down(new_board, col)
		elif direction == 3:  # Left
			for row in range(4):
				new_board = self._move_row_left(new_board, row)

		return new_board

	def _move_row_left(self, board: list[list[int]], row: int) -> list[list[int]]:
		"""Move and merge tiles in a row to the left."""
		# Extract non-zero tiles
		tiles = [board[row][col] for col in range(4) if board[row][col] != 0]

		# Merge adjacent equal tiles
		merged = []
		i = 0
		while i < len(tiles):
			if i + 1 < len(tiles) and tiles[i] == tiles[i + 1]:
				merged.append(tiles[i] * 2)
				i += 2
			else:
				merged.append(tiles[i])
				i += 1

		# Pad with zeros
		merged.extend([0] * (4 - len(merged)))

		# Update board
		for col in range(4):
			board[row][col] = merged[col]

		return board

	def _move_row_right(self, board: list[list[int]], row: int) -> list[list[int]]:
		"""Move and merge tiles in a row to the right."""
		# Extract non-zero tiles (reversed)
		tiles = [board[row][col] for col in range(3, -1, -1) if board[row][col] != 0]

		# Merge adjacent equal tiles
		merged = []
		i = 0
		while i < len(tiles):
			if i + 1 < len(tiles) and tiles[i] == tiles[i + 1]:
				merged.append(tiles[i] * 2)
				i += 2
			else:
				merged.append(tiles[i])
				i += 1

		# Pad with zeros
		merged.extend([0] * (4 - len(merged)))

		# Update board (reversed)
		for col in range(4):
			board[row][3 - col] = merged[col]

		return board

	def _move_column_up(self, board: list[list[int]], col: int) -> list[list[int]]:
		"""Move and merge tiles in a column upward."""
		# Extract non-zero tiles
		tiles = [board[row][col] for row in range(4) if board[row][col] != 0]

		# Merge adjacent equal tiles
		merged = []
		i = 0
		while i < len(tiles):
			if i + 1 < len(tiles) and tiles[i] == tiles[i + 1]:
				merged.append(tiles[i] * 2)
				i += 2
			else:
				merged.append(tiles[i])
				i += 1

		# Pad with zeros
		merged.extend([0] * (4 - len(merged)))

		# Update board
		for row in range(4):
			board[row][col] = merged[row]

		return board

	def _move_column_down(self, board: list[list[int]], col: int) -> list[list[int]]:
		"""Move and merge tiles in a column downward."""
		# Extract non-zero tiles (reversed)
		tiles = [board[row][col] for row in range(3, -1, -1) if board[row][col] != 0]

		# Merge adjacent equal tiles
		merged = []
		i = 0
		while i < len(tiles):
			if i + 1 < len(tiles) and tiles[i] == tiles[i + 1]:
				merged.append(tiles[i] * 2)
				i += 2
			else:
				merged.append(tiles[i])
				i += 1

		# Pad with zeros
		merged.extend([0] * (4 - len(merged)))

		# Update board (reversed)
		for row in range(4):
			board[3 - row][col] = merged[row]

		return board

	def _evaluate_board(self, board: list[list[int]]) -> float:
		"""
		Evaluate board quality using multiple weighted heuristics.

		Higher score = better board state.
		"""
		score = 0.0

		# 1. Empty tiles (critical - more space = more options)
		empty_weight = 270.0
		score += self._free_tiles_score(board) * empty_weight

		# 2. Monotonicity (tiles arranged in descending order)
		mono_weight = 100.0
		score += self._monotonicity_score(board) * mono_weight

		# 3. Smoothness (similar adjacent tiles easier to merge)
		smoothness_weight = -10.0
		score += self._smoothness_score(board) * smoothness_weight

		# 4. Max tile value (reward higher tiles)
		max_tile = max(max(row) for row in board)
		score += max_tile * 10.0

		# 5. Max in corner (strongly prefer max in corner)
		corner_weight = 10000.0
		score += self._max_in_corner_score(board) * corner_weight

		return score

	def _monotonicity_score(self, board: list[list[int]]) -> float:
		"""
		Score based on monotonic ordering.

		Prefers boards where tiles are arranged in consistent increasing/decreasing order.
		"""
		totals = [0.0, 0.0, 0.0, 0.0]  # up, down, left, right

		# Check each row
		for row in range(4):
			current = 0
			next_idx = current + 1
			while next_idx < 4:
				while next_idx < 4 and board[row][next_idx] == 0:
					next_idx += 1
				if next_idx >= 4:
					break

				current_val = math.log2(board[row][current]) if board[row][current] > 0 else 0
				next_val = math.log2(board[row][next_idx]) if board[row][next_idx] > 0 else 0

				if current_val > next_val:
					totals[0] += next_val - current_val
				elif next_val > current_val:
					totals[1] += current_val - next_val

				current = next_idx
				next_idx += 1

		# Check each column
		for col in range(4):
			current = 0
			next_idx = current + 1
			while next_idx < 4:
				while next_idx < 4 and board[next_idx][col] == 0:
					next_idx += 1
				if next_idx >= 4:
					break

				current_val = math.log2(board[current][col]) if board[current][col] > 0 else 0
				next_val = math.log2(board[next_idx][col]) if board[next_idx][col] > 0 else 0

				if current_val > next_val:
					totals[2] += next_val - current_val
				elif next_val > current_val:
					totals[3] += current_val - next_val

				current = next_idx
				next_idx += 1

		return max(totals[0], totals[1]) + max(totals[2], totals[3])

	def _smoothness_score(self, board: list[list[int]]) -> float:
		"""
		Score based on similarity of adjacent tiles (using log scale).

		Lower difference = easier to merge.
		"""
		smoothness = 0.0

		for row in range(4):
			for col in range(4):
				if board[row][col] == 0:
					continue

				value = math.log2(board[row][col])

				# Check right neighbor
				if col < 3:
					target_col = col + 1
					while target_col < 4 and board[row][target_col] == 0:
						target_col += 1
					if target_col < 4:
						target_value = math.log2(board[row][target_col])
						smoothness -= abs(value - target_value)

				# Check down neighbor
				if row < 3:
					target_row = row + 1
					while target_row < 4 and board[target_row][col] == 0:
						target_row += 1
					if target_row < 4:
						target_value = math.log2(board[target_row][col])
						smoothness -= abs(value - target_value)

		return smoothness

	def _free_tiles_score(self, board: list[list[int]]) -> float:
		"""Score based on number of empty tiles."""
		count = sum(1 for row in board for cell in row if cell == 0)
		return float(count)

	def _max_in_corner_score(self, board: list[list[int]]) -> float:
		"""Score based on whether max tile is in a corner."""
		max_val = max(max(row) for row in board)

		# Check all corners, prefer bottom-left
		corners = [
			(3, 0, 1.0),  # bottom-left (preferred)
			(3, 3, 0.8),  # bottom-right
			(0, 0, 0.6),  # top-left
			(0, 3, 0.4),  # top-right
		]

		for row, col, weight in corners:
			if board[row][col] == max_val:
				return weight

		return 0.0


# Example usage
if __name__ == '__main__':
	solver = Game2048Solver()

	# Test board
	test_board = [
		[2, 4, 8, 16],
		[0, 2, 0, 32],
		[0, 0, 0, 64],
		[0, 0, 0, 128],
	]

	best_move = solver.get_best_move(test_board)
	print(f'Best move: {best_move}')
