import sys
import os
import asyncio
from typing import Dict, Any, List

# Add app to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.analyzer.ai_analyzer import AIAnalyzer
from app.config import settings

async def test_deduplication():
    print("Starting deduplication test...")
    analyzer = AIAnalyzer()
    
    # Mock some recent relevant items
    recent_relevant = [
        {
            "content_id": "tweet_123",
            "text": "Claude 3.5 Sonnet is now available on our API with significant improvements in coding and reasoning.",
            "source_type": "OFFICIAL"
        },
        {
            "content_id": "tweet_456",
            "text": "OpenAI launches o1, a new series of reasoning models for complex tasks.",
            "source_type": "OFFICIAL"
        }
    ]
    
    # Test 1: Exact duplicate content (worded differently)
    print("\nTest 1: Similar content (Duplicate)")
    new_content_1 = "Anthropic just released Claude 3.5 Sonnet! You can try it now via the API if you want better coding performance."
    result_1 = analyzer.find_duplicate(new_content_1, recent_relevant)
    print(f"Result: {result_1}")
    
    # Test 2: Different content
    print("\nTest 2: Different content (Not Duplicate)")
    new_content_2 = "Gemini 1.5 Pro now has a 2M token context window."
    result_2 = analyzer.find_duplicate(new_content_2, recent_relevant)
    print(f"Result: {result_2}")
    
    # Test 3: Influence reporting on same news
    print("\nTest 3: Secondary source reporting same news (Duplicate)")
    new_content_3 = "BREAKING: OpenAI o1 is here! The new reasoning models are insane. Check it out at chatgpt.com"
    result_3 = analyzer.find_duplicate(new_content_3, recent_relevant)
    print(f"Result: {result_3}")

    # Simulation of jobs.py logic
    print("\n--- Simulation of jobs.py Prioritization ---")
    incoming_batch = [
        {"id": "influencer_post_1", "text": "New Sora update from OpenAI!", "source_type": "SECONDARY"},
        {"id": "official_post_1", "text": "We are excited to share new capabilities for Sora.", "source_type": "OFFICIAL"},
    ]
    
    # Sorting as done in jobs.py: OFFICIAL (0) vs SECONDARY (1)
    sorted_batch = sorted(incoming_batch, key=lambda x: 0 if x.get("source_type") == "OFFICIAL" else 1)
    
    print("Sorted Batch (How the system will process them):")
    for item in sorted_batch:
        print(f"- {item['id']} ({item['source_type']})")
    
    print("\nNote: The priority is defined in 'app/collectors/twitter_sources.json' and enforced in 'app/scheduler/jobs.py'.")

if __name__ == "__main__":
    has_openai = settings.OPENAI_API_KEY and settings.OPENAI_API_KEY != "your_openai_api_key"
    has_groq = settings.GROQ_API_KEY and settings.GROQ_API_KEY != "your_groq_api_key"
    
    if not has_openai and not has_groq:
        print("ERROR: Neither OPENAI_API_KEY nor GROQ_API_KEY set. Cannot run LLM test.")
    else:
        asyncio.run(test_deduplication())
