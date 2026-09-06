"""Synthetic evidence-contract tests. No model calls or benchmark data."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

spec = importlib.util.spec_from_file_location(
    "evidence", Path(__file__).parents[1] / "eval/findings.py"
)
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


class EvidenceTests(unittest.TestCase):
    def test_budget_preserves_small_files_and_marks_middle_clipping(self):
        limits = evidence._budget_outputs([10, 900000, 900000])
        self.assertEqual(limits, [10, 299995, 299995])
        clipped = evidence._clip("START" + "x" * 900000 + "END", limits[1])
        self.assertLessEqual(len(clipped), limits[1])
        self.assertTrue(clipped.startswith("START"))
        self.assertTrue(clipped.endswith("END"))
        self.assertIn("omitted from the middle", clipped)

    def test_only_deliverables_and_all_raw_paths_are_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "agent_outputs"
            root.mkdir()
            for i in range(55):
                (root / f"{i:02d}.txt").write_text(f"row {i}")
            for name in [".browser-use", "screenshots", "node_modules"]:
                (root / name).mkdir()
                (root / name / "private.txt").write_text("internal observation")
            outside = Path(tmp) / "outside.txt"
            outside.write_text("not a deliverable")
            (root / "symlink.txt").symlink_to(outside)
            result = evidence.collect(root)
            self.assertEqual(len(result["output_files"]), 50)
            self.assertEqual(len(result["staged_outputs"]), 55)
            self.assertNotIn("internal observation", str(result))
            self.assertNotIn("not a deliverable", str(result))

    def test_workbook_keeps_formulas_and_sheet_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = Workbook()
            book.active.title = "Prices"
            book.active.append(["Price", "Double"])
            book.active.append([7, "=A2*2"])
            book.save(root / "prices.xlsx")
            file = evidence.collect(root)["output_files"][0]
            self.assertIn("[sheet: Prices]", file["text"])
            self.assertIn("7,=A2*2", file["text"])
            self.assertEqual(file["rendered"], "xlsx rendered as csv text per sheet")
            self.assertFalse(file["clipped"])

    def test_pdf_is_rendered_before_utf8_decoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            writer = PdfWriter()
            page = writer.add_blank_page(width=200, height=200)
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
            )
            stream = DecodedStreamObject()
            stream.set_data(b"BT /F1 12 Tf 20 100 Td (Evidence survives) Tj ET")
            page[NameObject("/Contents")] = stream
            writer.write(root / "report.pdf")
            file = evidence.collect(root)["output_files"][0]
            self.assertIn("Evidence survives", file["text"])
            self.assertIn("[page 1]", file["text"])
            self.assertIn("pdf rendered", file["rendered"])


if __name__ == "__main__":
    unittest.main()
