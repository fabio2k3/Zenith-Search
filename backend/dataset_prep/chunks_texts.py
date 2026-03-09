import os
from pathlib import Path

INPUT_DIR = "extracted_text"
OUTPUT_DIR = "chunks"

CHUNK_SIZE = 800
OVERLAP = 100


def chunk_text(text, chunk_size=800, overlap=100):
    words = text.split()
    chunks = []

    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = words[start:end]
        chunks.append(" ".join(chunk))
        start += chunk_size - overlap

    return chunks


def process_files():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for file in os.listdir(INPUT_DIR):

        if not file.endswith(".txt"):
            continue

        path = os.path.join(INPUT_DIR, file)

        with open(path, "r", encoding="utf-8") as f:
            text = f.read()

        chunks = chunk_text(text)

        base_name = Path(file).stem

        for i, chunk in enumerate(chunks):

            out_file = os.path.join(
                OUTPUT_DIR,
                f"{base_name}_chunk_{i}.txt"
            )

            with open(out_file, "w", encoding="utf-8") as f:
                f.write(chunk)


if __name__ == "__main__":
    process_files()