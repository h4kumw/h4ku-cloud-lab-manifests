"""RAG-поиск по игровым логам через pgvector + Ollama."""
import os
import sys
import requests
import psycopg2

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", "5432"))
PG_USER = os.getenv("PG_USER", "admin")
PG_PASSWORD = os.getenv("PG_PASSWORD", "postgres")
PG_DB = os.getenv("PG_DB", "farcana")


def get_embedding(text):
    """Embedding для запроса."""
    resp = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": "nomic-embed-text", "prompt": text},
        timeout=30
    )
    resp.raise_for_status()
    return resp.json()["embedding"]


def generate_answer(query, context_docs):
    """LLM генерирует ответ на основе найденных документов (RAG)."""
    context = "\n".join(f"- {doc}" for doc in context_docs)
    prompt = f"""Based on the following game logs, answer the question.

Context:
{context}

Question: {query}

Answer in 2-3 sentences:"""
    
    resp = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": "llama3.2:3b",
            "prompt": prompt,
            "stream": False
        },
        timeout=60
    )
    resp.raise_for_status()
    return resp.json()["response"]


def rag_search(query, limit=5):
    """Векторный поиск по embeddings."""
    query_emb = get_embedding(query)
    vector_str = "[" + ",".join(str(x) for x in query_emb) + "]"
    
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER,
        password=PG_PASSWORD, database=PG_DB
    )
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            log_source,
            log_text,
            1 - (embedding <=> %s::vector) AS similarity
        FROM game_log_embeddings
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """, (vector_str, vector_str, limit))
    
    results = cur.fetchall()
    conn.close()
    return results


def main():
    # Получаем запрос из аргументов или используем дефолтный
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = "Find matches where players complained about lag"
    
    print(f"\n🔍 Query: {query}\n")
    print("=" * 80)
    
    results = rag_search(query, limit=5)
    
    print("\n📚 Top-5 similar logs:")
    print("-" * 80)
    for source, text, sim in results:
        print(f"[{sim:.3f}] [{source:8s}] {text}")
    
    print("\n" + "=" * 80)
    print("\n🤖 LLM Answer:")
    print("-" * 80)
    
    context_docs = [text for _, text, _ in results]
    answer = generate_answer(query, context_docs)
    print(answer)
    
    print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    main()
