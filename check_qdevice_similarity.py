# check_qdevice_similarity.py
from app.vector_store import vector_store
import numpy as np, traceback

def cos_sim(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if np.linalg.norm(a) == 0 or np.linalg.norm(b) == 0:
        return float("-inf")
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

# Put the exact ids you saw in get_chunks output here:
QDEVICE_IDS = [
    "qdevice_quorum_proxmox.md::qdevice_quorum_proxmox.md::138",
    "qdevice_quorum_proxmox.md::qdevice_quorum_proxmox.md::139",
    "qdevice_quorum_proxmox.md::qdevice_quorum_proxmox.md::140",
]

try:
    vs = vector_store
    vs.initialize()
    coll = vs._vectorstore._collection

    results = coll.get(limit=None, include=["documents", "metadatas", "embeddings"])
    ids = results.get("ids", [])
    docs = results.get("documents", [])
    metadatas = results.get("metadatas", [])
    embeddings = results.get("embeddings", [])
    embeddings_list = list(embeddings) if not isinstance(embeddings, list) else embeddings

    print(f"Loaded {len(ids)} items from Chroma.")

    query_text = "how do I set up qdevice"
    q_emb = vs.embed_query(query_text)
    print("Query embedding len:", len(q_emb))

    # Build mapping id->index
    id_to_index = {ids[i]: i for i in range(len(ids))}

    for qid in QDEVICE_IDS:
        if qid not in id_to_index:
            print(f"{qid}: NOT FOUND in index")
            continue
        i = id_to_index[qid]
        emb = embeddings_list[i]
        score = cos_sim(q_emb, emb)
        src = metadatas[i].get("source") if metadatas and metadatas[i] else None
        snippet = docs[i][:400].replace("\n", " ")
        print(f"\nID: {qid}")
        print(f"source: {src}")
        print(f"cosine similarity to query: {score:.6f}")
        print("snippet:", snippet)
except Exception:
    print("ERROR:")
    traceback.print_exc()

