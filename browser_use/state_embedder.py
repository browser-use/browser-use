#!/usr/bin/env python3
"""
State Embedder for Browser Use Agent

This module converts DOM states from scored sessions into embeddings
for similarity-based retrieval of historical experiences.
"""

import json
from pathlib import Path
from typing import Dict, List, Any
from openai import OpenAI

def extract_state_description(dom_state: Dict[str, Any]) -> str:
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

def process_with_original_data(scored_path: str, original_sessions_path: str, output_path: str = None) -> Dict[str, Any]:
    """Create embeddings using both scored results and original session data"""
    
    # Load both files
    with open(scored_path, 'r', encoding='utf-8') as f:
        scored_data = json.load(f)
    
    with open(original_sessions_path, 'r', encoding='utf-8') as f:
        original_data = json.load(f)
    
    # Initialize OpenAI client with API key
    try:
        from api_key import OpenAI_API_KEY, OPENAI_BASE_URL
        client = OpenAI(api_key=OpenAI_API_KEY, base_url=OPENAI_BASE_URL)
        print(f"✓ Loaded API key from api_key.py")
        print(f"✓ Base URL: {OPENAI_BASE_URL}")
    except ImportError:
        print("Error: api_key.py not found!")
        print("Please create api_key.py with OpenAI_API_KEY and OPENAI_BASE_URL")
        return None
    except Exception as e:
        print(f"Error loading from api_key.py: {e}")
        return None
    
    # Create mapping of step_number to original step data
    original_steps = {step['step_number']: step for step in original_data['steps']}
    
    embeddings_data = {
        "metadata": {
            "model": "text-embedding-3-large",
            "total_steps": len(scored_data['scored_steps']),
            "source_files": {
                "scored": scored_path,
                "original": original_sessions_path
            }
        },
        "state_embeddings": []
    }
    
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
        state_text = extract_state_description(dom_state)
        
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
    
    # Combine embeddings with step data
    for i, embedding_obj in enumerate(response.data):
        step_data = step_info[i]
        
        embeddings_data["state_embeddings"].append({
            "step_number": step_data["step_number"],
            "state_text": step_data["state_text"],
            "state_embedding": embedding_obj.embedding,
            "action": step_data["action"],
            "score": step_data["score"],
            "reasoning": step_data["reasoning"]
        })
    
    # Save output
    if output_path is None:
        output_path = scored_path.replace('.json', '_embeddings.json')
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(embeddings_data, f, indent=2, ensure_ascii=False)
    
    print(f"✓ Embeddings created successfully!")
    print(f"✓ Saved to: {output_path}")
    print(f"✓ Total embeddings: {len(embeddings_data['state_embeddings'])}")
    
    return embeddings_data

def main():
    """Main function for command-line usage"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Create state embeddings from scored sessions')
    parser.add_argument('scored_file', nargs='?', default='browser_use/all_sessions_scored.json', 
                       help='Path to the scored sessions JSON file')
    parser.add_argument('original_file', nargs='?', default='all_sessions.json',
                       help='Path to the original sessions JSON file')
    parser.add_argument('--output', '-o', help='Output file path')
    
    args = parser.parse_args()
    
    # Check if files exist
    if not Path(args.scored_file).exists():
        print(f"Error: Scored file '{args.scored_file}' not found!")
        return
    
    if not Path(args.original_file).exists():
        print(f"Error: Original file '{args.original_file}' not found!")
        return
    
    # Create embeddings
    try:
        process_with_original_data(args.scored_file, args.original_file, args.output)
    except Exception as e:
        print(f"Error creating embeddings: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()

