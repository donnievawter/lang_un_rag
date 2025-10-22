# debug_similarity.py
from app.vector_store import vector_store
import numpy as np, traceback

def cos_sim(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if np.linalg.norm(a) == 0 or np.linalg.norm(b) == 0:
        return float("-inf")
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

try:
    vs = vector_store
    vs.initialize()  # ensures _vectorstore is loaded
    coll = vs._vectorstore._collection

    # NOTE: do NOT include "ids" in include; get() returns ids by default
    results = coll.get(limit=None, include=["documents", "metadatas", "embeddings"])
    ids = results.get("ids", [])
    metadatas = results.get("metadatas", [])
    docs = results.get("documents", [])
    embeddings = results.get("embeddings", [])

    # Robust check for empty embeddings and coerce to list for safe iteration
    if embeddings is None:
        print("No embeddings found (embeddings is None).")
        raise SystemExit(1)
    # If embeddings is a numpy array, list() will produce a list of 1-D arrays (one per vector)
    embeddings_list = list(embeddings) if not isinstance(embeddings, list) else embeddings

    if len(embeddings_list) == 0:
        print("No embeddings found (empty list).")
        raise SystemExit(1)

    print(f"Loaded {len(ids)} items from Chroma.")
    query_text = "how do I set up qdevice"
    q_emb = vs.embed_query(query_text)
    print("Query embedding len:", len(q_emb), "preview:", q_emb[:6])
    first_emb = embeddings_list[0]
    print("Stored embedding len (first):", len(first_emb), "preview:", first_emb[:6])

    sims = []
    for i, e in enumerate(embeddings_list):
        try:
            score = cos_sim(q_emb, e)
        except Exception:
            score = float("-inf")
        src = metadatas[i].get("source") if i < len(metadatas) and metadatas[i] else None
        sims.append((score, ids[i], src, docs[i][:300] if i < len(docs) else ""))

    sims_sorted = sorted(sims, key=lambda x: x[0], reverse=True)
    print("\nTop 20 similar chunks:")
    for r, (score, id_, src, snippet) in enumerate(sims_sorted[:20], 1):
        print(f"{r:02d}. score={score:.6f} id={id_} source={src}")
        print(snippet.replace('\\n',' ') + "\n---")

except Exception:
    print("ERROR:")
    traceback.print_exc()