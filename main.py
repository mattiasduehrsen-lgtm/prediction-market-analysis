from __future__ import annotations

import io
import os
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

# pandas Cython code raises SIGINT (not a Python exception) on Timedelta overflow.
# Install a handler that converts OS-level SIGINT into a Python KeyboardInterrupt
# so it can be caught by except BaseException inside the loop.
def _sigint_handler(signum, frame):
    raise KeyboardInterrupt("SIGINT from pandas overflow — will retry next cycle")

signal.signal(signal.SIGINT, _sigint_handler)

load_dotenv()

# Force UTF-8 stdout/stderr so market names with non-ASCII characters
# (Turkish, accented, etc.) never crash the process on Windows.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def _configure_matplotlib_cache() -> None:
    project_root = Path(__file__).resolve().parent
    mpl_config_dir = project_root / ".cache" / "matplotlib"
    mpl_config_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(mpl_config_dir))


def analyze(name: str | None = None):
    """Run analysis by name or show interactive menu."""
    _configure_matplotlib_cache()

    from simple_term_menu import TerminalMenu

    from src.common.analysis import Analysis
    from src.common.util.strings import snake_to_title

    analyses = Analysis.load()

    if not analyses:
        print("No analyses found in src/analysis/")
        return

    output_dir = Path("output")

    # If name provided, run that specific analysis
    if name:
        if name == "all":
            print("\nRunning all analyses...\n")
            for analysis_cls in analyses:
                instance = analysis_cls()
                print(f"Running: {instance.name}")
                saved = instance.save(output_dir, formats=["png", "pdf", "csv", "json", "gif"])
                for fmt, path in saved.items():
                    print(f"  {fmt}: {path}")
            print("\nAll analyses complete.")
            return

        # Find matching analysis
        for analysis_cls in analyses:
            instance = analysis_cls()
            if instance.name == name:
                print(f"\nRunning: {instance.name}\n")
                saved = instance.save(output_dir, formats=["png", "pdf", "csv", "json", "gif"])
                print("Saved files:")
                for fmt, path in saved.items():
                    print(f"  {fmt}: {path}")
                return

        # No match found
        print(f"Analysis '{name}' not found. Available analyses:")
        for analysis_cls in analyses:
            instance = analysis_cls()
            print(f"  - {instance.name}")
        sys.exit(1)

    # Interactive menu mode
    options = ["[All] Run all analyses"]
    for analysis_cls in analyses:
        instance = analysis_cls()
        options.append(f"{snake_to_title(instance.name)}: {instance.description}")
    options.append("[Exit]")

    menu = TerminalMenu(
        options,
        title="Select an analysis to run (use arrow keys):",
        cycle_cursor=True,
        clear_screen=False,
    )
    choice = menu.show()

    if choice is None or choice == len(options) - 1:
        print("Exiting.")
        return

    if choice == 0:
        # Run all analyses
        print("\nRunning all analyses...\n")
        for analysis_cls in analyses:
            instance = analysis_cls()
            print(f"Running: {instance.name}")
            saved = instance.save(output_dir, formats=["png", "pdf", "csv", "json", "gif"])
            for fmt, path in saved.items():
                print(f"  {fmt}: {path}")
        print("\nAll analyses complete.")
    else:
        # Run selected analysis
        analysis_cls = analyses[choice - 1]
        instance = analysis_cls()
        print(f"\nRunning: {instance.name}\n")
        saved = instance.save(output_dir, formats=["png", "pdf", "csv", "json", "gif"])
        print("Saved files:")
        for fmt, path in saved.items():
            print(f"  {fmt}: {path}")


def index():
    """Interactive indexer selection menu."""
    from simple_term_menu import TerminalMenu

    from src.common.indexer import Indexer
    from src.common.util.strings import snake_to_title

    indexers = Indexer.load()

    if not indexers:
        print("No indexers found in src/indexers/")
        return

    # Build menu options
    options = []
    for indexer_cls in indexers:
        instance = indexer_cls()
        options.append(f"{snake_to_title(instance.name)}: {instance.description}")
    options.append("[Exit]")

    menu = TerminalMenu(
        options,
        title="Select an indexer to run (use arrow keys):",
        cycle_cursor=True,
        clear_screen=False,
    )
    choice = menu.show()

    if choice is None or choice == len(options) - 1:
        print("Exiting.")
        return

    indexer_cls = indexers[choice]
    instance = indexer_cls()
    print(f"\nRunning: {instance.name}\n")
    instance.run()
    print("\nIndexer complete.")


def package():
    """Package the data directory into a zstd-compressed tar archive."""
    from src.common.util import package_data

    success = package_data()
    sys.exit(0 if success else 1)


def current():
    """Collect a lightweight snapshot of current market data."""
    _configure_matplotlib_cache()

    from src.current.collector import collect_current_data

    collect_current_data()
    sys.exit(0)


