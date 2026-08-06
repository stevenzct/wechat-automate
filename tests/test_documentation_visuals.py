import unittest
from pathlib import Path

from PIL import Image


PROJECT_DIR = Path(__file__).resolve().parents[1]


class DocumentationVisualTests(unittest.TestCase):
    VISUALS = (
        "docs/quick-start.png",
        "docs/daily-automation.png",
    )

    def test_visuals_are_readable_large_pngs(self):
        for relative_path in self.VISUALS:
            with self.subTest(visual=relative_path):
                with Image.open(PROJECT_DIR / relative_path) as image:
                    self.assertEqual(image.format, "PNG")
                    self.assertGreaterEqual(image.width, 1000)
                    self.assertGreaterEqual(image.height, 650)
                    image.verify()

    def test_readme_shows_visual_guide_before_long_contents(self):
        readme = (PROJECT_DIR / "README.md").read_text(encoding="utf-8-sig")

        visual_guide_position = readme.index("## Visual quick start")
        contents_position = readme.index("## Contents")
        self.assertLess(visual_guide_position, contents_position)
        for relative_path in self.VISUALS:
            self.assertIn(f"]({relative_path})", readme)


if __name__ == "__main__":
    unittest.main()
