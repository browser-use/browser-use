#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["python-chess", "browser-use", "beautifulsoup4"]
# ///

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

import asyncio
import logging

import chess  # type: ignore
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from browser_use import Agent, Controller
from browser_use.agent.views import ActionResult
from browser_use.browser.context import BrowserContext
from browser_use.llm import ChatOpenAI

if not os.getenv('OPENAI_API_KEY'):
	raise ValueError('OPENAI_API_KEY is not set. Please add it to your environment variables.')

logger = logging.getLogger(__name__)

controller = Controller()


class PlayMoveParams(BaseModel):
	move: str = Field(
		description="The move in Standard Algebraic Notation (SAN) exactly as provided in the 'Legal Moves' list (e.g., 'Nf3', 'e4', 'Qh7#')."
	)


FILES = 'abcdefgh'
RANKS = '87654321'


# --- Helper Functions ---
def to_px(val: float) -> str:
	"""Convert float to px string, e.g. 42.0 -> '42px'."""
	s = f'{val:.1f}'.rstrip('0').rstrip('.')
	return f'{s}px'


def from_px(px: str) -> float:
	"""Convert px string to float, e.g. '42px' -> 42.0."""
	return float(px.replace('px', '').strip())


def parse_transform(style: str) -> tuple[float, float] | None:
	"""Extracts x and y pixel coordinates from a CSS transform string."""
	try:
		parts = style.split('(')[1].split(')')[0].split(',')
		x_px_str = float(parts[0].strip().replace('px', ''))
		y_px_str = float(parts[1].strip().replace('px', ''))
		return x_px_str, y_px_str
	except Exception as e:
		logger.error(f'Error parsing transform style: {e}')
		return None


def algebraic_to_pixels(square: str, square_size: float) -> tuple[str, str]:
	"""Converts algebraic notation to Lichess pixel coordinates using dynamic size."""
	file_char = square[0].lower()
	rank_char = square[1]

	if file_char not in FILES or rank_char not in RANKS:
		raise ValueError(f'Invalid square: {square}')

	x_index = FILES.index(file_char)
	y_index = RANKS.index(rank_char)

	x_px = x_index * square_size
	y_px = y_index * square_size
	return to_px(x_px), to_px(y_px)


def pixels_to_algebraic(x_px: float, y_px: float, square_size: float) -> str:
	"""Converts Lichess pixel coordinates to algebraic notation using dynamic size."""
	if not square_size:
		raise ValueError('Square size cannot be zero or None.')

	x_index = int(round(x_px / square_size))
	y_index = int(round(y_px / square_size))

	if 0 <= x_index < 8 and 0 <= y_index < 8:
		return f'{FILES[x_index]}{RANKS[y_index]}'

	raise ValueError(f'Pixel coordinates out of bounds: ({x_px}, {y_px})')


async def calculate_square_size(page) -> float | None:
	"""Dynamically calculates the size of a chess square in pixels."""
	try:
		board_html = await page.locator('cg-board').inner_html(timeout=3000)
		soup = BeautifulSoup(board_html, 'html.parser')
		pieces = soup.find_all('piece')
		if not pieces:
			raise ValueError('No pieces found.')
		x_coords: set[float] = set()
		for piece in pieces:
			if hasattr(piece, 'get'):
				style = piece.get('style')  # type: ignore
			else:
				continue
			if style:
				coords = parse_transform(style)  # type: ignore
				if coords:
					x_coords.add(coords[0])

		sorted_x = sorted(list(x_coords))
		x_diffs = [sorted_x[i] - sorted_x[i - 1] for i in range(1, len(sorted_x))]
		square_size = round(min(d for d in x_diffs if d > 1), 1)
		logger.debug(f'Calculated square size: {square_size}px')
		return square_size
	except Exception as e:
		logger.error(f'Error calculating square size: {e}')
		return None


