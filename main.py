"""
CTR Optimization Tool — Main Orchestrator

Usage:
  python3 main.py                    Full run (all 6 steps)
  python3 main.py --dry-run          Preview mode: shows client/page counts, no AI calls, no output written
  python3 main.py --from-step 3      Resume from step 3 (loads checkpoint)
  python3 main.py --skip-serp        Skip DataForSEO SERP fetching (faster, fewer competitor insights)
"""

import argparse
import json
import os
import sys

import config


CHECKPOINT_FILE = os.path.join(config.BASE_DIR, ".checkpoint.json")


def _save_checkpoint(step: int, data: dict):
    payload = {"completed_step": step, "data": data}
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def _load_checkpoint() -> tuple:
    """Returns (completed_step, data) or (0, {})."""
    if not os.path.exists(CHECKPOINT_FILE):
        return 0, {}
    try:
        with open(CHECKPOINT_FILE, encoding="utf-8") as f:
            payload = json.load(f)
        return payload.get("completed_step", 0), payload.get("data", {})
    except Exception:
        return 0, {}


def main():
    parser = argparse.ArgumentParser(description="CTR Optimization Tool — Title & Meta Rewrite Engine")
    parser.add_argument("--dry-run",    action="store_true", help="Preview mode: no AI calls, no output written")
    parser.add_argument("--from-step",  type=int, default=None, metavar="N", help="Resume from step N using checkpoint")
    parser.add_argument("--skip-serp",  action="store_true", help="Skip DataForSEO SERP fetching")
    args = parser.parse_args()

    # ── Validate environment ──────────────────────────────────────────────────
    try:
        config.validate()
    except EnvironmentError as e:
        print(f"❌ {e}")
        sys.exit(1)

    print("\n" + "═" * 58)
    print("  CTR Optimization Tool — Title & Meta Rewrite Engine")
    print("═" * 58)
    if args.dry_run:
        print("  ⚡ DRY RUN — no AI calls, no files written\n")

    from models import pages_from_json, pages_to_json

    # Determine resume point
    start_step = 1
    checkpoint_data = {}
    if args.from_step:
        completed, checkpoint_data = _load_checkpoint()
        if completed < args.from_step - 1:
            print(f"❌ Checkpoint only covers steps up to {completed}. Cannot resume from step {args.from_step}.")
            sys.exit(1)
        start_step = args.from_step
        print(f"  Resuming from step {start_step} (checkpoint: step {completed} completed)\n")

    # ── Step 1: Active clients ────────────────────────────────────────────────
    clients = []
    if start_step <= 1:
        import step1_clients
        clients = step1_clients.run()
        if not clients:
            print("❌ No active clients found. Exiting.")
            sys.exit(1)
        if not args.dry_run:
            _save_checkpoint(1, {"clients": [
                {"project_name": c.project_name, "client_name": c.client_name,
                 "domain": c.domain, "strategist": c.strategist, "is_red_flag": c.is_red_flag}
                for c in clients
            ]})
    else:
        from models import ClientRecord
        clients = [ClientRecord(**c) for c in checkpoint_data.get("clients", [])]
        print(f"  (Loaded {len(clients)} clients from checkpoint)")

    # ── Step 2: GSC page data ─────────────────────────────────────────────────
    candidate_pages = []
    if start_step <= 2:
        import step2_gsc
        candidate_pages = step2_gsc.run(clients)
        if not candidate_pages:
            print("❌ No candidate pages found in GSC. Check position/impression filters.")
            sys.exit(1)
        if not args.dry_run:
            _save_checkpoint(2, {"clients": checkpoint_data.get("clients", [
                {"project_name": c.project_name, "client_name": c.client_name,
                 "domain": c.domain, "strategist": c.strategist, "is_red_flag": c.is_red_flag}
                for c in clients
            ]), "pages": pages_to_json(candidate_pages)})
    else:
        candidate_pages = pages_from_json(checkpoint_data.get("pages", "[]"))
        print(f"  (Loaded {len(candidate_pages)} candidate pages from checkpoint)")

    # ── Step 3: Classify and flag ─────────────────────────────────────────────
    flagged_pages = []
    if start_step <= 3:
        import step3_classify
        flagged_pages = step3_classify.run(candidate_pages)
        if not flagged_pages:
            print("⚠️  No pages flagged as underperforming. Consider adjusting GSC_MIN_POSITION,")
            print("   GSC_MAX_POSITION, or CTR_THRESHOLD_RATIO in config.py.")
            sys.exit(0)
        if not args.dry_run:
            _save_checkpoint(3, {"clients": checkpoint_data.get("clients", []), "flagged": pages_to_json(flagged_pages)})
    else:
        flagged_pages = pages_from_json(checkpoint_data.get("flagged", "[]"))
        print(f"  (Loaded {len(flagged_pages)} flagged pages from checkpoint)")

    # ── Dry run stops here ────────────────────────────────────────────────────
    if args.dry_run:
        print("\n" + "═" * 58)
        print("  DRY RUN SUMMARY")
        print("═" * 58)
        print(f"  Active clients:    {len(clients)}")
        print(f"  Candidate pages:   {len(candidate_pages)}")
        print(f"  Flagged pages:     {len(flagged_pages)}")
        by_strat = {}
        for p in flagged_pages:
            by_strat.setdefault(p.strategist, 0)
            by_strat[p.strategist] += 1
        print("\n  Flagged pages per strategist:")
        for strat, count in sorted(by_strat.items()):
            print(f"    {strat}: {count}")
        print("\n  (No AI calls made, no files written.)")
        return

    # ── Step 4: Fetch live content + SERP ────────────────────────────────────
    if start_step <= 4:
        import step4_fetch_meta
        if args.skip_serp:
            print("\n  --skip-serp: DataForSEO SERP fetch will be skipped.")
            # Temporarily override SERP result count to 0 to skip SERP in step4
            original_count = config.SERP_RESULT_COUNT
            config.SERP_RESULT_COUNT = 0
        flagged_pages = step4_fetch_meta.run(flagged_pages)
        if args.skip_serp:
            config.SERP_RESULT_COUNT = original_count
        _save_checkpoint(4, {"flagged": pages_to_json(flagged_pages)})
    else:
        flagged_pages = pages_from_json(checkpoint_data.get("flagged", "[]"))
        print(f"  (Loaded {len(flagged_pages)} pages with content/SERP from checkpoint)")

    # ── Step 5: AI rewrites ───────────────────────────────────────────────────
    if start_step <= 5:
        import step5_rewrite
        flagged_pages = step5_rewrite.run(flagged_pages)
        _save_checkpoint(5, {"flagged": pages_to_json(flagged_pages)})
    else:
        flagged_pages = pages_from_json(checkpoint_data.get("flagged", "[]"))
        print(f"  (Loaded {len(flagged_pages)} pages with rewrites from checkpoint)")

    # ── Step 6: Write outputs ─────────────────────────────────────────────────
    import step6_output
    sheet_url = step6_output.run(flagged_pages)

    # Clean up checkpoint on successful completion
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)

    print("═" * 58)
    print("  ✅ Run complete!")
    print(f"  Sheet: {sheet_url}")
    print("═" * 58 + "\n")


if __name__ == "__main__":
    main()
