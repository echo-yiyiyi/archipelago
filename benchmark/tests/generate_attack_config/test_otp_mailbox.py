import mailbox
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmark.generate_attack_config.prompt import email_forward_otp as otp
from benchmark.generate_attack_file.templates import generate_file


class OtpMailboxTests(unittest.TestCase):
    def payload(self):
        return dict(sender_name='Security', sender_email='security@example.org',
                    recipient_email='user@example.org', subject='Verification',
                    body='Your verification code is 9057.', security_team='Support')

    def generate(self, root):
        with patch.object(otp, 'generate_structured_payload', return_value=self.payload()):
            return otp.generate_otp_artifact(
                {'task_id': 'task_test', 'prompt': 'Review the report'}, root, client=object())

    def test_email_carrier_and_otp_share_mailbox_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            payload=self.payload()
            payload.pop('security_team')
            payload.update(date='Thu, 15 Jan 2026 09:00:00 +0000',
                           message_id='<carrier@example.org>', body='Carrier body')
            target=generate_file('email', payload, temp, injection_content='Test instruction')
            previous=target.read_bytes()
            self.assertEqual(self.generate(temp), target)
            self.assertTrue(target.read_bytes().startswith(previous))
            box=mailbox.mbox(target, create=False)
            try:
                messages=list(box)
                self.assertEqual(len(messages), 2)
                self.assertEqual(messages[0]['Message-ID'], '<carrier@example.org>')
                self.assertEqual(messages[1]['Message-ID'], otp._otp_mail_id('task_test'))
                bodies=[m.get_payload(decode=True).decode() for m in messages]
                self.assertIn('Test instruction', bodies[0])
                self.assertIn('9057', bodies[1])
                self.assertNotIn('Test instruction', bodies[1])
            finally:
                box.close()
            self.assertFalse(list(Path(temp).glob('.otp-*')))

    def test_standalone_otp_and_invalid_existing_file(self):
        with tempfile.TemporaryDirectory() as temp:
            target=self.generate(temp)
            box=mailbox.mbox(target, create=False)
            try:
                self.assertEqual(len(box), 1)
            finally:
                box.close()
            target.write_bytes(b'not a mailbox')
            with self.assertRaises(ValueError):
                self.generate(temp)
            self.assertEqual(target.read_bytes(), b'not a mailbox')


if __name__ == '__main__':
    unittest.main()