def get_piece_symbol(class_list: list[str]) -> str:
	color = class_list[0]
	ptype = class_list[1]
	symbols = {'king': 'k', 'queen': 'q', 'rook': 'r', 'bishop': 'b', 'knight': 'n', 'pawn': 'p'}
	symbol = symbols.get(ptype, '?')
	return symbol.upper() if color == 'white' else symbol


def create_fen_board(board_state: dict) -> str:
	fen = ''
	for rank_num in RANKS:
		empty_count = 0
		for file_char in FILES:
			square = f'{file_char}{rank_num}'
			if square in board_state:
				if empty_count > 0:
					fen += str(empty_count)
					empty_count = 0
				fen += board_state[square]
			else:
				empty_count += 1
		if empty_count > 0:
			fen += str(empty_count)
		if rank_num != RANKS[-1]:
			fen += '/'
	return fen


async def get_current_board_info(page) -> tuple[str | None, float | None]:
	"""Reads the current board HTML and returns FEN string and square size."""
	board_state = {}
	board_html = ''
	square_size = None

	try:
		board_locator = page.locator('cg-board')
		await board_locator.wait_for(state='visible', timeout=3000)
		board_html = await board_locator.inner_html()
		square_size = await calculate_square_size(page)
	except Exception as e:
		logger.error(f'Error (get_info): Could not read cg-board: {e}')
		return None, None

	if not board_html or not square_size:
		return None, None

	soup = BeautifulSoup(board_html, 'html.parser')
	pieces = soup.find_all('piece')
	for piece in pieces:
		if not hasattr(piece, 'get'):
			continue
		style = piece.get('style')  # type: ignore
		class_ = piece.get('class')  # type: ignore

		if style and class_:
			coords = parse_transform(style)  # type: ignore
			if coords:
				x_px, y_px = coords
				try:
					square = pixels_to_algebraic(x_px, y_px, square_size)
					board_state[square] = get_piece_symbol(class_)  # type: ignore
				except ValueError as ve:
					logger.error(f'Error: {ve}')

	if not board_state or not square_size:
		return None, None

	fen_board = create_fen_board(board_state)
	full_fen = f'{fen_board} w KQkq - 0 1'
	return full_fen, square_size


# --- Custom Actions ---
@controller.registry.action(
	'Read Chess Board',
)
async def read_board(browser: BrowserContext):
	"""Reads the board, returns FEN and legal moves in SAN (+/#), and the last move by opponent if possible."""
	page = await browser.get_current_page()
	full_fen, _ = await get_current_board_info(page)

	if not full_fen:
		return ActionResult(extracted_content='Could not read board state.')

	legal_moves_descriptive = []
	last_move_san = None

	try:
		move_list_html = await page.locator('l4x').inner_html(timeout=3000)
		soup = BeautifulSoup(move_list_html, 'html.parser')
		move_tags = soup.find_all('kwdb')
		moves = [tag.get_text(strip=True) for tag in move_tags]
		last_move_san = moves[-1] if moves else None
	except Exception as e:
		logger.error(f'Error extracting move list: {e}')
		last_move_san = None

	try:
		board = chess.Board(full_fen)
		for move in board.legal_moves:
			san = board.san(move)
			board.push(move)
			is_mate = board.is_checkmate()
			board.pop()
			is_check = board.gives_check(move) and not is_mate

			move_str_out = san.replace('+', '')
			if is_mate:
				move_str_out += '#'
			elif is_check:
				move_str_out += '+'
			legal_moves_descriptive.append(move_str_out)

	except Exception as chess_err:
		logger.error(f'Error generating SAN moves: {chess_err}. FEN: {full_fen}')
		legal_moves_descriptive = ['Error']

	result_text = f'FEN: {full_fen}. Legal Moves (SAN): {", ".join(legal_moves_descriptive)}'
	if last_move_san:
		result_text = f'Last move: {last_move_san}. {result_text}'
	logger.info(f'Read board result: {result_text}')
	return ActionResult(extracted_content=result_text, include_in_memory=True)


