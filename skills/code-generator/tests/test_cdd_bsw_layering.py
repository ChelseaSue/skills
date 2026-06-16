import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK = os.path.join(ROOT, "scripts", "check_layering.py")

# CDD 与 BSW 同层并列的两条驱动栈：HAL→CDD→MCAL 与 HAL→BSW→MCAL，CDD↔BSW 平级互不依赖。
LAYERS = {
    "layers": ["App", "Service", "Hal", "Cdd", "Bsw", "Mcal", "Os"],
    "peer_groups": [["Cdd", "Bsw"], ["Mcal", "Os"]],
    "path_map": {
        "Source/App": "App", "Source/Service": "Service", "Source/Hal": "Hal",
        "Source/Cdd": "Cdd", "Source/Bsw": "Bsw", "Source/Mcal": "Mcal", "Source/Os": "Os",
    },
    "architecture_edges": [
        ["App", "Service"], ["Service", "Hal"], ["Hal", "Mcal"],
        ["Hal", "Cdd"], ["Hal", "Bsw"], ["Cdd", "Mcal"], ["Bsw", "Mcal"],
    ],
    "file_prefix": {},
}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


class CddBswLayeringTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.layers = os.path.join(self.d, "layers.json")
        self.code = os.path.join(self.d, "code")
        with open(self.layers, "w") as f:
            json.dump(LAYERS, f)
        # 各层放一个可被 include 解析的头文件
        for rel in ("Source/Cdd/Pmic/Cdd_Pmic.h", "Source/Bsw/CanIf/CanIf.h",
                    "Source/Mcal/Can/Mcal_Can.h", "Source/Hal/If/IF_Can.h"):
            write(os.path.join(self.code, rel), "#ifndef H\n#define H\n#endif\n")

    def _kinds(self, rel_c, c_body):
        write(os.path.join(self.code, rel_c), c_body)
        r = subprocess.run(
            [sys.executable, CHECK, "--root", self.code, "--layers", self.layers, "--json"],
            capture_output=True, text=True)
        return [v["kind"] for v in json.loads(r.stdout)["violations"]], r.returncode

    def test_bsw_including_cdd_is_peer_violation(self):
        kinds, rc = self._kinds("Source/Bsw/CanIf/CanIf.c", '#include "Cdd_Pmic.h"\n')
        self.assertIn("PEER", kinds)
        self.assertEqual(rc, 1)

    def test_cdd_including_bsw_is_peer_violation(self):
        kinds, _ = self._kinds("Source/Cdd/Pmic/Cdd_Pmic.c", '#include "CanIf.h"\n')
        self.assertIn("PEER", kinds)

    def test_hal_including_bsw_is_legal(self):
        kinds, rc = self._kinds("Source/Hal/Impl/IF_Can.c", '#include "CanIf.h"\n')
        self.assertEqual(kinds, [])
        self.assertEqual(rc, 0)

    def test_bsw_including_mcal_is_legal(self):
        kinds, rc = self._kinds("Source/Bsw/CanIf/CanIf.c", '#include "Mcal_Can.h"\n')
        self.assertEqual(kinds, [])
        self.assertEqual(rc, 0)

    def test_bsw_including_hal_is_upward_violation(self):
        kinds, _ = self._kinds("Source/Bsw/CanIf/CanIf.c", '#include "IF_Can.h"\n')
        self.assertIn("UPWARD", kinds)


if __name__ == "__main__":
    unittest.main()
