import unittest
from pathlib import Path


class ChineseInterfaceTests(unittest.TestCase):
    def test_primary_gui_copy_is_chinese(self):
        source = (Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8")
        for text in (
            "AirCard 卡面助手",
            "连接 iPhone",
            "选择 Wallet 卡片",
            "选择卡面图片",
            "应用新卡面",
            "恢复原始卡面",
            "原始卡面已恢复并通过校验",
        ):
            self.assertIn(text, source)

        for old_text in (
            "Choose artwork",
            "Apply card skin",
            "Restore original",
            "Scan Wallet card",
            "No original backup yet",
        ):
            self.assertNotIn(old_text, source)


if __name__ == "__main__":
    unittest.main()