@controller.registry.action(
	'Play Chess Move',
	param_model=PlayMoveParams,
)
async def play_move(params: PlayMoveParams, browser: BrowserContext):
	"""Plays a chess move given in SAN by converting it to UCI and clicking."""
	san_move = params.move.strip()
	page = await browser.get_current_page()
	uci_move = ''

	try:
		current_fen, square_size = await get_current_board_info(page)
		if not current_fen or square_size is None:
			return ActionResult(extracted_content='Failed to get current FEN or square size to play move.')

		board = chess.Board(current_fen)
		san_to_parse = san_move.replace('#', '').replace('+', '')
		move_obj = board.parse_san(san_to_parse)
		uci_move = move_obj.uci()

	except Exception as e:
		return ActionResult(extracted_content=f"Could not parse SAN move '{san_move}' or get FEN: {e}")

	start_sq = uci_move[:2]
	end_sq = uci_move[2:]

	try:
		start_x_str, start_y_str = algebraic_to_pixels(start_sq, square_size)
		end_x_str, end_y_str = algebraic_to_pixels(end_sq, square_size)
		start_x = from_px(start_x_str)
		start_y = from_px(start_y_str)
		end_x = from_px(end_x_str)
		end_y = from_px(end_y_str)
	except Exception as e:
		return ActionResult(extracted_content=f"Could not convert UCI '{uci_move}' to coordinates: {e}")

	try:
		board_locator = page.locator('cg-board')
		await board_locator.wait_for(state='visible', timeout=3000)
		click_offset = square_size / 2
		start_click_x = start_x + click_offset
		start_click_y = start_y + click_offset
		end_click_x = end_x + click_offset
		end_click_y = end_y + click_offset

		logger.debug(f"DEBUG: Playing SAN '{san_move}' (UCI: {uci_move}).")
		await board_locator.click(position={'x': start_click_x, 'y': start_click_y}, timeout=3000)
		await asyncio.sleep(0.5)
		await board_locator.click(position={'x': end_click_x, 'y': end_click_y}, timeout=3000)
		await asyncio.sleep(0.5)
		return ActionResult(extracted_content=f'Played move {san_move}.', include_in_memory=True)

	except Exception as e:
		error_message = f'Failed to play move {san_move} using Coordinates: {e}'
		logger.error(f'ERROR: {error_message}')
		return ActionResult(extracted_content=error_message)


# --- Main Execution ---
async def main():
	agent = Agent(
		task="""
        Objective: Play chess against the computer on Lichess and win.

        Strategy: Play the Queen's Gambit opening (1. d4 d5 2. c4) as White. Aim for a solid, strategic game.

        Instructions:
        1. Open lichess.org.
        2. Find and click the button or link with the text "Play with the computer". Use a standard click action.
        3. On the setup screen, ensure 'White' is selected. Click the "Play" or "Start game" button.
        4. Use 'Read Chess Board'. This will provide the FEN and a list called 'Legal Moves (SAN)'.
        5. The 'Legal Moves (SAN)' list will contain moves like 'Nf3' (Knight to f3), 'e4' (pawn to e4), 'O-O' (kingside castle), 'Rxe4+' (Rook captures on e4, giving check), or 'Qh7#' (Queen to h7, checkmate).
        6. Analyze the FEN, moves, and **you MUST choose your next move EXACTLY as it appears in the 'Legal Moves (SAN)' list.** Do not invent moves or use any other format.
        7. Use the 'Play Chess Move' action, passing the exact SAN string you chose. For example: `play_move(move='Nf3')` or `play_move(move='Rxe4+')`.
        8. Repeat steps 4-7 until the game ends. If anything seems wrong, use 'Read Chess Board' again.
        9. Announce the final result.
        """,
		llm=ChatOpenAI(model='gpt-4.1'),
		controller=controller,
	)
	result = await agent.run()
	logger.info(result)


if __name__ == '__main__':
	asyncio.run(main())
