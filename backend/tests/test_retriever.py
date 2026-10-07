from services.retriever import FileChunkRetriever, build_retriever


def test_file_chunk_retriever_ranks_matching_files() -> None:
    retriever = FileChunkRetriever(chunk_size=200)
    retriever.index_files({"app.py": "def login():\n    password = 'secret'\n", "readme.md": "hello"})
    hits = retriever.retrieve("password login", top_k=2)
    assert hits
    assert hits[0]["path"] == "app.py"


def test_build_retriever_files_backend() -> None:
    assert type(build_retriever("files")).__name__ == "FileChunkRetriever"
    assert type(build_retriever("none")).__name__ == "NoOpRetriever"
