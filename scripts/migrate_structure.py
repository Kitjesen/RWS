#!/usr/bin/env python3
"""
RWS Project Structure Migration Script
=======================================

Automatically reorganizes the project structure according to the refactor plan.

Usage:
    python scripts/tools/migrate_structure.py --dry-run  # Preview changes
    python scripts/tools/migrate_structure.py            # Execute migration
"""

import argparse
import shutil
from pathlib import Path
from typing import Dict, List, Tuple

# Base directory (scripts/migrate_structure.py -> scripts -> RWS)
BASE_DIR = Path(__file__).parent.parent

# Migration mappings: old_path -> new_path
DOCS_MIGRATIONS: Dict[str, str] = {
    # Getting Started
    "docs/QUICK_START.md": "docs/getting-started/quick-start.md",
    "docs/CONFIGURATION.md": "docs/getting-started/configuration.md",

    # Guides
    "docs/HARDWARE_GUIDE.md": "docs/guides/hardware-setup.md",
    "docs/COORDINATE_MATH.md": "docs/guides/coordinate-math.md",
    "docs/TESTING_GUIDE.md": "docs/guides/testing.md",
    "docs/OCCLUSION_HANDLING.md": "docs/guides/occlusion-handling.md",
    "docs/WHY_CROSSHAIR_FIXED.md": "docs/guides/crosshair-design.md",

    # API Documentation
    "docs/API_GUIDE.md": "docs/api/rest-api.md",
    "docs/GRPC_GUIDE.md": "docs/api/grpc-api.md",
    "docs/API_QUICK_REFERENCE.md": "docs/api/quick-reference.md",

    # Architecture
    "docs/ARCHITECTURE.md": "docs/architecture/overview.md",
    "docs/QUICK_REFERENCE.md": "docs/architecture/quick-reference.md",

    # Development
    "docs/CI_FINAL_STATUS.md": "docs/development/ci-status.md",
    "docs/CI_FIX_SUMMARY.md": "docs/development/ci-fixes.md",
    "docs/MIGRATION_GUIDE.md": "docs/development/migration-guide.md",

    # Reports
    "docs/API_REFACTOR_SUMMARY.md": "docs/reports/2024-02-16-api-refactor.md",
    "docs/API_IMPLEMENTATION_COMPLETE.md": "docs/reports/2024-02-17-api-complete.md",
    "docs/API_TEST_REPORT.md": "docs/reports/2024-02-17-api-test.md",
    "docs/TEAM_ANALYSIS_REPORT.md": "docs/reports/2024-02-15-team-analysis.md",
    "docs/TEST_COVERAGE_REPORT.md": "docs/reports/2024-02-15-test-coverage.md",
    "docs/ENHANCEMENT_PLAN.md": "docs/reports/2024-02-15-enhancement-plan.md",
    "docs/PROJECT_REORGANIZATION.md": "docs/reports/2024-02-16-reorganization.md",
    "docs/FINAL_SUMMARY.md": "docs/reports/2024-02-16-final-summary.md",
    "docs/CLEANUP_SUMMARY.md": "docs/reports/2024-02-16-cleanup.md",
    "docs/QUICK_START_NEW_FEATURES.md": "docs/reports/2024-02-15-new-features.md",
    "docs/RFlow.md": "docs/reports/2024-02-15-rflow.md",

    # Root to docs/reports
    "FINAL_API_SUMMARY.md": "docs/reports/2024-02-17-api-summary.md",
    "WORK_SUMMARY_2026-02-17.md": "docs/reports/2024-02-17-work-summary.md",
}

