# check_qdevice_reembed.py
from app.vector_store import vector_store
import numpy as np

QDEVICE_IDS = [
    "qdevice_quorum_proxmox.md::qdevice_quorum_proxmox.md::138",
    "qdevice_quorum_proxmox.md::qdevice_quorum_proxmox.md::139",
    "qdevice_quorum_proxmox.md::qdevice_quorum_proxmox.md::140",
]

def cos_sim(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if np.linalg.norm(a) == 0 or np.linalg.norm(b) == 0:
        return float("-inf")
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

vs = vector_store
vs.initialize()
coll = vs._vectorstore._collection

results = coll.get(limit=None, include=["documents", "metadatas", "embeddings"])
ids = results.get("ids", [])
docs = results.get("documents", [])

# Re-embed the qdevice chunk texts directly with the embeddings provider
for qid in QDEVICE_IDS:
    try:
        idx = ids.index(qid)
    except ValueError:
        print(f"{qid} not found")
        continue
    text = docs[idx]
    doc_emb = vs.embeddings.embed_documents([text])[0]
    q_emb = vs.embed_query("how do I set up qdevice")
    print("\n---")
    print(f"ID: {qid}")
    print("Re-embedded doc vector length:", len(doc_emb))
    print("Query vector length:", len(q_emb))
    print("Cosine similarity (query vs re-embedded doc):", cos_sim(q_emb, doc_emb))
    print("Snippet:", text[:300].replace('\n', ' '))
