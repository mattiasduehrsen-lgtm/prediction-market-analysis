from __future__ import annotations

import os
import sys
from pathlib import Path


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
    """Run the Polymarket paper-trading bot on a timer."""
    _configure_matplotlib_cache()

    from src.bot.polymarket import PaperTradingBot

    iterations = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    sleep_seconds = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    saved = PaperTradingBot().run_loop(iterations=iterations, sleep_seconds=sleep_seconds)
    print("Paper-trading loop complete.")
    for name, path in saved.items():
        print(f"  {name}: {path}")
    sys.exit(0)


def main():
    if len(sys.argv) < 2:
        print("\nUsage: uv run main.py <command>")
        print("Commands: analyze, index, current, package, paper, paper-loop")
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

    print(f"Unknown command: {command}")
    print("Commands: analyze, index, current, package, paper, paper-loop")
    sys.exit(1)


if __name__ == "__main__":
    main()