SCRIPTS_MIGRATIONS: Dict[str, str] = {
    # API scripts
    "scripts/run_api_server.py": "scripts/api/run_rest_server.py",
    "scripts/run_grpc_server.py": "scripts/api/run_grpc_server.py",
    "scripts/api_client_example.py": "scripts/api/rest_client_example.py",
    "scripts/grpc_client_example.py": "scripts/api/grpc_client_example.py",

    # Demo scripts
    "scripts/run_demo.py": "scripts/demo/run_simple_demo.py",
    "scripts/run_yolo_cam.py": "scripts/demo/run_camera_demo.py",

    # Tools
    "scripts/generate_proto.bat": "scripts/tools/generate_proto.bat",
    "scripts/generate_proto.sh": "scripts/tools/generate_proto.sh",

    # Tests
    "scripts/test_api.py": "scripts/tests/test_api.py",
    "scripts/run_tests.bat": "scripts/tests/run_tests.bat",
    "scripts/run_tests.sh": "scripts/tests/run_tests.sh",
}

FILES_TO_DELETE: List[str] = [
    "docs/DIRECTORY_STRUCTURE.md",
    "docs/PROJECT_STRUCTURE.txt",
    "docs/README_STRUCTURE.md",
]

NEW_DIRECTORIES: List[str] = [
    "docs/getting-started",
    "docs/guides",
    "docs/api/examples",
    "docs/architecture",
    "docs/development",
    "scripts/api",
    "scripts/demo",
    "scripts/tools",
    "scripts/tests",
]


def create_directories(dry_run: bool = False) -> None:
    """Create new directory structure."""
    print("\n[+] Creating new directories...")
    for dir_path in NEW_DIRECTORIES:
        full_path = BASE_DIR / dir_path
        if not full_path.exists():
            if dry_run:
                print(f"  [DRY RUN] Would create: {dir_path}")
            else:
                full_path.mkdir(parents=True, exist_ok=True)
                print(f"  [OK] Created: {dir_path}")
        else:
            print(f"  [EXISTS] Already exists: {dir_path}")


def migrate_files(migrations: Dict[str, str], dry_run: bool = False) -> Tuple[int, int]:
    """Migrate files according to mapping."""
    success_count = 0
    skip_count = 0

    for old_path, new_path in migrations.items():
        old_full = BASE_DIR / old_path
        new_full = BASE_DIR / new_path

        if not old_full.exists():
            print(f"  [SKIP] Not found: {old_path}")
            skip_count += 1
            continue

        if new_full.exists():
            print(f"  [SKIP] Already exists: {new_path}")
            skip_count += 1
            continue

        if dry_run:
            print(f"  [DRY RUN] Would move: {old_path} -> {new_path}")
        else:
            new_full.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_full), str(new_full))
            print(f"  [OK] Moved: {old_path} -> {new_path}")

        success_count += 1

    return success_count, skip_count


def delete_files(files: List[str], dry_run: bool = False) -> int:
    """Delete obsolete files."""
    delete_count = 0

    for file_path in files:
        full_path = BASE_DIR / file_path

        if not full_path.exists():
            print(f"  [SKIP] Not found: {file_path}")
            continue

        if dry_run:
            print(f"  [DRY RUN] Would delete: {file_path}")
        else:
            full_path.unlink()
            print(f"  [OK] Deleted: {file_path}")

        delete_count += 1

    return delete_count


