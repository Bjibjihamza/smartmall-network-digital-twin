"""Repository-structure regression tests (no Mininet, no root).

Guards the cleanup: official entry points exist and start, the v2 pipeline does
not depend on legacy scripts, the library imports without Mininet, every script
compiles, and documentation does not reference missing scripts.
"""
import importlib
import py_compile
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Official, Mininet-free entry points (must answer --help in any environment).
OFFLINE_OFFICIAL = ["run_small_scenario", "run_small_scenario_campaign", "audit_small_scenario",
                    "analyze_small_scenarios", "build_small_dataset", "verify_small_iperf_receiver",
                    "catalog_small_data"]
MININET_OFFICIAL = ["run_small_mininet"]
TOPOLOGY_TOOLS = ["validate_topology", "visualize_topology"]   # need networkx/matplotlib
LEGACY_MODULES = {"collect_small_with_ports", "collect_small_experiment", "run_small_link_campaign",
                  "audit_port_experiment", "audit_experiment", "analyze_small_campaign",
                  "analyze_small_repeatability", "pilot_small_background_traffic",
                  "audit_small_load_pilot", "diagnose_small_iperf_receiver", "demo_link_failure"}


class RepositoryTests(unittest.TestCase):
    def test_official_scripts_present(self):
        for name in OFFLINE_OFFICIAL + MININET_OFFICIAL + TOPOLOGY_TOOLS:
            self.assertTrue((ROOT / "scripts" / f"{name}.py").is_file(), name)

    def test_offline_official_help(self):
        for name in OFFLINE_OFFICIAL:
            proc = subprocess.run([sys.executable, str(ROOT / "scripts" / f"{name}.py"), "--help"],
                                  capture_output=True, text=True, cwd=ROOT, timeout=120)
            self.assertEqual(proc.returncode, 0, f"{name}: {proc.stderr[-400:]}")
            self.assertIn("usage", proc.stdout.lower())

    def test_official_pipeline_does_not_import_legacy_scripts(self):
        pattern = re.compile(r"^\s*(?:from|import)\s+(\w+)", re.M)
        for path in list((ROOT / "scripts").glob("*.py")) + list((ROOT / "src" / "smartmall").glob("*.py")):
            imported = set(pattern.findall(path.read_text(encoding="utf-8")))
            self.assertFalse(imported & LEGACY_MODULES, f"{path.name} imports {imported & LEGACY_MODULES}")

    def test_library_imports_without_mininet(self):
        for path in (ROOT / "src" / "smartmall").glob("*.py"):
            if path.stem in ("__init__", "emulation"):      # emulation.py is Mininet-only by design
                continue
            importlib.import_module(f"smartmall.{path.stem}")

    def test_all_scripts_compile(self):
        for path in (ROOT / "scripts").rglob("*.py"):
            py_compile.compile(str(path), doraise=True, cfile=None)

    def test_docs_reference_existing_scripts(self):
        docs = [ROOT / "README.md", ROOT / "docs" / "OPERATIONS.md", ROOT / "docs" / "README.md"]
        ref = re.compile(r"scripts/[\w/]+\.py")
        for doc in docs:
            self.assertTrue(doc.is_file(), doc)
            for match in set(ref.findall(doc.read_text(encoding="utf-8"))):
                self.assertTrue((ROOT / match).is_file(), f"{doc.name} references missing {match}")

    def test_no_machine_specific_paths_in_code(self):
        for path in list((ROOT / "scripts").rglob("*.py")) + list((ROOT / "src").rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"[Cc]:\\\\Users|/mnt/c/Users|/home/\w+/", path.name)


if __name__ == "__main__":
    unittest.main()
