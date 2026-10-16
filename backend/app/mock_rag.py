"""RAG simulado para probar el flujo completo sin el RAG real.

Mini catálogo con búsqueda por palabras clave. Devuelve el mismo contrato que
espera rag_client.py: {"reply_text": "...", ...}. Las respuestas son cortas
porque se muestran en una pantalla pequeña.
"""

from __future__ import annotations

import re
import unicodedata

CATALOG = [
    {"name": "Camiseta básica", "price": 80, "keywords": ["camiseta", "polera", "remera", "playera"]},
    {"name": "Jean azul", "price": 250, "keywords": ["jean", "pantalon", "vaquero"]},
    {"name": "Zapatillas running", "price": 420, "keywords": ["zapatilla", "zapato", "tenis", "calzado"]},
    {"name": "Mochila urbana", "price": 180, "keywords": ["mochila", "bolso", "maleta"]},
    {"name": "Auriculares BT", "price": 150, "keywords": ["auricular", "audifono", "cascos"]},
    {"name": "Gorra negra", "price": 60, "keywords": ["gorra", "gorro", "sombrero"]},
]


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]", " ", text)


def mock_query(text: str) -> dict:
    norm = _normalize(text)
    words = norm.split()

    if not words:
        return {"reply_text": "No te escuché bien, repite por favor.", "intent": "empty"}

    if any(w in words for w in ("hola", "buenas", "buenos")):
        return {"reply_text": "Hola, soy VoloBot. Pregúntame por un producto.", "intent": "greeting"}

    if any(w in norm for w in ("que tienes", "catalogo", "que venden", "productos")):
        names = ", ".join(p["name"] for p in CATALOG[:4])
        return {"reply_text": f"Tengo: {names} y más.", "intent": "catalog"}

    for product in CATALOG:
        if any(k in norm for k in product["keywords"]):
            return {
                "reply_text": f"{product['name']}: {product['price']} Bs. Hay stock.",
                "intent": "product",
                "product": product["name"],
            }

    return {"reply_text": f"No encontré eso. Escuché: {text}", "intent": "unknown"}
