import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAFFOLD = os.path.join(ROOT, "scripts", "scaffold_tree.py")

LAYERS = {
    "layers": ["App", "Service", "Hal", "Mcal"],
    "path_map": {"Source/App": "App", "Source/Service": "Service",
                 "Source/Hal": "Hal", "Source/Mcal": "Mcal"},
    "file_prefix": {},
}
SPEC = {"project": "T", "modules": [
    {"name": "FocCore", "layer": "Service", "reuse": "reusable"},
    {"name": "ProjOrch", "layer": "App", "reuse": "project-specific"},
    {"name": "ParamSvc", "layer": "Service"},  # 缺省 -> reusable
]}


class ScaffoldReuseTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.layers = os.path.join(self.d, "layers.json")
        self.spec = os.path.join(self.d, "spec.json")
        self.out = os.path.join(self.d, "code")
        with open(self.layers, "w") as f:
            json.dump(LAYERS, f)
        with open(self.spec, "w") as f:
            json.dump(SPEC, f)
        subprocess.run([sys.executable, SCAFFOLD, "--spec", self.spec,
                        "--layers", self.layers, "--out", self.out], check=True)

    def _exists(self, *parts):
        return os.path.exists(os.path.join(self.out, *parts))

    def test_reusable_gets_contract_and_port(self):
        self.assertTrue(self._exists("Source/Service", "FocCore", "FocCore_contract.h"))
        self.assertTrue(self._exists("Source/Service", "FocCore", "FocCore_port.md"))

    def test_default_service_is_reusable(self):
        self.assertTrue(self._exists("Source/Service", "ParamSvc", "ParamSvc_contract.h"))

    def test_project_specific_has_no_contract_or_port(self):
        self.assertFalse(self._exists("Source/App", "ProjOrch", "ProjOrch_contract.h"))
        self.assertFalse(self._exists("Source/App", "ProjOrch", "ProjOrch_port.md"))


if __name__ == "__main__":
    unittest.main()
