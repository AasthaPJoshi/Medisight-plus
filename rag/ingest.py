"""
FILE: rag/ingest.py
===================
WHAT THIS FILE IS:
    The knowledge base builder. Fetches medical abstracts from PubMed
    (free, no API key needed), embeds them locally using sentence-transformers,
    and uploads them to Pinecone for semantic search.

CONCEPT:
    PubMed has 35M+ free medical abstracts via the NCBI E-utilities API.
    We fetch ~500 abstracts across common medical topics, split them into
    chunks, embed each chunk into a 384-dimensional vector, and store
    those vectors in Pinecone. Later, when a doctor asks about symptoms,
    we search Pinecone for the most relevant chunks.

    Embedding model: all-MiniLM-L6-v2 (free, runs locally, 384 dimensions)
    This matches the Pinecone index dimension we created (384).

HOW TO RUN:
    python3 rag/ingest.py

    First run: downloads the embedding model (~80MB), fetches PubMed,
    uploads to Pinecone. Takes 5-10 minutes.
    Subsequent runs: model is cached, just re-uploads.

INPUT:  PubMed E-utilities API (free, no key), Pinecone credentials from .env
OUTPUT: Pinecone index populated with medical knowledge chunks

CHECK IT WORKED:
    python3 -c "
    from pinecone import Pinecone
    import os; from dotenv import load_dotenv; load_dotenv()
    pc = Pinecone(api_key=os.getenv('PINECONE_API_KEY'))
    idx = pc.Index(os.getenv('PINECONE_INDEX_NAME'))
    print(idx.describe_index_stats())
    "
    Should show total_vector_count > 0
"""

import os
import sys
import time
import pickle
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Any

from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from pinecone import Pinecone, ServerlessSpec
from rank_bm25 import BM25Okapi

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

PINECONE_API_KEY   = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX     = os.getenv("PINECONE_INDEX_NAME", "medisight-kb")
EMBED_MODEL        = "all-MiniLM-L6-v2"   # 384 dimensions, free, runs locally
EMBED_DIM          = 384
BM25_PATH          = Path(__file__).parent.parent / "data" / "bm25_index.pkl"
BATCH_SIZE         = 100   # Pinecone upsert batch size

# Medical topics to fetch from PubMed
# Each term fetches up to 50 abstracts
PUBMED_TOPICS = [
    "chest pain diagnosis",
    "type 2 diabetes management",
    "hypertension treatment guidelines",
    "pneumonia clinical presentation",
    "urinary tract infection antibiotics",
    "acute myocardial infarction symptoms",
    "asthma exacerbation treatment",
    "COPD management",
    "depression anxiety treatment",
    "headache migraine differential diagnosis",
    "fever evaluation adults",
    "back pain treatment",
    "shortness of breath differential",
    "abdominal pain evaluation",
    "hyperlipidemia statin therapy",
]

PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: FETCH PUBMED ABSTRACTS
# ─────────────────────────────────────────────────────────────────────────────

def fetch_pubmed_abstracts(topic: str, max_results: int = 30) -> List[Dict]:
    """
    Fetch abstracts from PubMed E-utilities API (completely free, no key needed).

    Two-step process:
    1. esearch: search PubMed for the topic, get a list of PMIDs
    2. efetch: fetch the actual abstract text for each PMID

    INPUT:  topic string (e.g. "chest pain diagnosis"), max results to fetch
    OUTPUT: list of dicts with {pmid, title, abstract, source}
    """
    abstracts = []

    try:
        # Step 1: Search for PMIDs
        search_url = f"{PUBMED_BASE}/esearch.fcgi"
        search_params = {
            "db": "pubmed",
            "term": topic,
            "retmax": max_results,
            "retmode": "json",
            "sort": "relevance",
        }
        search_resp = requests.get(search_url, params=search_params, timeout=15)
        search_data = search_resp.json()
        pmids = search_data.get("esearchresult", {}).get("idlist", [])

        if not pmids:
            print(f"   ⚠️  No results for: {topic}")
            return []

        # Step 2: Fetch abstracts for those PMIDs
        fetch_url = f"{PUBMED_BASE}/efetch.fcgi"
        fetch_params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "rettype": "abstract",
            "retmode": "xml",
        }
        fetch_resp = requests.get(fetch_url, params=fetch_params, timeout=30)
        root = ET.fromstring(fetch_resp.content)

        # Parse the XML response
        for article in root.findall(".//PubmedArticle"):
            try:
                # Get PMID
                pmid_el = article.find(".//PMID")
                pmid = pmid_el.text if pmid_el is not None else "unknown"

                # Get title
                title_el = article.find(".//ArticleTitle")
                title = title_el.text if title_el is not None else ""
                if not title:
                    continue

                # Get abstract text (may have multiple AbstractText elements)
                abstract_els = article.findall(".//AbstractText")
                abstract_parts = []
                for el in abstract_els:
                    text = el.text or ""
                    label = el.get("Label", "")
                    if label:
                        abstract_parts.append(f"{label}: {text}")
                    else:
                        abstract_parts.append(text)
                abstract = " ".join(abstract_parts).strip()

                if len(abstract) < 100:
                    continue  # Skip very short abstracts

                abstracts.append({
                    "pmid": pmid,
                    "title": title,
                    "abstract": abstract,
                    "topic": topic,
                    "source": f"PubMed PMID:{pmid}",
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                })

            except Exception:
                continue

    except Exception as e:
        print(f"   ⚠️  PubMed fetch error for '{topic}': {e}")

    return abstracts


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2: CHUNK TEXT
# ─────────────────────────────────────────────────────────────────────────────

