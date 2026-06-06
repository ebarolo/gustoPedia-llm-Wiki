# gnammyAssistant/wiki_builder/memory_tree_service.py
import datetime
import json
import logging
from typing import Any, List, Dict, Optional
from supabase import Client
from google import genai as google_genai
from google.genai import types as genai_types

logger = logging.getLogger(__name__)


class MemoryTreeService:
    def __init__(self, supabase_client: Client, genai_client: google_genai.Client) -> None:
        self._db = supabase_client
        self._client = genai_client

    def _embed(self, text: str) -> List[float]:
        from shared.retry import retry_sync
        result = retry_sync(
            self._client.models.embed_content,
            model="gemini-embedding-2",
            contents=text,
            config={"output_dimensionality": 768},
            max_retries=3,
            initial_delay=0.5
        )
        return result.embeddings[0].values

    def update_topic_tree(self, slug: str, is_concept: bool = False) -> bool:
        """Rigenera in modo gerarchico il Topic Tree (L2 + L1) per l'entità o concetto indicato.

        Aggrega tutte le ricette associate per produrre riassunti focalizzati
        tramite Gemini ed effettua l'upsert su wiki_tree_nodes con embedding.
        """
        table = "wiki_concepts" if is_concept else "wiki_entities"
        logger.info("Updating topic tree for slug=%s in table=%s", slug, table)

        resp = self._db.table(table).select("*").eq("slug", slug).maybe_single().execute()
        if not resp or not resp.data:
            logger.warning("Topic slug %s not found in table %s", slug, table)
            return False

        topic = resp.data
        name = topic["name"]
        recipe_ids = topic.get("source_recipe_ids") or []
        mentions = topic.get("mentions_in_sources") or []

        if not recipe_ids:
            logger.info("Topic slug=%s has no associated recipes. Skipping tree building.", slug)
            return False

        # 2. Recupero dettagli delle ricette per costruire il contesto per Gemini
        recipes_resp = self._db.table("recipes").select("id, title, description").in_("id", recipe_ids).execute()
        recipes_data = recipes_resp.data or []

        recipes_context = []
        for r in recipes_data:
            recipes_context.append(f"- Ricetta: {r['title']}\n  Descrizione: {r.get('description', '')}")

        # 3. Invio prompt a Gemini
        prompt = f"""Sei un esperto storico della gastronomia e tecnologo alimentare.
Genera una sintesi gerarchica in italiano per il tema culinario: "{name}" (tipo: {topic.get('type')}).

Di seguito trovi i dettagli delle ricette che citano o utilizzano questo tema e i contesti in cui compare:

RICETTE:
{"\n".join(recipes_context)}

CITAZIONI:
{"\n".join(f"- \"{m}\"" for m in mentions)}

Fornisci una sintesi strutturata in due livelli gerarchici:
1. Un riepilogo generale (Level 2) che definisce il tema, la sua importanza gastronomica e il ruolo nelle ricette.
2. Un elenco di massimo 4 sotto-temi specifici (Level 1) per approfondire il tema (es. abbinamenti ideali, varianti, errori comuni di preparazione, aspetti scientifici della cottura).

Rispondi SOLO con un JSON valido, senza markdown fence, senza testo extra:
{{
  "title": "{name}",
  "L2_summary": "definizione ed importanza del tema (2-3 frasi)...",
  "L1_nodes": [
    {{
      "title": "Titolo del Sotto-tema 1",
      "summary": "riassunto del sotto-tema (1-2 frasi)..."
    }}
  ]
}}"""

        try:
            from shared.retry import retry_sync
            response = retry_sync(
                self._client.models.generate_content,
                model="gemini-flash-latest",
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json"
                ),
                max_retries=3,
                initial_delay=1.0
            )
            raw_text = response.text or ""
            # Rimozione di eventuali markdown block
            if raw_text.startswith("```"):
                raw_text = raw_text.strip().removeprefix("```json").removesuffix("```").strip()
            data = json.loads(raw_text)
        except Exception:
            logger.exception("Gemini call failed for topic tree generation slug=%s", slug)
            return False

        # 4. Upsert Nodo Principale (L2)
        l2_summary = data.get("L2_summary", "")
        if not l2_summary:
            logger.warning("Gemini did not return L2_summary for slug=%s", slug)
            return False

        l2_embedding = self._embed(l2_summary)
        l2_row = {
            "tree_type": "topic",
            "entity_slug": None if is_concept else slug,
            "concept_slug": slug if is_concept else None,
            "node_level": 2,
            "title": name,
            "summary": l2_summary,
            "embedding": l2_embedding,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

        # Controllo se esiste già un L2 node per questo slug
        slug_col = "concept_slug" if is_concept else "entity_slug"
        l2_exist = self._db.table("wiki_tree_nodes")\
            .select("id")\
            .eq("tree_type", "topic")\
            .eq("node_level", 2)\
            .eq(slug_col, slug)\
            .maybe_single()\
            .execute()

        if l2_exist and l2_exist.data:
            l2_id = l2_exist.data["id"]
            self._db.table("wiki_tree_nodes").update(l2_row).eq("id", l2_id).execute()
        else:
            l2_insert = self._db.table("wiki_tree_nodes").insert(l2_row).execute()
            l2_id = l2_insert.data[0]["id"]

        # Cancellazione preventiva dei vecchi nodi L1 per questo slug (aggiornamento distruttivo)
        self._db.table("wiki_tree_nodes")\
            .delete()\
            .eq("tree_type", "topic")\
            .eq("node_level", 1)\
            .eq(slug_col, slug)\
            .execute()

        # 5. Scrittura Nuovi Nodi L1 e Giunzione con Ricette
        for node in data.get("L1_nodes", []):
            node_title = node.get("title", "")
            node_summary = node.get("summary", "")
            if not node_title or not node_summary:
                continue

            node_embedding = self._embed(node_summary)
            l1_row = {
                "tree_type": "topic",
                "entity_slug": None if is_concept else slug,
                "concept_slug": slug if is_concept else None,
                "node_level": 1,
                "title": node_title,
                "summary": node_summary,
                "parent_node_id": l2_id,
                "embedding": node_embedding
            }

            l1_insert = self._db.table("wiki_tree_nodes").insert(l1_row).execute()
            l1_id = l1_insert.data[0]["id"]

            # Associazione delle ricette contributrici
            for rid in recipe_ids:
                try:
                    self._db.table("wiki_node_recipes").insert({"node_id": l1_id, "recipe_id": rid}).execute()
                except Exception:
                    pass  # Evita crash in caso di tentati inserimenti duplicati

        logger.info("Successfully updated topic tree (L2 + L1 nodes) for slug=%s", slug)
        return True

    def generate_daily_global_tree(self) -> bool:
        """Crea un digest giornaliero (Global Tree L1) delle ricette inserite nelle ultime 24 ore."""
        logger.info("Running daily global tree generation...")
        day_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).isoformat()

        # Recupero ricette inserite nelle ultime 24 ore
        resp = self._db.table("recipes")\
            .select("id, title, description")\
            .gte("created_at", day_ago)\
            .execute()

        recipes = resp.data or []
        if not recipes:
            logger.info("No new recipes in the last 24 hours to generate a daily global digest.")
            return False

        recipes_context = []
        for r in recipes:
            recipes_context.append(f"- {r['title']}: {r.get('description', '')}")

        today_str = datetime.date.today().strftime("%d/%m/%Y")
        prompt = f"""Sei un critico gastronomico ed esperto di nutrizione.
Scrivi un breve sommario editoriale in italiano (2-4 frasi) dell'attività di cucina e inserimento ricette svolta in data {today_str}.
Di seguito trovi l'elenco delle ricette elaborate oggi:

{"\n".join(recipes_context)}

Sintetizza i temi principali affrontati oggi (es. profili di sapore predominanti, ingredienti chiave, tecniche di cottura ricorrenti o abitudini alimentari).

Rispondi SOLO con un JSON valido:
{{
  "title": "Digest Giornaliero {today_str}",
  "summary": "testo del sommario..."
}}"""

        try:
            from shared.retry import retry_sync
            response = retry_sync(
                self._client.models.generate_content,
                model="gemini-flash-latest",
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json"
                ),
                max_retries=3,
                initial_delay=1.0
            )
            raw_text = response.text or ""
            if raw_text.startswith("```"):
                raw_text = raw_text.strip().removeprefix("```json").removesuffix("```").strip()
            data = json.loads(raw_text)
        except Exception:
            logger.exception("Gemini call failed for daily global tree digest")
            return False

        summary = data.get("summary", "")
        title = data.get("title", f"Digest Giornaliero {today_str}")
        if not summary:
            return False

        embedding = self._embed(summary)
        row = {
            "tree_type": "global",
            "node_level": 1,
            "title": title,
            "summary": summary,
            "embedding": embedding
        }

        l1_insert = self._db.table("wiki_tree_nodes").insert(row).execute()
        l1_id = l1_insert.data[0]["id"]

        for r in recipes:
            try:
                self._db.table("wiki_node_recipes").insert({"node_id": l1_id, "recipe_id": r["id"]}).execute()
            except Exception:
                pass

        logger.info("Successfully created global digest node id=%s containing %d recipes", l1_id, len(recipes))
        return True
