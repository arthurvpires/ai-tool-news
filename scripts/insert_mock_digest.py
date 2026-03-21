import sys
import os
import json
from datetime import datetime
from uuid import uuid4

# Add app to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import db

# Create 3 mock items to pass the MIN_ITEMS_TO_SEND=3 threshold
mocks = [
    {
        "content_id": f"mock_{uuid4()}",
        "source": "claudeai",
        "source_type": "OFFICIAL",
        "metadata": {
            "relevant": True,
            "relevance_score": 9,
            "text": "Introducing Claude 3.7 Sonnet, our most intelligent model yet, with extended thinking capabilities for complex reasoning tasks. Available today on the Pro plan and via API.",
            "company": "Anthropic",
            "url": "https://x.com/claudeai/status/2035025492617961704",
            "images": ["https://pbs.twimg.com/media/mock_image.jpg"], # simulates an image attach
            "video": None,
            "summary": "Lançamento do Claude 3.7 Sonnet com modo 'extended thinking' para raciocínio complexo, disponível no plano Pro.",
            "category": "model_release"
        }
    },
    {
        "content_id": f"mock_{uuid4()}",
        "source": "OpenAI",
        "source_type": "OFFICIAL",
        "metadata": {
            "relevant": True,
            "relevance_score": 8,
            "text": "We're giving GPT-4o a voice. Now you can use the API to generate and understand native audio, opening up new possibilities for real-time speech apps.",
            "company": "OpenAI",
            "url": "https://x.com/GoogleLabs/status/2034337527293944228",
            "images": None,
            "video": "https://video.twimg.com/ext_tw_video/mock_video.mp4", # simulates a video attach
            "summary": "GPT-4o ganha suporte nativo a áudio via API, permitindo aplicações de voz em tempo real.",
            "category": "api_update"
        }
    },
    {
        "content_id": f"mock_{uuid4()}",
        "source": "Cursor_AI",
        "source_type": "OFFICIAL",
        "metadata": {
            "relevant": True,
            "relevance_score": 7,
            "text": "Casdasdursor 0.40 is out! Featuring parallel agents: you can now have multiple AI instances working on different parts of your codebase simultaneously.",
            "company": "Cursor",
            "url": "https://x.com/cursor_ai/status/2032148125448610145",
            "images": None,
            "video": None, # pure text link
            "summary": "Cssssssursor lança versão com multi-agentes que podem programar em paralelo na mesma base de código.",
            "category": "product_update"
        }
    }
]

print("Inserindo dados mock para teste do Digest...")

for item in mocks:
    db.mark_content_processed(
        content_id=item["content_id"],
        source=item["source"],
        metadata=item["metadata"]
    )
    print(f"✅ Inserido: {item['content_id']} ({item['metadata']['company']})")

print("\nFeito! Agora dispare /run-digest")
