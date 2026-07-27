import io
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main  # noqa: E402


class Response:
    status_code = 200
    text = "ok"

    @staticmethod
    def json():
        return {"ok": True}


class WorldOverlayTest(unittest.TestCase):
    def test_overlay_posts_directory_contents_to_filesystem(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            overlay = root / "overlay"
            output = root / "output"
            overlay.mkdir()
            output.mkdir()
            (overlay / "INSTRUCTIONS.md").write_text("<think>review note</think>\n")
            (overlay / "nested").mkdir()
            (overlay / "nested" / "note.txt").write_text("nested\n")

            captured = {}

            def fake_post(url, *, files, params, timeout):
                captured.update(url=url, files=files, params=params, timeout=timeout)
                return Response()

            with patch.object(main.httpx, "post", side_effect=fake_post):
                main.populate_filesystem_overlay(overlay, output)

            self.assertEqual(captured["params"], {"subsystem": "filesystem"})
            archive_bytes = captured["files"]["archive"][1]
            with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
                self.assertEqual(
                    sorted(archive.getnames()),
                    ["INSTRUCTIONS.md", "nested", "nested/note.txt"],
                )
                extracted = archive.extractfile("INSTRUCTIONS.md")
                self.assertIsNotNone(extracted)
                self.assertEqual(
                    extracted.read().decode(), "<think>review note</think>\n"
                )


if __name__ == "__main__":
    unittest.main()
