from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from benchmark.generate_attack_config.prompt import email_send_file as files


class PartialDatasetCacheTests(unittest.TestCase):
    def test_original_archive_fallback_and_dataset_priority(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            dataset = repo / 'dataset'
            task = {'task_id': 'task_example', 'world_id': 'world_example'}
            original = repo / 'benchmark/output/concurrent/run/tasks/task_example_py_1/world_example.zip'
            original.parent.mkdir(parents=True)
            with zipfile.ZipFile(original, 'w') as archive:
                archive.writestr('filesystem/source.txt', 'original')
            with patch.object(files, 'REPO_ROOT', repo):
                self.assertEqual(files._resolve_world_archive(dataset, task), original)
                preferred = dataset / 'world_files_zipped/world_example.zip'
                preferred.parent.mkdir(parents=True)
                preferred.write_bytes(original.read_bytes())
                self.assertEqual(files._resolve_world_archive(dataset, task), preferred)

    def test_final_snapshot_cannot_replace_missing_original(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            final = repo / 'benchmark/output/concurrent/run/tasks/task_example/final_snapshot.zip'
            final.parent.mkdir(parents=True)
            with zipfile.ZipFile(final, 'w'):
                pass
            with patch.object(files, 'REPO_ROOT', repo), self.assertRaisesRegex(FileNotFoundError, 'no saved original'):
                files._resolve_world_archive(repo / 'dataset', {'task_id': 'task_example', 'world_id': 'world_example'})

    def test_file_listing_retains_task_overlay_with_world_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            dataset = repo / 'dataset'
            overlay = dataset / 'task_files/task_example/filesystem/task.txt'
            overlay.parent.mkdir(parents=True)
            overlay.write_text('task input')
            original = repo / 'examples/hugging_face_task/output/task_example/world_example.zip'
            original.parent.mkdir(parents=True)
            with zipfile.ZipFile(original, 'w') as archive:
                archive.writestr('filesystem/world.txt', 'world input')
                archive.writestr('.apps_data/private.txt', 'not visible')
            with patch.object(files, 'REPO_ROOT', repo), patch.object(files, '_find_dataset_dir', return_value=dataset), patch.object(
                files, '_load_task', return_value={'task_id': 'task_example', 'world_id': 'world_example'}
            ):
                self.assertEqual(files._list_task_file_paths('task_example'), ('world_example', ['task.txt', 'world.txt']))


if __name__ == '__main__':
    unittest.main()
