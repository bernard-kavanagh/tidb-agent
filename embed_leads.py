"""
Generate embeddings for all leads that don't have one yet.

Run: python3 embed_leads.py

Uses all-MiniLM-L6-v2 (384 dims) locally via sentence-transformers.
Stores vectors in TiDB with VEC_COSINE_DISTANCE-compatible format.

Prerequisites:
  pip install sentence-transformers
  ALTER TABLE leads ADD COLUMN embedding VECTOR(384);
  CREATE VECTOR INDEX vidx_leads_embedding ON leads ((VEC_COSINE_DISTANCE(embedding)));
"""
import os
import sys

# Load .env
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))

from agent.storage import get_conn
from agent.embeddings import backfill_embeddings
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


def main():
    console.rule("[bold blue]TiDB Cloud — Lead Embedding Backfill[/bold blue]")

    conn = get_conn()
    try:
        # Count leads needing embeddings
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM leads WHERE embedding IS NULL")
            pending = cur.fetchone()["n"]

        if pending == 0:
            console.print("[green]All leads already have embeddings.[/green]")
            return

        console.print(f"Embedding [bold]{pending}[/bold] leads (model: all-MiniLM-L6-v2)...")
        console.print("[dim]First run downloads the model (~90MB) — subsequent runs are instant.[/dim]\n")

        with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as p:
            task = p.add_task(f"Processing {pending} leads...", total=None)
            updated, skipped = backfill_embeddings(conn)
            p.update(task, description=f"[green]Done — {updated} embedded, {skipped} skipped (no text)[/green]")

        console.print(f"\n[bold green]✅  {updated} leads now searchable via vector similarity.[/bold green]")
        console.print("[dim]Run the dashboard and use the search bar to try semantic search.[/dim]")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
