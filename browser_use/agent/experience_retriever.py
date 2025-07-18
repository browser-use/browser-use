"""
Historical Experience Retriever for Browser Use Agent

This module retrieves similar historical states based on embedding similarity
and provides action recommendations based on previous successes/failures.
"""

import json
import logging
import numpy as np
from pathlib import Path
from typing import Dict, List, Any, Optional
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)


class ExperienceRetriever:
	"""Retrieves and formats historical experience based on state similarity"""
	
	def __init__(
		self, 
		embeddings_file: str,
		similarity_threshold: float = 0.7,
		top_k: int = 5
	):
		self.embeddings_file = embeddings_file
		self.similarity_threshold = similarity_threshold
		self.top_k = top_k
		self.embeddings_data = None
		self.client = None
		
		self._load_embeddings()
		self._init_client()
	
	def _load_embeddings(self):
		"""Load historical embedding data"""
		try:
			embeddings_path = Path(self.embeddings_file)
			if embeddings_path.exists():
				with open(embeddings_path, 'r', encoding='utf-8') as f:
					self.embeddings_data = json.load(f)
				logger.info(f"✓ Loaded embeddings from {self.embeddings_file}")
			else:
				logger.warning(f"Embeddings file {self.embeddings_file} not found")
				self.embeddings_data = None
		except Exception as e:
			logger.warning(f"Failed to load embeddings: {e}")
			self.embeddings_data = None
	
	def _init_client(self):
		"""Initialize OpenAI client"""
		try:
			from api_key import OpenAI_API_KEY, OPENAI_BASE_URL
			from openai import OpenAI
			self.client = OpenAI(api_key=OpenAI_API_KEY, base_url=OPENAI_BASE_URL)
			logger.debug("✓ Initialized OpenAI client for experience retrieval")
		except ImportError:
			logger.warning("api_key.py not found, experience retrieval disabled")
			self.client = None
		except Exception as e:
			logger.warning(f"Failed to initialize OpenAI client: {e}")
			self.client = None
	
	async def retrieve_similar_states(self, current_state: dict) -> List[dict]:
		"""
		Retrieve similar states from historical embeddings
		
		Args:
			current_state: Current browser state dictionary
			
		Returns:
			List of similar states with their actions and scores
		"""
		if not self.client or not self.embeddings_data:
			return []
		
		try:
			# Extract current state description
			current_state_text = self._extract_state_description(current_state)
			
			# Create embedding for current state
			logger.debug("Creating embedding for current state...")
			response = self.client.embeddings.create(
				model="text-embedding-3-large",
				input=current_state_text
			)
			current_embedding = response.data[0].embedding
			
			# Calculate similarities with historical states
			similarities = []
			for historical in self.embeddings_data.get("state_embeddings", []):
				similarity = self._cosine_similarity(
					current_embedding, 
					historical["state_embedding"]
				)
				
				if similarity >= self.similarity_threshold:
					similarities.append({
						"similarity": similarity,
						"action": historical["action"],
						"score": historical["score"],
						"reasoning": historical["reasoning"],
						"situation": historical.get("situation", ""),
						"thinking": historical.get("thinking", "")
					})
			
			# Sort by similarity and return top-k
			similarities.sort(key=lambda x: x["similarity"], reverse=True)
			result = similarities[:self.top_k]
			
			if result:
				logger.info(f"🔍 Experience search: Found {len(result)} similar states (threshold: {self.similarity_threshold})")
				logger.info(f"   Best match: similarity={result[0]['similarity']:.3f}, score={result[0]['score']}/10")
			else:
				logger.debug(f"No similar states found above threshold {self.similarity_threshold}")
			
			return result
			
		except Exception as e:
			logger.warning(f"Error retrieving similar states: {e}")
			return []
	
	def _extract_state_description(self, state: dict) -> str:
		"""Extract and format state information for embedding"""
		# Use the same extraction logic as state_embedder.py
		url = state.get('url', '')
		title = state.get('title', '')
		interactive_elements = state.get('interactive_elements_text', '')
		
		# Scroll position context
		scroll_pos = state.get('scroll_position', {})
		pixels_above = scroll_pos.get('pixels_above', 0)
		pixels_below = scroll_pos.get('pixels_below', 0)
		
		# Format as descriptive text
		state_text = f"""
URL: {url}
Page Title: {title}
Interactive Elements: {interactive_elements}
Scroll Position: {pixels_above} pixels above, {pixels_below} pixels below
""".strip()
		
		return state_text
	
	def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
		"""Calculate cosine similarity between two vectors"""
		vec1 = np.array(vec1)
		vec2 = np.array(vec2)
		
		dot_product = np.dot(vec1, vec2)
		norm1 = np.linalg.norm(vec1)
		norm2 = np.linalg.norm(vec2)
		
		if norm1 == 0 or norm2 == 0:
			return 0.0
		
		return float(dot_product / (norm1 * norm2))
	
	def format_experience_message(self, similar_states: List[dict]) -> str:
		"""Format historical experience data for the agent"""
		if not similar_states:
			return ""
		
		message = "### Historical Experience from Similar States:\n\n"
		
		for i, state in enumerate(similar_states, 1):
			action = state['action'][0] if state['action'] else {}
			if not action:
				continue
			
			action_name = list(action.keys())[0]
			action_params = action.get(action_name, {})
			
			# Get the fields
			situation = state.get('situation', '')
			thinking = state.get('thinking', '')
			score = state.get('score', 0)
			reasoning = state.get('reasoning', '')
			
			message += f"**{i}. Similarity: {state['similarity']:.2f}**\n"
			message += f"- **Situation**: {situation}\n"
			message += f"- **Action and intention**: {action_name}"
			if action_params:
				message += f" with {json.dumps(action_params, ensure_ascii=False)}"
			if thinking:
				message += f" - {thinking}"
			message += f"\n- **Comment**: Score {score}/5, {reasoning}\n\n"
		
		return message.strip()
	
	def is_available(self) -> bool:
		"""Check if experience retrieval is available"""
		return (
			self.client is not None and 
			self.embeddings_data is not None and
			len(self.embeddings_data.get("state_embeddings", [])) > 0
		)