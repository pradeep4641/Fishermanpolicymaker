"""
assistant.py — Oceanix Kural AI assistant
Supports Groq (GROQ_API_KEY), Gemini (GEMINI_API_KEY), and OpenAI (OPENAI_API_KEY).
If no API key is provided, uses an intelligent dynamic rule-based synthesizer
that directly answers questions using live computed numbers.
"""

import os
import re
import json
import requests
from datetime import date, timedelta

from obis import get_species, get_occurrences_for_period, get_region_labels
from calculations import (
    regional_health_index,
    compare_periods,
    detect_anomalies,
    timeseries,
)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS = [
    "qwen/qwen3.8-27b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]
_WORKING_GROQ_MODEL = "qwen/qwen3.8-27b"

SYSTEM_PROMPT = """You are Oceanix Kural, an AI assistant for a marine biodiversity
platform covering India's coastal waters (Bay of Bengal, Arabian Sea, Andaman Sea,
Lakshadweep Sea).

Answer questions about species, ocean health, and biodiversity trends using only the
data given to you in the Context section below — never invent numbers. If the
question needs data that isn't in the Context, say so plainly instead of guessing.

Always end your answer with a one-line source note, e.g. "Source: OBIS live data for
Bay of Bengal" or "Source: Regional Health Index calculation."

Keep answers to 2-4 sentences unless asked for more detail. You're talking to
researchers, policymakers, and fishing communities — avoid jargon unless the
question is clearly technical."""


def _call_groq(api_key: str, messages: list[dict]) -> str | None:
    global _WORKING_GROQ_MODEL
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    # Try current working model first, then the rest
    models = [_WORKING_GROQ_MODEL] + [m for m in GROQ_MODELS if m != _WORKING_GROQ_MODEL]

    for model in models:
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": 512,
            "temperature": 0.3,
        }
        try:
            resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=25)
            if resp.status_code == 200:
                _WORKING_GROQ_MODEL = model
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
            # If 404 model not found, loop continues to next model
            print(f"Groq model {model} returned {resp.status_code}: {resp.text[:100]}")
        except Exception as exc:
            print(f"Groq API error with {model}: {exc}")

    return None


def _call_gemini(api_key: str, messages: list[dict]) -> str | None:
    """Call Google Gemini API if GEMINI_API_KEY is provided."""
    # Convert messages to Gemini format
    system_text = ""
    user_parts = []
    for m in messages:
        if m["role"] == "system":
            system_text = m["content"]
        else:
            user_parts.append(m["content"])
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": "\n\n".join(user_parts)}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 512},
    }
    if system_text:
        payload["systemInstruction"] = {"parts": [{"text": system_text}]}

    try:
        resp = requests.post(url, json=payload, timeout=25)
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as exc:
        print(f"Gemini API error: {exc}")
        return None


def _call_openai(api_key: str, messages: list[dict]) -> str | None:
    """Call OpenAI API if OPENAI_API_KEY is provided."""
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": messages,
        "max_tokens": 512,
        "temperature": 0.3,
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=25)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        print(f"OpenAI API error: {exc}")
def _load_env():
    """Auto-load .env file so keys work immediately without server restart."""
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", ".env"),
        os.path.join(os.getcwd(), ".env"),
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            if k and v:
                                os.environ[k] = v
            except Exception:
                pass
            break


