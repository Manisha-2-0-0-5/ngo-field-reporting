"""
gemini_adapter.py — Gemini 1.5 Flash (free tier, no billing needed)
Uses the NEW google-genai SDK (google.generativeai is deprecated).
"""

import os
import json
import google.genai as genai
from google.genai import types

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))

SYSTEM_PROMPT = """
You are a hyperlocal crisis semantic adapter for NGO field operations in Chennai, India.
Field workers submit short voice notes or handwritten survey transcriptions in a mix of
Tamil, English, and Madras Bashai (hyperlocal dialect). Your job:

1. Translate the input into clear English.
2. Identify crisis category from: [sanitation, health_kit, food_access, power_outage,
   water_stagnation, shelter, livelihood, elderly_care, child_welfare, infrastructure]
3. Assign priority: CRITICAL / HIGH / MEDIUM / LOW
4. List dialect terms resolved (original → meaning).
5. Return ONLY valid JSON — no markdown, no preamble.

JSON schema:
{
  "summary": "one-sentence English translation",
  "crisis_tags": ["tag1", "tag2"],
  "priority": "CRITICAL|HIGH|MEDIUM|LOW",
  "dialect_resolved": [
    {"term": "original term", "meaning": "English meaning"}
  ],
  "confidence": 0.95
}
"""


def translate_field_input(raw_input: str) -> dict:
    """Translate hyperlocal field input → structured crisis signal."""
    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=SYSTEM_PROMPT + f"\n\nField input: {raw_input}",
        )
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())
    except Exception as e:
        print(f"[gemini] translate error: {e}")
        return {
            "summary": raw_input,
            "crisis_tags": ["unknown"],
            "priority": "MEDIUM",
            "dialect_resolved": [],
            "confidence": 0.0,
        }


def get_embedding(text: str) -> list:
    """
    Gemini text-embedding-004 — 768-dim vector.
    Used for semantic similarity search in Supabase pgvector.
    """
    try:
        result = client.models.embed_content(
            model="models/text-embedding-004",
            contents=text,
            config=types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY"),
        )
        return result.embeddings[0].values
    except Exception as e:
        print(f"[gemini] embedding error: {e}")
        return []

def analyze_document(file_content: bytes, mime_type: str) -> str:
    """Analyze an uploaded document or image using Gemini Vision."""
    try:
        prompt = (
            "Analyze this document/image from an NGO field worker. "
            "Extract any handwritten or printed text, describe any crisis events shown "
            "(like flooding, damage, infrastructure issues, etc.), "
            "and provide a clear English summary of the situation."
        )
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=[
                types.Part.from_bytes(data=file_content, mime_type=mime_type),
                prompt
            ]
        )
        return response.text.strip()
    except Exception as e:
        print(f"[gemini] vision error: {e}")
        return f"Could not analyze document: {e}"
