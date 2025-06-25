#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Milvus Integration for Browser Use State Embeddings

This module provides functionality to:
1. Connect to Milvus database running in Docker
2. Create collections for storing state embeddings
3. Process scored and original session files to generate embeddings
4. Store embeddings with action scores and reasoning in Milvus
5. Search for similar states based on embedding similarity
"""

import json
import numpy as np
from pathlib import Path
from typing import Dict, List, Any, Optional
from pymilvus import MilvusClient, DataType
from openai import OpenAI

class MilvusStateStore:
	"""Manages state embeddings in Milvus vector database"""
	
	def __init__(self, 
				 uri: str = "http://localhost:8001",
				 token: str = "root:Milvus",
				 db_name: str = "browser_use_db",
				 collection_name: str = "browser_state_embeddings"):
		"""Initialize Milvus connection and collection"""
		self.uri = uri
		self.token = token
		self.db_name = db_name
		self.collection_name = collection_name
		self.embedding_dim = 3072  # text-embedding-3-large dimension
		
		# Initialize client
		self.client = MilvusClient(
			uri=self.uri,
			token=self.token
		)
		print(f"[OK] Connected to Milvus at {self.uri}")
		
		# Create database if not exists
		self._setup_database()
		
		# Create or load collection
		self._setup_collection()
	
	def _setup_database(self):
		"""Create database if it doesn't exist"""
		databases = self.client.list_databases()
		if self.db_name not in databases:
			self.client.create_database(db_name=self.db_name)
			print(f"[OK] Created database '{self.db_name}'")
		else:
			print(f"[OK] Database '{self.db_name}' already exists")
		
		# Use the database
		self.client.using_database(self.db_name)
	
	def _setup_collection(self):
		"""Create or load the collection for state embeddings"""
		# Check if collection exists
		collections = self.client.list_collections()
		
		if self.collection_name not in collections:
			print(f"Creating new collection '{self.collection_name}'...")
			
			# Create collection with schema
			schema = self.client.create_schema(
				auto_id=True,
				enable_dynamic_field=True,
			)
			
			# Add fields to schema
			schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
			schema.add_field(field_name="state_text", datatype=DataType.VARCHAR, max_length=5000)  # Increased limit
			schema.add_field(field_name="action", datatype=DataType.VARCHAR, max_length=1000)
			schema.add_field(field_name="score", datatype=DataType.FLOAT)
			schema.add_field(field_name="reasoning", datatype=DataType.VARCHAR, max_length=2000)  # Increased limit
			schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=self.embedding_dim)
			
			# Create collection
			self.client.create_collection(
				collection_name=self.collection_name,
				schema=schema,
				metric_type="COSINE",  # Using cosine similarity
				consistency_level="Strong"
			)
			print(f"[OK] Collection '{self.collection_name}' created successfully")
			
			# Create index for the embedding field
			print(f"Creating index for embedding field...")
			# Use prepare_index_params method to create index params
			index_params = self.client.prepare_index_params()
			index_params.add_index(
				field_name="embedding",
				index_type="IVF_FLAT",
				metric_type="COSINE",
				params={"nlist": 128}
			)
			self.client.create_index(
				collection_name=self.collection_name,
				index_params=index_params
			)
			print(f"[OK] Index created successfully")
		else:
			print(f"[OK] Collection '{self.collection_name}' already exists")
			
			# Check if index exists, if not create it
			try:
				indexes = self.client.list_indexes(collection_name=self.collection_name)
				if "embedding" not in indexes:
					print(f"Creating index for existing collection...")
					index_params = self.client.prepare_index_params()
					index_params.add_index(
						field_name="embedding",
						index_type="IVF_FLAT",
						metric_type="COSINE",
						params={"nlist": 128}
					)
					self.client.create_index(
						collection_name=self.collection_name,
						index_params=index_params
					)
					print(f"[OK] Index created for existing collection")
				else:
					print(f"[OK] Index already exists")
			except Exception as e:
				print(f"Warning: Could not check/create index: {e}")
		
		# Load collection
		try:
			self.client.load_collection(collection_name=self.collection_name)
			print(f"[OK] Collection loaded to memory")
		except Exception as e:
			print(f"Warning: Could not load collection: {e}")
			print("Collection will be loaded when needed")
	
	def extract_state_description(self, dom_state: Dict[str, Any]) -> str:
		"""Extract and format state information for embedding"""
		
		# Core state components
		url = dom_state.get('url', '')
		title = dom_state.get('title', '')
		interactive_elements = dom_state.get('interactive_elements_text', '')
		
		# Scroll position context
		scroll_pos = dom_state.get('scroll_position', {})
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
	
	def process_with_original_data(self, scored_path: str, original_sessions_path: str, session_id: str = None):
		"""Create embeddings using both scored results and original session data and insert to Milvus"""
		print(f"\nProcessing files:")
		
		# Load both files
		with open(scored_path, 'r', encoding='utf-8') as f:
			scored_data = json.load(f)
		
		with open(original_sessions_path, 'r', encoding='utf-8') as f:
			original_data = json.load(f)
		
		# Extract session ID from filename if not provided
		if session_id is None:
			session_id = Path(scored_path).stem.replace("_scored", "")
		
		# Initialize OpenAI client with API key
		try:
			import sys
			sys.path.append('..')
			from api_key import OpenAI_API_KEY, OPENAI_BASE_URL
			# Use OpenAI API for embeddings, not OpenRouter
			openai_base = "https://api.openai.com/v1"
			client = OpenAI(api_key=OpenAI_API_KEY, base_url=openai_base)
			print(f"[OK] Loaded API key from api_key.py")
			print(f"[OK] Using OpenAI API: {openai_base}")
		except ImportError:
			print("Error: api_key.py not found!")
			print("Please create api_key.py with OpenAI_API_KEY and OPENAI_BASE_URL")
			return 0
		except Exception as e:
			print(f"Error loading from api_key.py: {e}")
			return 0
		
		# Create mapping of step_number to original step data
		original_steps = {step['step_number']: step for step in original_data['steps']}
		
		print(f"Creating embeddings for {len(scored_data['scored_steps'])} steps...")
		
		# Collect all state texts for batch embedding
		state_texts = []
		step_info = []
		
		for step in scored_data['scored_steps']:
			step_number = step['step_number']
			
			# Get original step data
			original_step = original_steps.get(step_number)
			if not original_step:
				print(f"Warning: No original data found for step {step_number}")
				continue
			
			# Extract state description
			dom_state = original_step['dom_state']
			state_text = self.extract_state_description(dom_state)
			
			state_texts.append(state_text)
			step_info.append({
				"step_number": step_number,
				"action": original_step['agent_response']['action'],
				"score": step.get('scores', {}).get('step_score', 0),
				"reasoning": step.get('scores', {}).get('overall_reasoning', ''),
				"state_text": state_text
			})
		
		# Create embeddings in batch
		print("Calling OpenAI embedding API...")
		response = client.embeddings.create(
			model="text-embedding-3-large",
			input=state_texts
		)
		
		# Prepare records for Milvus insertion
		records = []
		for i, embedding_obj in enumerate(response.data):
			step_data = step_info[i]
			
			record = {
				"state_text": step_data["state_text"][:5000],  # Increased limit
				"action": json.dumps(step_data["action"], ensure_ascii=False)[:1000],  # Store action as JSON string
				"score": float(step_data["score"]),
				"reasoning": step_data["reasoning"][:2000],  # Increased limit
				"embedding": embedding_obj.embedding
			}
			records.append(record)
		
		# Insert data to Milvus
		print(f"Inserting {len(records)} embeddings to Milvus...")
		res = self.client.insert(
			collection_name=self.collection_name,
			data=records
		)
		print(f"[OK] Inserted {res['insert_count']} embeddings successfully")
		
		# Flush to ensure data is persisted
		self.client.flush(collection_names=[self.collection_name])
		print(f"[OK] Data flushed to disk")
		
		return res['insert_count']
	
	def search_similar_states(self, 
							query_embedding: List[float], 
							top_k: int = 5,
							score_threshold: float = None) -> List[Dict[str, Any]]:
		"""Search for similar states based on embedding similarity"""
		
		# Build filter expression if needed
		filter_expr = None
		if score_threshold is not None:
			filter_expr = f"score >= {score_threshold}"
		
		# Perform search
		results = self.client.search(
			collection_name=self.collection_name,
			data=[query_embedding],
			anns_field="embedding",
			limit=top_k,
			filter=filter_expr,
			output_fields=["state_text", "action", "score", "reasoning"]
		)
		
		# Format results
		similar_states = []
		if results and len(results) > 0:
			for hit in results[0]:
				# Parse action from JSON string
				action_str = hit['entity'].get("action", "{}")
				try:
					action = json.loads(action_str)
				except:
					action = {"action": "unknown", "args": {}}
				
				similar_states.append({
					"distance": hit['distance'],
					"similarity": 1 - hit['distance'],  # Convert distance to similarity for cosine
					"state_text": hit['entity'].get("state_text"),
					"action": action,
					"score": hit['entity'].get("score"),
					"reasoning": hit['entity'].get("reasoning")
				})
		
		return similar_states
	
	def search_by_state_text(self, state_description: str, top_k: int = 5):
		"""Search for similar states by first creating embedding from text"""
		# This requires OpenAI API to create embedding
		try:
			import sys
			sys.path.append('..')
			from api_key import OpenAI_API_KEY, OPENAI_BASE_URL
			from openai import OpenAI
			
			# Use OpenAI API for embeddings
			client = OpenAI(api_key=OpenAI_API_KEY, base_url="https://api.openai.com/v1")
			
			# Create embedding for the query text
			response = client.embeddings.create(
				model="text-embedding-3-large",
				input=state_description
			)
			
			query_embedding = response.data[0].embedding
			
			# Search with the embedding
			return self.search_similar_states(query_embedding, top_k)
			
		except ImportError:
			print("Error: Cannot create embedding without OpenAI API")
			return []
	
	def get_collection_stats(self) -> Dict[str, Any]:
		"""Get statistics about the collection"""
		# Get collection info
		stats = self.client.get_collection_stats(collection_name=self.collection_name)
		
		return {
			"collection_name": self.collection_name,
			"row_count": stats.get('row_count', 0),
			"database": self.db_name,
			"uri": self.uri
		}
	
	def delete_by_score_threshold(self, score_threshold: float):
		"""Delete all embeddings with score below threshold"""
		res = self.client.delete(
			collection_name=self.collection_name,
			filter=f'score < {score_threshold}'
		)
		print(f"[OK] Deleted {res['delete_count']} embeddings with score < {score_threshold}")
	
	def drop_collection(self):
		"""Drop the entire collection (use with caution!)"""
		self.client.drop_collection(collection_name=self.collection_name)
		print(f"[OK] Collection '{self.collection_name}' dropped")


