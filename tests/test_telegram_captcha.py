import unittest

from telegram_captcha import TelegramCaptchaClient, TelegramCaptchaError


class TelegramCaptchaReplyTests(unittest.TestCase):
    def setUp(self):
        self.owner_id = 123456
        self.photo_id = 987
        self.base = {
            "message": {
                "chat": {"id": self.owner_id, "type": "private"},
                "from": {"id": self.owner_id},
                "reply_to_message": {"message_id": self.photo_id},
                "text": " Ab C 12 ",
            }
        }

    def test_accepts_reply_to_current_photo_from_owner(self):
        self.assertEqual(
            TelegramCaptchaClient._answer_from_update(
                self.base, owner_id=self.owner_id, photo_message_id=self.photo_id
            ),
            "AbC12",
        )

    def test_rejects_unrelated_message(self):
        update = {"message": {**self.base["message"], "reply_to_message": {"message_id": 1}}}
        self.assertIsNone(
            TelegramCaptchaClient._answer_from_update(
                update, owner_id=self.owner_id, photo_message_id=self.photo_id
            )
        )

    def test_rejects_other_sender(self):
        update = {"message": {**self.base["message"], "from": {"id": 999}}}
        self.assertIsNone(
            TelegramCaptchaClient._answer_from_update(
                update, owner_id=self.owner_id, photo_message_id=self.photo_id
            )
        )

    def test_rejects_group_chat(self):
        update = {"message": {**self.base["message"], "chat": {"id": self.owner_id, "type": "group"}}}
        self.assertIsNone(
            TelegramCaptchaClient._answer_from_update(
                update, owner_id=self.owner_id, photo_message_id=self.photo_id
            )
        )

    def test_rejects_non_text_reply(self):
        update = {"message": {**self.base["message"], "text": None}}
        self.assertIsNone(
            TelegramCaptchaClient._answer_from_update(
                update, owner_id=self.owner_id, photo_message_id=self.photo_id
            )
        )

    def test_requires_configuration(self):
        with self.assertRaises(TelegramCaptchaError):
            TelegramCaptchaClient("", str(self.owner_id))


if __name__ == "__main__":
    unittest.main()
