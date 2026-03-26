import argparse
import asyncio

from ingest import ingest_folder


def _estimate_cost_usd(total_chunks: int) -> float:
    """Estimate ingestion API cost from chunk count using architecture baseline."""
    # From architecture baseline: 500 chunks costs about $0.004 (embeddings)
    # plus about $0.05-$0.10 (extraction). Use midpoint $0.075.
    per_chunk_cost = (0.004 + 0.075) / 500
    return total_chunks * per_chunk_cost


async def _run(folder_path: str) -> None:
    """Run ingest on a folder and print per-file plus total summary."""
    results = await ingest_folder(folder_path)

    total_files = len(results)
    done_files = 0
    total_chunks = 0
    total_fields = 0

    for result in results:
        filename = str(result.get("filename", "unknown"))
        status = str(result.get("status", "unknown"))
        chunk_count = int(result.get("chunk_count", 0) or 0)
        field_count = int(result.get("field_count", 0) or 0)

        if status == "done":
            done_files += 1
        total_chunks += chunk_count
        total_fields += field_count

        print(
            "filename=%s status=%s chunk_count=%d field_count=%d"
            % (filename, status, chunk_count, field_count)
        )

    estimate = _estimate_cost_usd(total_chunks)
    print("---")
    print("files_ingested=%d/%d" % (done_files, total_files))
    print("total_chunks=%d" % total_chunks)
    print("total_fields=%d" % total_fields)
    print("total_cost_estimate_usd=$%.4f" % estimate)


def main() -> None:
    """Parse CLI args and run folder seeding."""
    parser = argparse.ArgumentParser(description="Seed demo data into Vantage by ingesting a folder.")
    parser.add_argument("folder_path", help="Path to folder containing files to ingest")
    args = parser.parse_args()

    asyncio.run(_run(args.folder_path))


if __name__ == "__main__":
    main()