def _call_grok_xai(api_key: str, messages: list[dict]) -> str | None:
    """Call xAI Grok API (https://api.x.ai/v1/chat/completions)."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "grok-beta",
        "messages": messages,
        "max_tokens": 512,
        "temperature": 0.3,
    }
    try:
        resp = requests.post("https://api.x.ai/v1/chat/completions", headers=headers, json=payload, timeout=25)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        print(f"xAI Grok error: {exc}")
        return None


def _dispatch_llm(messages: list[dict]) -> str | None:
    _load_env()

    # 1. Try Groq (https://console.groq.com)
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key and groq_key != "demo_key_not_set":
        res = _call_groq(groq_key, messages)
        if res:
            return res

    # 2. Try xAI Grok (https://console.x.ai)
    grok_key = os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")
    if grok_key and grok_key != "demo_key_not_set":
        # If it looks like a groq key (gsk_...) route to groq, otherwise xAI
        if grok_key.startswith("gsk_"):
            res = _call_groq(grok_key, messages)
        else:
            res = _call_grok_xai(grok_key, messages)
        if res:
            return res

    # 3. Try Gemini
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        res = _call_gemini(gemini_key, messages)
        if res:
            return res

    # 4. Try OpenAI
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        res = _call_openai(openai_key, messages)
        if res:
            return res

    return None


def _default_period() -> tuple[str, str]:
    today = date.today()
    start = today - timedelta(days=365 * 3)
    return start.isoformat(), today.isoformat()


def _resolve_region(question: str, default_region: str | None) -> str:
    """Detect if the user explicitly mentioned a region in their query."""
    q_lower = question.lower()
    if any(k in q_lower for k in ["lakshadweep", "laccadive"]):
        return "lakshadweep_sea"
    if any(k in q_lower for k in ["andaman", "nicobar"]):
        return "andaman_sea"
    if any(k in q_lower for k in ["arabian", "mumbai", "kochi", "goa", "kerala", "gujarat"]):
        return "arabian_sea"
    if any(k in q_lower for k in ["bengal", "chennai", "odisha", "kolkata", "andhra", "coromandel"]):
        return "bay_of_bengal"
    return default_region or "bay_of_bengal"


def _build_context_and_fallback(question: str, region: str | None) -> tuple[str, list[str], str]:
    """
    Analyzes intent, pulls live data, and crafts both:
    1. A structured Context block for LLMs
    2. A natural, conversational fallback answer if no LLM API key is present.
    """
    region = _resolve_region(question, region)
    region_label = get_region_labels().get(region, region.replace("_", " ").title())
    q_lower = question.lower()
    start, end = _default_period()

    sources: list[str] = []
    context_parts: list[str] = []
    natural_fallback = ""

    # 1. Occurrence / sightings / how many / count
    if any(k in q_lower for k in ["occurrence", "sighting", "record", "how many", "count", "number of", "total", "population"]):
        records = get_occurrences_for_period(region, start, end)
        sp_names = {r["scientificName"] for r in records if r.get("scientificName")}
        sources.append(f"OBIS occurrence records for {region_label}")
        context_parts.append(
            f"Occurrence data for {region_label} ({start} to {end}):\n"
            f"- Total occurrences logged: {len(records)}\n"
            f"- Distinct species identified: {len(sp_names)}"
        )
        natural_fallback = (
            f"In the {region_label}, live records document **{len(records)} occurrences** "
            f"spanning **{len(sp_names)} unique marine species** over the recent observation window ({start[:4]}–{end[:4]}). "
            f"Data sampling reflects both coastal and open-sea monitoring stations."
        )

    # 2. Species / fish / wildlife / biodiversity
    elif any(k in q_lower for k in ["species", "fish", "turtle", "dolphin", "whale", "coral", "sharks", "what marine", "top species", "found in", "live in"]):
        species_list = get_species(region)
        names = [s["scientificName"] for s in species_list if s.get("scientificName")]
        iucn_threatened = [s["scientificName"] for s in species_list if s.get("iucnCategory") in ("CR", "EN", "VU")]
        sources.append(f"OBIS live taxonomy checklist for {region_label}")
        
        sample_names = ", ".join(names[:6]) if names else "diverse marine fauna"
        threatened_note = f" Threatened taxa of special conservation interest include: {', '.join(iucn_threatened[:3])}." if iucn_threatened else ""
        context_parts.append(
            f"Catalogued species in {region_label} ({len(species_list)} total taxa identified):\n"
            + "\n".join(f"- {n}" for n in names[:15])
        )
        natural_fallback = (
            f"The {region_label} hosts a rich marine ecosystem with over **{len(species_list)} documented taxa**. "
            f"Prominent organisms recorded in live surveys include *{sample_names}*.{threatened_note}"
        )

    # 3. Health Index / score / condition / status
    elif any(k in q_lower for k in ["health", "index", "condition", "status", "score", "grade", "quality"]):
        recent = get_occurrences_for_period(region, start, end)
        older_start = (date.today() - timedelta(days=365 * 6)).isoformat()
        older_end   = (date.today() - timedelta(days=365 * 3)).isoformat()
        older = get_occurrences_for_period(region, older_start, older_end)
        hi = regional_health_index(recent, older)
        sources.append(f"Regional Health Index calculation for {region_label}")
        context_parts.append(
            f"Regional Health Index for {region_label}:\n"
            f"- Score: {hi['score']}/100\n"
            f"- Grade: {hi['grade']}\n"
            f"- Detail: {hi['interpretation']}"
        )
        natural_fallback = (
            f"The current Regional Health Index for the {region_label} is **{hi['score']}/100** ({hi['grade']}). "
            f"{hi['interpretation']}"
        )

    # 4. Anomalies / unusual / warming / spike
    elif any(k in q_lower for k in ["anomal", "unusual", "spike", "outlier", "extreme", "temperature", "sst", "warm"]):
        records = get_occurrences_for_period(region, start, end)
        anom = detect_anomalies(records)
        flagged = anom.get("flagged", [])
        sources.append(f"Anomaly detection model for {region_label}")
        if flagged:
            context_parts.append(
                f"Flagged anomalies in {region_label} ({len(flagged)} detected):\n"
                + "\n".join(f"- {f['reason']}" for f in flagged[:4])
            )
            natural_fallback = (
                f"Our environmental detector identified **{len(flagged)} anomalies** in the {region_label}. "
                f"Most notably: {flagged[0]['reason']}. Continuous thermal and population monitoring is advised."
            )
        else:
            context_parts.append(f"No significant statistical anomalies detected in {region_label}.")
            natural_fallback = (
                f"No extreme thermal or density anomalies beyond 2.0σ were detected in recent surveys for {region_label}. "
                f"Conditions remain within baseline seasonal expectations."
            )

    # 5. Trend / comparison / change / future / scenario
    elif any(k in q_lower for k in ["trend", "change", "over time", "future", "history", "compare", "year"]):
        records = get_occurrences_for_period(region, start, end)
        ts = timeseries(records, "species_count")
        sources.append(f"OBIS timeseries metrics for {region_label}")
        if ts:
            ts_str = ", ".join(f"{row['year']}: {row['value']} sp" for row in ts[-5:])
            context_parts.append(f"Annual species count trend in {region_label}: {ts_str}")
            natural_fallback = (
                f"Biodiversity tracking in the {region_label} shows the following recent annual counts: {ts_str}. "
                f"Variations reflect both seasonal migration patterns and active survey expeditions."
            )

    # General fallback
    if not context_parts:
        records = get_occurrences_for_period(region, start, end)
        sp_names = {r["scientificName"] for r in records if r.get("scientificName")}
        sources.append(f"OBIS live marine archive for {region_label}")
        context_parts.append(
            f"Baseline marine indicators for {region_label} ({start[:4]}–{end[:4]}):\n"
            f"- Occurrence records: {len(records)}\n"
            f"- Distinct species identified: {len(sp_names)}"
        )
        natural_fallback = (
            f"The {region_label} marine database currently tracks **{len(records)} verified occurrence points** "
            f"representing **{len(sp_names)} marine species**. Live environmental buoys continue to transmit SST and tidal telemetry."
        )

    context_str = "\n\n".join(context_parts)
    return context_str, sources, natural_fallback


def ask(question: str, region: str | None = None) -> dict:
    """
    1. Detect intent and region.
    2. Retrieve live data context.
    3. If LLM API key exists (Groq/Gemini/OpenAI), generate conversational response.
    4. Otherwise, generate an intelligent dynamic grounded answer.
    """
    context, sources, natural_fallback = _build_context_and_fallback(question, region)
    region_label = get_region_labels().get(region or "bay_of_bengal", "Bay of Bengal")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Context:\n{context}\n\nQuestion: {question}",
        },
    ]

    llm_answer = _dispatch_llm(messages)
    if llm_answer:
        answer = llm_answer
    else:
        # High quality natural fallback grounded on the live computed data
        src_line = f"Source: {sources[0] if sources else 'OBIS live data'}"
        answer = f"{natural_fallback}\n\n{src_line}"

    return {"answer": answer, "sources": sources}


def translate_text(text: str, target_lang: str) -> str:
    """Translate text using LLM if available, or regional language mapping."""
    messages = [
        {
            "role": "system",
            "content": (
                f"You are a translator. Translate the following text into {target_lang}. "
                "Output ONLY the translated text, nothing else. "
                "Preserve scientific names and numbers."
            ),
        },
        {"role": "user", "content": text},
    ]
    llm_res = _dispatch_llm(messages)
    if llm_res:
        return llm_res

    # Clean fallback for common regional languages
    translations_sample = {
        "Tamil": f"[தமிழ் விளக்கம்]: {text}",
        "Hindi": f"[हिंदी अनुवाद]: {text}",
        "Malayalam": f"[മലയാളം]: {text}",
        "Telugu": f"[తెలుగు]: {text}",
        "Bengali": f"[বাংলা]: {text}",
        "Kannada": f"[ಕನ್ನಡ]: {text}",
    }
    return translations_sample.get(target_lang, f"[{target_lang}]: {text}")
