"""Cross-computer asset transfer tests using isolated local folders."""
from copy import deepcopy
from pathlib import Path
import tempfile
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from .automation import Automation
from .contracts import digest
from .workspace import Conflict


class AssetTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = self.make_automation("source")
        self.target = self.make_automation("target")
        content = {
            "title": "迁移用例", "product": "Welink云文档", "layer": "UI",
            "feature": "ai_table/grid", "subproduct": "ai_table",
            "spec": {"steps": "填写内容", "expected": "内容保存"},
            "source": {"taskId": "task-1", "caseId": "TC1"}, "binding": None,
        }
        self.asset = self.source._version("assets", {}, content, "asset")
        self.suite = self.source.suite({
            "name": "迁移套件", "layer": "UI",
            "cases": [{"assetId": self.asset["id"], "revision": 1}],
        })

    def make_automation(self, name):
        return Automation(
            Path(self.temp.name) / name, None,
            SimpleNamespace(get=lambda: {"cases": []}),
            SimpleNamespace(environments=lambda: {"environments": []}),
        )

    def package(self):
        return self.source.export_assets({})

    def commit(self, package, preview=None):
        preview = preview or self.target.import_assets({"package": package})
        return self.target.import_assets({
            "package": package, "commit": True,
            "expectedRevision": preview["revision"],
            "packageDigest": preview["packageDigest"],
        })

    def test_roundtrip_repeat_and_restart_preserve_local_records(self):
        self.source.state["models"] = {"private": "not-exported"}
        self.target.state["plans"] = [{"id": "local-plan"}]
        self.target.state["models"] = {"local": "model"}
        self.target._save()
        package = self.package()
        self.assertEqual(set(package), {"format", "version", "assets", "suites"})
        before = self.target.path.read_bytes()
        preview = self.target.import_assets({"package": package})
        self.assertEqual(preview["added"], 2)
        self.assertEqual(before, self.target.path.read_bytes())
        self.commit(package, preview)
        saved = self.target.path.read_bytes()
        self.assertEqual(self.commit(package)["unchanged"], 2)
        self.assertEqual(saved, self.target.path.read_bytes())
        restored = self.make_automation("target")
        self.assertEqual(restored.state["assets"], package["assets"])
        self.assertEqual(restored.state["suites"], package["suites"])
        self.assertEqual(restored.state["plans"], [{"id": "local-plan"}])
        self.assertEqual(restored.state["models"], {"local": "model"})

    def test_new_version_keeps_old_suite_reference(self):
        self.commit(self.package())
        content = deepcopy(self.asset["versions"][0]["content"])
        content["title"] = "新版本"
        self.source._version("assets", {"id": self.asset["id"], "expectedRevision": 1}, content, "asset")
        self.assertEqual(self.commit(self.package())["updated"], 1)
        self.assertEqual(self.target.version("assets", self.asset["id"], 1)["content"]["title"], "迁移用例")
        self.assertEqual(self.target.state["suites"][0]["versions"][0]["content"]["cases"][0]["revision"], 1)

    def test_diverged_version_blocks_whole_package(self):
        self.commit(self.package())
        package = self.package()
        version = package["assets"][0]["versions"][0]
        version["content"]["title"] = "分叉"
        version["digest"] = digest(version["content"])
        saved = self.target.path.read_bytes()
        self.assertTrue(self.target.import_assets({"package": package})["conflicts"])
        with self.assertRaises(Conflict):
            self.commit(package)
        self.assertEqual(saved, self.target.path.read_bytes())

    def test_duplicate_source_under_other_id_is_reported(self):
        self.commit(self.package())
        package = self.package()
        package["assets"][0]["id"] = "asset-other"
        package["suites"] = []
        preview = self.target.import_assets({"package": package})
        self.assertIn("来源", preview["conflicts"][0])
        with self.assertRaises(Conflict):
            self.commit(package, preview)

    def test_missing_suite_reference_and_tampered_digest(self):
        package = self.package()
        package["assets"] = []
        self.assertTrue(self.target.import_assets({"package": package})["conflicts"])
        with self.assertRaises(Conflict):
            self.commit(package)
        package = self.package()
        package["assets"][0]["versions"][0]["content"]["title"] = "篡改"
        with self.assertRaises(ValueError):
            self.target.import_assets({"package": package})

    def test_stale_preview_or_changed_package_rejected(self):
        package = self.package()
        preview = self.target.import_assets({"package": package})
        self.target._save()
        with self.assertRaises(Conflict):
            self.commit(package, preview)
        preview = self.target.import_assets({"package": package})
        package["suites"] = []
        with self.assertRaises(Conflict):
            self.commit(package, preview)
        self.assertEqual(self.target.state["assets"], [])

    def test_scripts_checked_again_at_commit(self):
        package = self.package()
        version = package["assets"][0]["versions"][0]
        binding = {"inventoryId": "scan-1", "files": {"ui/testcases/test_main.py": "hash"}, "admission": "静态可执行"}
        version["content"]["binding"] = binding
        version["digest"] = digest(version["content"])
        self.target.inventory.get = lambda: {"cases": [{"assetId": "scan-1"}]}
        self.target._row_binding = Mock(return_value=deepcopy(binding))
        preview = self.target.import_assets({"package": package})
        self.assertEqual(preview["conflicts"], [])
        self.target._row_binding.return_value["files"] = {"ui/testcases/test_main.py": "changed"}
        with self.assertRaises(Conflict):
            self.commit(package, preview)
        self.assertEqual(self.target.state["assets"], [])

    def test_local_script_and_spec_hashes_are_verified(self):
        root = Path(self.temp.name) / "repository"
        folder = root / "ui/testcases/example"
        folder.mkdir(parents=True)
        script = folder / "test_main.py"
        script.write_text("def test_example():\n    assert True\n", encoding="utf-8")
        spec = folder / "case_spec.json"
        spec.write_text(json.dumps({"case_name": "本机脚本"}), encoding="utf-8")
        row = {
            "assetId": "scan-local", "product": "Welink云文档", "title": "本机脚本",
            "admission": "静态可执行", "scriptPath": "ui/testcases/example/test_main.py",
            "specPath": "ui/testcases/example/case_spec.json",
        }
        self.target.inventory.get = lambda: {"cases": [row]}
        with patch("workbench.automation.ROOT", root):
            package = self.package()
            version = package["assets"][0]["versions"][0]
            version["content"]["binding"] = self.target._row_binding(row, row["product"])
            version["digest"] = digest(version["content"])
            preview = self.target.import_assets({"package": package})
            self.assertEqual(preview["conflicts"], [])
            script.write_text("def test_example():\n    assert False\n", encoding="utf-8")
            with self.assertRaises(Conflict):
                self.commit(package, preview)
            script.unlink()
            self.assertTrue(self.target.import_assets({"package": package})["conflicts"])

    def test_failed_write_keeps_memory_unchanged(self):
        package = self.package()
        before = deepcopy(self.target.state)
        self.target._save = Mock(side_effect=OSError("disk full"))
        with self.assertRaises(OSError):
            self.commit(package)
        self.assertEqual(before, self.target.state)

    def test_invalid_record_shapes_are_rejected(self):
        for malformed in (None, [], {}, {"format": "other", "version": 1}):
            with self.subTest(package=malformed), self.assertRaises(ValueError):
                self.target.import_assets({"package": malformed})