def create_index_files(dry_run: bool = False) -> None:
    """Create documentation index files."""
    print("\n[+] Creating index files...")

    # docs/README.md
    docs_readme = BASE_DIR / "docs" / "README.md"
    if not docs_readme.exists():
        content = """# RWS Tracking System Documentation

## 🚀 Getting Started
- [Quick Start](getting-started/quick-start.md) - Get up and running in 5 minutes
- [Installation](getting-started/installation.md) - Detailed installation guide
- [Configuration](getting-started/configuration.md) - System configuration

## 📖 User Guides
- [Hardware Setup](guides/hardware-setup.md) - Hardware integration guide
- [Coordinate Math](guides/coordinate-math.md) - Understanding coordinate transforms
- [Testing Guide](guides/testing.md) - Running and writing tests
- [Occlusion Handling](guides/occlusion-handling.md) - Target occlusion strategies
- [Crosshair Design](guides/crosshair-design.md) - Why crosshair is fixed

## 🔌 API Documentation
- [REST API](api/rest-api.md) - Complete REST API reference
- [gRPC API](api/grpc-api.md) - Complete gRPC API reference
- [Quick Reference](api/quick-reference.md) - API quick reference card
- [Examples](api/examples/) - Code examples

## 🏗️ Architecture
- [System Overview](architecture/overview.md) - High-level architecture
- [Quick Reference](architecture/quick-reference.md) - Architecture quick reference

## 🛠️ Development
- [Contributing](development/contributing.md) - How to contribute
- [Testing](development/testing.md) - Testing guidelines
- [CI/CD](development/ci-status.md) - Continuous integration setup
- [Migration Guide](development/migration-guide.md) - Version migration guide

## 📊 Project Reports
See [reports/](reports/) for project completion reports and summaries.
"""
        if dry_run:
            print(f"  [DRY RUN] Would create: docs/README.md")
        else:
            docs_readme.write_text(content, encoding="utf-8")
            print(f"  [OK] Created: docs/README.md")

    # docs/api/README.md
    api_readme = BASE_DIR / "docs" / "api" / "README.md"
    if not api_readme.exists():
        content = """# API Documentation

RWS Tracking System provides both REST and gRPC APIs for remote control.

## Quick Links

- **[REST API](rest-api.md)** - HTTP/JSON API (port 5000)
- **[gRPC API](grpc-api.md)** - High-performance binary API (port 50051)
- **[Quick Reference](quick-reference.md)** - API endpoints at a glance

## Choosing an API

- Use **REST API** for web frontends, simple integration, debugging
- Use **gRPC API** for high performance, streaming, embedded systems

## Getting Started

### REST API
```bash
python scripts/api/run_rest_server.py
```

### gRPC API
```bash
python scripts/api/run_grpc_server.py
```

See the full guides for detailed usage and examples.
"""
        if dry_run:
            print(f"  [DRY RUN] Would create: docs/api/README.md")
        else:
            api_readme.write_text(content, encoding="utf-8")
            print(f"  [OK] Created: docs/api/README.md")


def main():
    parser = argparse.ArgumentParser(description="Migrate RWS project structure")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without executing",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("RWS Project Structure Migration")
    print("=" * 70)

    if args.dry_run:
        print("\n[!] DRY RUN MODE - No changes will be made\n")

    # Step 1: Create directories
    create_directories(args.dry_run)

    # Step 2: Migrate docs
    print("\n[*] Migrating documentation files...")
    docs_success, docs_skip = migrate_files(DOCS_MIGRATIONS, args.dry_run)

    # Step 3: Migrate scripts
    print("\n[*] Migrating script files...")
    scripts_success, scripts_skip = migrate_files(SCRIPTS_MIGRATIONS, args.dry_run)

    # Step 4: Delete obsolete files
    print("\n[-] Deleting obsolete files...")
    deleted = delete_files(FILES_TO_DELETE, args.dry_run)

    # Step 5: Create index files
    create_index_files(args.dry_run)

    # Summary
    print("\n" + "=" * 70)
    print("Migration Summary")
    print("=" * 70)
    print(f"  Docs migrated:     {docs_success}")
    print(f"  Scripts migrated:  {scripts_success}")
    print(f"  Files deleted:     {deleted}")
    print(f"  Files skipped:     {docs_skip + scripts_skip}")
    print("=" * 70)

    if args.dry_run:
        print("\n[OK] Dry run completed. Run without --dry-run to execute migration.")
    else:
        print("\n[OK] Migration completed successfully!")
        print("\nNext steps:")
        print("  1. Update README.md with new structure")
        print("  2. Update script paths in documentation")
        print("  3. Test all scripts and APIs")
        print("  4. Commit changes with: git add -A && git commit -m 'refactor: reorganize project structure'")


if __name__ == "__main__":
    main()