def chunk_abstract(doc: Dict, chunk_size: int = 400, overlap: int = 50) -> List[Dict]:
    """
    Split a long abstract into overlapping chunks for better retrieval.

    Why chunk? Embedding models work best on shorter text (200-500 words).
    A long abstract embedded as one vector loses detail.
    Overlapping chunks (50 word overlap) ensure context isn't lost at boundaries.

    INPUT:  one abstract dict, chunk_size in words, overlap in words
    OUTPUT: list of chunk dicts with {id, text, metadata}
    """
    # Combine title + abstract for richer context
    full_text = f"{doc['title']}. {doc['abstract']}"
    words = full_text.split()

    chunks = []
    start = 0
    chunk_idx = 0

    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk_text = " ".join(words[start:end])

        chunks.append({
            "id": f"pmid_{doc['pmid']}_chunk_{chunk_idx}",
            "text": chunk_text,
            "metadata": {
                "pmid": doc["pmid"],
                "title": doc["title"],
                "topic": doc["topic"],
                "source": doc["source"],
                "url": doc["url"],
                "chunk_idx": chunk_idx,
            }
        })

        chunk_idx += 1
        # Move forward by (chunk_size - overlap) to create overlapping windows
        start += chunk_size - overlap

        if end == len(words):
            break

    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3: EMBED CHUNKS
# ─────────────────────────────────────────────────────────────────────────────

def embed_chunks(chunks: List[Dict], model: SentenceTransformer) -> List[Dict]:
    """
    Convert each chunk's text into a 384-dimensional vector.

    The embedding model (all-MiniLM-L6-v2) converts text into a vector
    where semantically similar texts have vectors close together in space.
    This is what allows "chest discomfort" to match "chest pain" even
    without exact keyword overlap.

    INPUT:  list of chunks, loaded SentenceTransformer model
    OUTPUT: same chunks with 'embedding' field added (list of 384 floats)
    """
    texts = [chunk["text"] for chunk in chunks]
    # batch_size=32 balances speed and memory usage
    embeddings = model.encode(texts, batch_size=32, show_progress_bar=False)

    for chunk, embedding in zip(chunks, embeddings):
        chunk["embedding"] = embedding.tolist()

    return chunks


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4: UPLOAD TO PINECONE
# ─────────────────────────────────────────────────────────────────────────────

def upload_to_pinecone(chunks: List[Dict], index) -> int:
    """
    Upload embedded chunks to Pinecone in batches.

    Pinecone stores each vector with:
    - id: unique string identifier
    - values: the 384-dimensional embedding vector
    - metadata: title, PMID, URL — returned with search results

    INPUT:  embedded chunks, Pinecone index object
    OUTPUT: number of vectors uploaded
    """
    uploaded = 0

    # Upsert in batches (Pinecone has a limit per request)
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i:i + BATCH_SIZE]
        vectors = [
            {
                "id": chunk["id"],
                "values": chunk["embedding"],
                "metadata": chunk["metadata"],
            }
            for chunk in batch
        ]
        index.upsert(vectors=vectors)
        uploaded += len(batch)

    return uploaded


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5: BUILD BM25 INDEX
# ─────────────────────────────────────────────────────────────────────────────

def build_bm25_index(chunks: List[Dict]):
    """
    Build a BM25 keyword index from all chunks and save to disk.

    BM25 is a classic information retrieval algorithm that finds documents
    containing specific keywords. Combined with Pinecone's semantic search
    (which finds conceptually similar documents), we get hybrid retrieval
    that handles both exact keyword matches AND semantic similarity.

    This combination is called Reciprocal Rank Fusion (RRF) — we run both
    searches, get two ranked lists, and combine them.

    INPUT:  list of all chunks
    OUTPUT: BM25Okapi index saved to data/bm25_index.pkl

    IMPORTANT: Save the chunks list alongside the index so we can look up
    the original text when BM25 returns result indices.
    """
    print("   Building BM25 keyword index...")

    # Tokenize each chunk by splitting on whitespace
    tokenized_chunks = [chunk["text"].lower().split() for chunk in chunks]
    bm25 = BM25Okapi(tokenized_chunks)

    # Save both the index and the chunk texts (needed to map indices back to content)
    BM25_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(BM25_PATH, "wb") as f:
        # Save as a dict so we can load both pieces together
        pickle.dump({
            "bm25": bm25,
            "chunks": [{"id": c["id"], "text": c["text"], "metadata": c["metadata"]}
                       for c in chunks]
        }, f)

    print(f"   ✅ BM25 index saved to {BM25_PATH}")
    return bm25


# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def run_ingestion():
    """
    Full ingestion pipeline:
    1. Fetch abstracts from PubMed for each topic
    2. Chunk each abstract
    3. Load embedding model
    4. Embed all chunks
    5. Upload to Pinecone
    6. Build BM25 keyword index
    """
    print("=" * 60)
    print("🏥  MediSight+ Knowledge Base Ingestion")
    print("=" * 60)

    if not PINECONE_API_KEY:
        print("❌ PINECONE_API_KEY not set in .env")
        return

    # ── Step 1: Connect to Pinecone ───────────────────────────────────────────
    print("\n📡 Connecting to Pinecone...")
    pc = Pinecone(api_key=PINECONE_API_KEY)

    # Check if index exists, create if not
    existing = [idx.name for idx in pc.list_indexes()]
    if PINECONE_INDEX not in existing:
        print(f"   Creating index '{PINECONE_INDEX}'...")
        pc.create_index(
            name=PINECONE_INDEX,
            dimension=EMBED_DIM,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1")
        )
        time.sleep(10)  # Wait for index to be ready
        print(f"   ✅ Index created")
    else:
        print(f"   ✅ Index '{PINECONE_INDEX}' already exists")

    index = pc.Index(PINECONE_INDEX)

    # ── Step 2: Load embedding model ──────────────────────────────────────────
    print(f"\n🤖 Loading embedding model ({EMBED_MODEL})...")
    print("   First run downloads ~80MB — cached after that")
    model = SentenceTransformer(EMBED_MODEL)
    print("   ✅ Model loaded")

    # ── Step 3: Fetch PubMed abstracts ────────────────────────────────────────
    print(f"\n📚 Fetching PubMed abstracts for {len(PUBMED_TOPICS)} topics...")
    all_abstracts = []

    for i, topic in enumerate(PUBMED_TOPICS):
        print(f"   [{i+1}/{len(PUBMED_TOPICS)}] {topic}...")
        abstracts = fetch_pubmed_abstracts(topic, max_results=30)
        all_abstracts.extend(abstracts)
        print(f"   Fetched {len(abstracts)} abstracts")
        time.sleep(0.5)  # Be polite to the PubMed API

    # Deduplicate by PMID (same paper may appear in multiple topics)
    seen_pmids = set()
    unique_abstracts = []
    for doc in all_abstracts:
        if doc["pmid"] not in seen_pmids:
            seen_pmids.add(doc["pmid"])
            unique_abstracts.append(doc)

    print(f"\n   Total unique abstracts: {len(unique_abstracts)}")

    # ── Step 4: Chunk all abstracts ───────────────────────────────────────────
    print("\n✂️  Chunking abstracts...")
    all_chunks = []
    for doc in unique_abstracts:
        chunks = chunk_abstract(doc)
        all_chunks.extend(chunks)

    print(f"   Total chunks: {len(all_chunks)}")

    # ── Step 5: Embed all chunks ──────────────────────────────────────────────
    print(f"\n🔢 Embedding {len(all_chunks)} chunks...")
    print("   This takes 2-5 minutes on first run")
    all_chunks = embed_chunks(all_chunks, model)
    print("   ✅ Embedding complete")

    # ── Step 6: Upload to Pinecone ────────────────────────────────────────────
    print(f"\n⬆️  Uploading to Pinecone index '{PINECONE_INDEX}'...")
    uploaded = upload_to_pinecone(all_chunks, index)
    print(f"   ✅ Uploaded {uploaded} vectors")

    # ── Step 7: Build BM25 index ──────────────────────────────────────────────
    print("\n🔍 Building BM25 keyword index...")
    build_bm25_index(all_chunks)

    # ── Step 8: Verify ────────────────────────────────────────────────────────
    print("\n✅ Verifying Pinecone index...")
    time.sleep(2)  # Wait for Pinecone to index the vectors
    stats = index.describe_index_stats()
    total_vectors = stats.get("total_vector_count", 0)
    print(f"   Pinecone vector count: {total_vectors}")

    print("\n" + "=" * 60)
    print("✅ Knowledge base ingestion complete!")
    print(f"   PubMed abstracts fetched: {len(unique_abstracts)}")
    print(f"   Chunks created: {len(all_chunks)}")
    print(f"   Vectors in Pinecone: {total_vectors}")
    print(f"   BM25 index: {BM25_PATH}")
    print("\nNext step: python3 -m uvicorn api.main:app --reload")
    print("=" * 60)


if __name__ == "__main__":
    run_ingestion()
