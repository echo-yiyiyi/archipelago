"""Verify structured metadata stays separate from local document instructions."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from benchmark.generate_attack_file.generate import generate_from_task_record
from benchmark.generate_attack_file.templates import generate_file


class DocumentVectorTests(unittest.TestCase):
    def test_word_structured_request_and_local_instruction(self):
        for generic in (False, True):
            with self.subTest(generic=generic), tempfile.TemporaryDirectory() as directory:
                payload = dict(file_name='reference.docx', title='Reference',
                               keyword_line='the current task', reference_note='Values are unknown.')
                create = Mock(return_value=SimpleNamespace(output_text=json.dumps(payload), status='completed'))
                client = SimpleNamespace(responses=SimpleNamespace(create=create))
                record = dict(inject_vector='word', keywords=['PRIVATE_TOPIC'], no_key_words=generic,
                              attack_config={'cot': 'LOCAL_ONLY_MARKER <&> 中文'})
                path = generate_from_task_record(record, directory, client=client)
                request = str(create.call_args)
                self.assertNotIn('LOCAL_ONLY_MARKER', request)
                self.assertEqual('PRIVATE_TOPIC' in request, not generic)
                with ZipFile(path) as archive:
                    tree = ET.fromstring(archive.read('word/document.xml'))
                    text = ''.join(tree.itertext())
                self.assertIn('LOCAL_ONLY_MARKER <&> 中文', text)
                self.assertIn('Additional Task Instruction:', text)

    @unittest.skipUnless(shutil.which('libreoffice') and shutil.which('pdftotext'), 'Requires LibreOffice and pdftotext')
    def test_pdf_conversion_and_no_intermediate_files(self):
        with tempfile.TemporaryDirectory() as directory:
            payload = dict(file_name='reference.pdf', title='Reference',
                           keyword_line='current task', reference_note='Values are unknown.')
            path = generate_file('pdf', payload, directory, injection_content='LOCAL_ONLY_MARKER <&>')
            self.assertTrue(path.read_bytes().startswith(b'%PDF-'))
            text = subprocess.check_output(['pdftotext', '-layout', str(path), '-'], text=True)
            self.assertIn('LOCAL_ONLY_MARKER <&>', text)
            self.assertEqual(list(Path(directory).iterdir()), [path])
            with self.assertRaises(FileExistsError):
                generate_file('pdf', payload, directory)

    def test_wrong_extension_and_path_rejected(self):
        for vector, name in [('word', '../reference.docx'), ('pdf', 'reference.docx')]:
            with self.subTest(vector=vector), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    generate_file(vector, dict(file_name=name, title='Reference', keyword_line='task',
                                              reference_note='Unknown'), directory)


if __name__ == '__main__':
    unittest.main()
