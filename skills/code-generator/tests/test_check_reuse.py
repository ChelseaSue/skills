import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK = os.path.join(ROOT, "scripts", "check_layering.py")

LAYERS = {
    "layers": ["App", "Service", "Hal", "Mcal"],
    "path_map": {"Source/App": "App", "Source/Service": "Service",
                 "Source/Hal": "Hal", "Source/Mcal": "Mcal"},
    "file_prefix": {},
}
SPEC = {"modules": [
    {"name": "FocCore", "layer": "Service", "reuse": "reusable"},
    {"name": "ProjOrch", "layer": "Service", "reuse": "project-specific"},
    {"name": "MathLib", "layer": "Service", "reuse": "reusable"},
]}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


class CheckReuseTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.layers = os.path.join(self.d, "layers.json")
        self.spec = os.path.join(self.d, "spec.json")
        self.code = os.path.join(self.d, "code")
        with open(self.layers, "w") as f:
            json.dump(LAYERS, f)
        with open(self.spec, "w") as f:
            json.dump(SPEC, f)
        write(os.path.join(self.code, "Source/Service/ProjOrch/ProjOrch.h"), "#ifndef P\n#define P\n#endif\n")

    def _run(self, c_body):
        write(os.path.join(self.code, "Source/Service/FocCore/FocCore.c"), c_body)
        return subprocess.run(
            [sys.executable, CHECK, "--root", self.code, "--layers", self.layers,
             "--modules", self.spec, "--json"], capture_output=True, text=True)

    def test_reusable_including_project_specific_is_violation(self):
        r = self._run('#include "ProjOrch.h"\n')
        self.assertEqual(r.returncode, 1)
        data = json.loads(r.stdout)
        kinds = [v["kind"] for v in data["violations"]]
        self.assertIn("REUSE", kinds)

    def test_reusable_including_reusable_is_ok(self):
        write(os.path.join(self.code, "Source/Service/Other/Other.h"), "#ifndef O\n#define O\n#endif\n")
        # Other 未在 spec -> 不分类 -> 不触发 REUSE
        r = self._run('#include "Other.h"\n')
        kinds = [v["kind"] for v in json.loads(r.stdout)["violations"]]
        self.assertNotIn("REUSE", kinds)

    def test_reusable_including_classified_reusable_is_ok(self):
        write(os.path.join(self.code, "Source/Service/MathLib/MathLib.h"), "#ifndef M\n#define M\n#endif\n")
        r = self._run('#include "MathLib.h"\n')
        kinds = [v["kind"] for v in json.loads(r.stdout)["violations"]]
        self.assertNotIn("REUSE", kinds)

    def test_no_modules_arg_keeps_old_behavior(self):
        write(os.path.join(self.code, "Source/Service/FocCore/FocCore.c"), '#include "ProjOrch.h"\n')
        r = subprocess.run(
            [sys.executable, CHECK, "--root", self.code, "--layers", self.layers, "--json"],
            capture_output=True, text=True)
        kinds = [v["kind"] for v in json.loads(r.stdout)["violations"]]
        self.assertNotIn("REUSE", kinds)


if __name__ == "__main__":
    unittest.main()