def main():
	"""Main function to process embeddings and store in Milvus"""
	# 设置默认参数，可以直接在PyCharm中运行
	class Args:
		uri = 'http://localhost:8001'
		token = 'root:Milvus'
		process = True  # 默认执行处理
		stats = True    # 默认显示统计
		drop_collection = False
	
	args = Args()
	
	# Set parameters as variables (same as state_embedder.py)
	scored_file = r"D:\supie\202506\browser-use-RL\score_json\obsidian_20250626_144509_350746_scored.json"
	original_file = r"D:\supie\202506\browser-use-RL\json_logs\obsidian_20250626_144509_350746.json"
	
	# Handle drop collection if requested
	if args.drop_collection:
		temp_client = MilvusClient(uri=args.uri, token=args.token)
		temp_client.using_database("browser_use_db")
		collections = temp_client.list_collections()
		if "browser_state_embeddings" in collections:
			temp_client.drop_collection(collection_name="browser_state_embeddings")
			print("[OK] Dropped existing collection")
		del temp_client
	
	# Initialize Milvus store
	store = MilvusStateStore(uri=args.uri, token=args.token)
	
	if args.process:
		# Check if files exist
		if not Path(scored_file).exists():
			print(f"Error: Scored file '{scored_file}' not found!")
			return
		
		if not Path(original_file).exists():
			print(f"Error: Original file '{original_file}' not found!")
			return
		
		# Process and import embeddings
		try:
			store.process_with_original_data(scored_file, original_file)
		except Exception as e:
			print(f"Error processing files: {e}")
			import traceback
			traceback.print_exc()
	
	if args.stats:
		# Show statistics
		stats = store.get_collection_stats()
		print("\nCollection Statistics:")
		print(f"- Collection: {stats['collection_name']}")
		print(f"- Database: {stats['database']}")
		print(f"- Total rows: {stats['row_count']}")
		print(f"- URI: {stats['uri']}")
	


if __name__ == "__main__":
	main()