def paper():
    """Run the Polymarket paper-trading bot once."""
    _configure_matplotlib_cache()

    from src.bot.polymarket import PaperTradingBot

    saved = PaperTradingBot().run_once()
    print("Paper-trading run complete.")
    for name, path in saved.items():
        print(f"  {name}: {path}")
    sys.exit(0)


def paper_loop():
    """Run the Polymarket paper-trading bot on a timer, refreshing data each cycle."""
    import time as _time

    _configure_matplotlib_cache()

    from src.bot.polymarket import PaperTradingBot
    from src.current.collector import collect_current_data

    iterations = int(sys.argv[2]) if len(sys.argv) > 2 else 0  # 0 = run forever
    sleep_seconds = int(sys.argv[3]) if len(sys.argv) > 3 else int(os.environ.get("PAPER_LOOP_SLEEP_SECONDS", 900))
    max_iterations = iterations or None

    bot = PaperTradingBot()
    bot.price_monitor.start()
    print("[PRICE MONITOR] Started WebSocket price monitor")

    run_count = 0
    last_saved: dict = {}

    try:
        while True:
            run_count += 1
            print(f"\n=== Paper loop iteration {run_count} ===")
            try:
                collect_current_data()
                last_saved = bot.run_once()
                # Subscribe any newly opened positions to the price monitor.
                bot.subscribe_open_positions()
                print("Paper-trading run complete.")
                for name, path in last_saved.items():
                    print(f"  {name}: {path}")
            except BaseException as exc:
                import traceback
                print(f"[LOOP ERROR] cycle {run_count} failed, retrying next cycle: {exc}")
                traceback.print_exc()

            if max_iterations is not None and run_count >= max_iterations:
                break

            # Between full cycles: check prices every 1s using the live WS cache.
            elapsed = 0
            while elapsed < sleep_seconds:
                try:
                    _time.sleep(1)
                except BaseException:
                    pass
                elapsed += 1
                try:
                    bot.fast_exit_check()
                except Exception as exc:
                    print(f"[FAST EXIT CHECK] error (non-fatal): {exc}")
    finally:
        bot.price_monitor.stop()

    print("Paper-trading loop complete.")
    sys.exit(0)


def dashboard():
    """Launch the web dashboard at http://localhost:5000"""
    from src.dashboard.app import run
    print("Dashboard running at http://localhost:5000")
    print("Open that address in your browser. Press Ctrl+C to stop.")
    run()


def live():
    """Run the live-trading bot once (requires LIVE_TRADING=true in .env)."""
    _configure_matplotlib_cache()

    from src.bot.live_executor import build_live_executor_if_enabled
    from src.bot.polymarket import PaperTradingBot

    executor = build_live_executor_if_enabled()
    if executor is None:
        print("LIVE_TRADING is not enabled. Set LIVE_TRADING=true in your .env file.")
        print("Running in paper mode instead.")
    saved = PaperTradingBot(live_executor=executor).run_once()
    mode = "Live-trading" if executor else "Paper-trading"
    print(f"{mode} run complete.")
    for name, path in saved.items():
        print(f"  {name}: {path}")
    sys.exit(0)


def live_loop():
    """Run the live-trading bot on a timer (requires LIVE_TRADING=true in .env)."""
    _configure_matplotlib_cache()

    from src.bot.live_executor import build_live_executor_if_enabled
    from src.bot.polymarket import PaperTradingBot

    iterations = int(sys.argv[2]) if len(sys.argv) > 2 else None
    sleep_seconds = int(sys.argv[3]) if len(sys.argv) > 3 else 60

    executor = build_live_executor_if_enabled()
    if executor is None:
        print("LIVE_TRADING is not enabled. Set LIVE_TRADING=true in your .env file.")
        print("Running in paper mode instead.")
    saved = PaperTradingBot(live_executor=executor).run_loop(
        iterations=iterations, sleep_seconds=sleep_seconds
    )
    mode = "Live-trading" if executor else "Paper-trading"
    print(f"{mode} loop complete.")
    for name, path in saved.items():
        print(f"  {name}: {path}")
    sys.exit(0)


def main():
    if len(sys.argv) < 2:
        print("\nUsage: uv run main.py <command>")
        print("Commands: analyze, index, current, package, paper, paper-loop, live, live-loop")
        sys.exit(0)

    command = sys.argv[1]

    if command == "analyze":
        name = sys.argv[2] if len(sys.argv) > 2 else None
        analyze(name)
        sys.exit(0)

    if command == "index":
        index()
        sys.exit(0)

    if command == "package":
        package()
        sys.exit(0)

    if command == "current":
        current()
        sys.exit(0)

    if command == "paper":
        paper()
        sys.exit(0)

    if command == "paper-loop":
        paper_loop()
        sys.exit(0)

    if command == "dashboard":
        dashboard()
        sys.exit(0)

    if command == "live":
        live()
        sys.exit(0)

    if command == "live-loop":
        live_loop()
        sys.exit(0)

    print(f"Unknown command: {command}")
    print("Commands: analyze, index, current, package, paper, paper-loop, live, live-loop")
    sys.exit(1)


if __name__ == "__main__":
    main()
