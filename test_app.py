import os
import tempfile

import app as poll_application


def test_home_page_and_poll_page_load():
    """The app starts with a seeded poll that is visible to visitors."""
    database_file, database_path = tempfile.mkstemp()
    os.close(database_file)
    poll_application.app.config.update(TESTING=True, DATABASE=database_path)

    try:
        with poll_application.app.app_context():
            poll_application.init_db()

        client = poll_application.app.test_client()
        assert client.get("/").status_code == 200
        assert client.get("/poll/1").status_code == 200
    finally:
        os.unlink(database_path)
